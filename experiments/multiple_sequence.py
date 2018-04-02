#!/usr/bin/env python
import numpy as np

from biseqt.sequence import Alphabet
from biseqt.stochastics import rand_seq, MutationProcess
from biseqt.blot import WordBlotMultiple
from util import savefig, get_seqs_from_mse, plot_roc

import matplotlib
from matplotlib import pyplot as plt
import matplotlib.gridspec as gridspec
from mpl_toolkits.mplot3d import Axes3D

from Bio import AlignIO


def plot_scored_seeds_3d(fig, ax, scored_seeds, threshold=.5):
    idx_S, idx_T1, idx_T2, cs, ss = [], [], [], [], []
    cmap = plt.cm.get_cmap('jet')
    scores = [score for _, score in scored_seeds]
    max_score = max(scores)
    for (i, j, k), score in scored_seeds:
        idx_S.append(i)
        idx_T1.append(j)
        idx_T2.append(k)
        cs.append(cmap(score/max_score)[:3])
        ss.append(10 if score > threshold else 1)

    ax.scatter(idx_S, idx_T1, idx_T2, facecolor=cs, lw=0, s=ss, alpha=.3)
    ax.set_aspect('equal')
    ax.elev = 10
    ax.azim = 240
    norm = matplotlib.colors.Normalize(vmin=0, vmax=max_score)
    m = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    m.set_array(scores)
    fig.colorbar(m, shrink=.7)


def exp_three_syntehtic_sequences():
    subst, gap = .15, .05
    wordlen = 6
    K = 2000
    A = Alphabet('ACGT')
    M = MutationProcess(A, subst_probs=subst, ge_prob=gap, go_prob=gap)
    S = rand_seq(A, K)
    T1, _ = M.mutate(S)
    T2, _ = M.mutate(S)

    def junk(): return rand_seq(A, K / 2)

    S, T1, T2 = junk() + S + junk(), junk() + T1 + junk(), junk() + T2 + junk()
    WB_kw = {'g_max': .2, 'sensitivity': .9, 'alphabet': A, 'wordlen': wordlen,
             'path': ':memory:'}
    WB = WordBlotMultiple(S, T1, T2, **WB_kw)

    p_min = (1-gap) * (1-subst)
    print p_min
    scored_seeds = [(WB.to_ij_coordinates(*rec['seed']), rec['p'])
                    for rec in WB.score_seeds(100)]

    fig = plt.figure()
    ax = fig.gca(projection=Axes3D.name)
    plot_scored_seeds_3d(fig, ax, scored_seeds, threshold=p_min)

    for axis in 'xyz':
        ax.tick_params(axis=axis, labelsize=5)
    ax.set_xlabel('Sequence 1')
    ax.set_ylabel('Sequence 2')
    ax.set_zlabel('Sequence 3')

    ax.set_title('estimated similarity at exactly matching %d-mers' % wordlen)

    fig.tight_layout()
    savefig(fig, 'multiple-sequence.png', dpi=300)


def seeds_from_maf(maf_path, wordlen, ids_of_interest=[]):
    alignments = list(AlignIO.parse(maf_path, 'maf'))
    # NOTE trust the first alignment to have all the ids
    ids = set()
    for alignment in alignments:
        ids = ids.union(set(rec.id for rec in alignment))
    assert all(id_ in ids for id_ in ids_of_interest)
    ids = ids_of_interest if ids_of_interest else ids
    seqs = {id_: '' for id_ in ids}
    for alignment in alignments:
        updated = {id_: False for id_ in ids}
        line_len = len(alignment[0])
        for rec in alignment:
            if rec.id not in ids:
                continue
            seqs[rec.id] += ''.join(rec.upper())
            updated[rec.id] = True
        for id_ in seqs:
            if not updated[id_]:
                seqs[id_] += '-' * line_len

    seq_lens = set(len(seq) for seq in seqs.values())
    assert len(seq_lens) == 1, \
        'all aligned sequences must have the same length'
    seqs = np.array([list(seqs[id_]) for id_ in ids])
    num_seqs, seq_len = seqs.shape
    pos = np.zeros(num_seqs)
    for idx in range(seq_len - wordlen):
        # print seqs[:, idx]
        for i in range(num_seqs):
            if seqs[i, idx] != '-':
                pos[i] += 1
        if all(len(set(seqs[i, idx + j] for i in range(num_seqs))) == 1
               for j in range(wordlen)):
            yield tuple(pos)


def exp_biological_multiple_sequences():
    maf_path = 'data/actb/actb-7vet.maf'
    wordlen = 6
    A = Alphabet('ACGT')
    WB_kw = {'g_max': .4, 'sensitivity': .9, 'alphabet': A,
             'wordlen': wordlen, 'path': ':memory:'}

    # 3 sequences for scatter plot
    ids = ['hg38.chr7',
           'panTro4.chr7',
           'canFam3.chr6',
           ]
    seqs = [A.parse(seq.upper())
            for id_, seq in get_seqs_from_mse(maf_path, fmt='maf')
            if id_ in ids]
    WB = WordBlotMultiple(*seqs, **WB_kw)
    p_min = .8
    scored_seeds = [(WB.to_ij_coordinates(*rec['seed']), rec['p'])
                    for rec in WB.score_seeds(50)]
    print 'found %d seeds for %d sequences' % (len(scored_seeds), len(ids))

    fig = plt.figure(figsize=(10, 5))
    gs = gridspec.GridSpec(1, 2, width_ratios=[2, 2])
    ax_scatter = plt.subplot(gs[0], projection=Axes3D.name)
    plot_scored_seeds_3d(fig, ax_scatter, scored_seeds, threshold=p_min)
    for axis in 'xyz':
        ax_scatter.tick_params(axis=axis, labelsize=4)
    ax_scatter.set_xlabel(ids[0].split('.')[0])
    ax_scatter.set_ylabel(ids[1].split('.')[0])
    ax_scatter.set_zlabel(ids[2].split('.')[0])
    ax_scatter.set_title('estimated similarity at exactly matching %d-mers' %
                         wordlen, fontsize=8)

    # ============================
    # hom/non-hom seed classifier
    # ============================
    ids = ['hg38.chr7',
           'panTro4.chr7',
           'canFam3.chr6',
           'mm10.chr5',
           'rheMac3.chr3',
           'rn5.chr12',
           ]

    real_seeds = list(seeds_from_maf(maf_path, wordlen, ids_of_interest=ids))
    real_seeds = list(tuple(int(x) for x in seed) for seed in real_seeds)
    print 'found %d homologous seeds for %d sequences' % \
          (len(real_seeds), len(ids))

    seqs = [A.parse(seq.upper())
            for id_, seq in get_seqs_from_mse(maf_path, fmt='maf')
            if id_ in ids]
    WB = WordBlotMultiple(*seqs, **WB_kw)
    scored_seeds = [(WB.to_ij_coordinates(*rec['seed']), rec['p'])
                    for rec in WB.score_seeds(50)]
    print 'found %d seeds for %d sequences' % (len(scored_seeds), len(ids))
    pos, neg = [], []
    for coords, p_hat in scored_seeds:
        if coords in real_seeds:
            pos.append(p_hat)
        else:
            neg.append(p_hat)

    ax_roc = plt.subplot(gs[1])
    plot_roc(ax_roc, pos, neg, color='k')
    title = 'ROC for classifing exactly matching %d-mers (%d samples)\n' % \
            (wordlen, len(pos) + len(neg))
    title += 'species: %s' % ', '.join(x.split('.')[0] for x in ids)
    ax_roc.set_title(title, fontsize=8)

    fig.tight_layout()
    savefig(fig, 'multiple-sequence[bio].png')


if __name__ == '__main__':
    exp_three_syntehtic_sequences()
    exp_biological_multiple_sequences()