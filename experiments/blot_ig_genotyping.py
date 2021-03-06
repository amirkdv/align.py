import numpy as np
import sys
import logging
from time import time

from matplotlib import pyplot as plt
from biseqt.pw import Aligner, BANDED_MODE, B_LOCAL
from biseqt.blot import WordBlotLocalRef
from biseqt.sequence import Alphabet
from util import log, savefig
from util import fill_in_unknown
from util import load_fasta, with_dumpfile


@with_dumpfile
def sim_ig_genotyping(reads, genes, **kw):
    wordlens, p_min = kw['wordlens'], kw['p_min']
    mismatch_scores = kw['mismatch_scores']
    gap_open_score = kw['gap_open_score']
    gap_extend_score = kw['gap_extend_score']
    minlens = kw['minlens']

    A = Alphabet('ACGT')
    WB_kw = {'g_max': .5, 'sensitivity': .9, 'alphabet': A,
             'log_level': logging.WARN}

    sim_data = {
        'genes': genes,
        'wordlens': wordlens,
        'minlens': minlens,
        'reads': reads,
        'mappings': {
            read_name: {'V': None, 'D': None, 'J': None,
                        'D_start': None, 'D_end': None,
                        'time': 0}
            for read_name in reads
        },
        'p_min': p_min,
        'WB_kw': WB_kw,
        'mismatch_scores': mismatch_scores,
        'gap_open_score': gap_open_score,
        'gap_extend_score': gap_extend_score,
    }

    def _matches_in_seg(similar_segment):
        p_hat, seg = similar_segment['p'], similar_segment['segment']
        seglen = seg[1][1] - seg[1][0]
        return p_hat * seglen

    def _map_gene_type(read_, gene_type):
        t_start = time()
        assert gene_type in 'VJD'
        WB_kw['wordlen'] = wordlens[gene_type]
        WB = WordBlotLocalRef(read_, **WB_kw)
        candidates = {}
        for idx, (gene, gene_rec) in enumerate(genes[gene_type].items()):
            gene_len = len(gene_rec['seq'])

            K_min = gene_len / 2
            K_min = minlens[gene_type]
            similarities = list(
                WB.similar_segments(gene_rec['seq'], K_min, p_min)
            )
            if not similarities:
                continue
            res = max(similarities, key=lambda rec: _matches_in_seg(rec))
            candidates[gene] = res
        if not candidates:
            sys.stderr.write(' no Ig %s gene found!\n' % gene_type)
            return None, time() - t_start

        chosen_genes = dict(
            sorted(candidates.items(),
                   key=lambda rec: -_matches_in_seg(rec[1]))[:3]
        )
        return chosen_genes, time() - t_start

    def _add_aln(read_, gene_seq, gene_type, rec):
        d_band = rec['segment'][0]
        aligner_kw = {
            'match_score': 1,
            'mismatch_score': mismatch_scores[gene_type],
            'ge_score': gap_extend_score,
            'go_score': gap_open_score,
            'alnmode': BANDED_MODE,
            'alntype': B_LOCAL,
            'diag_range': (int(d_band[0]), int(d_band[1])),
        }

        with Aligner(read_, gene_seq, **aligner_kw) as aligner:
            aligner.solve()
            alignment = aligner.traceback()
            tx = alignment.transcript
            len_on_gene = sum(tx.count(op) for op in 'MSI')
            num_matches = tx.count('M')
            p_aln = 1. * num_matches / len_on_gene
            rec['p_aln'] = round(p_aln, 2)
            rec['len_aln'] = len_on_gene
            rec['alignment'] = alignment

        return rec

    for read_idx, (read_name, read_rec) in enumerate(reads.items()):
        read_seq = read_rec['seq']
        sys.stderr.write('%d/%d %s\n' % (read_idx + 1, len(reads), read_name))
        start_pos = 0
        for gene_type in 'VDJ':
            mapped_genes, t_elapsed = _map_gene_type(read_seq[start_pos:],
                                                     gene_type)
            sim_data['mappings'][read_name]['time'] += t_elapsed
            igblast = read_rec['igblast'][gene_type]
            if not igblast:
                # if igblast didn't map a read to any genes don't bother;
                # we don't have a ground truth.
                continue
            min_igblast_p = round(min(rec['p'] for rec in igblast.values()), 2)
            min_igblast_L = min(rec['length'] for rec in igblast.values())
            min_igblast_m = min(rec['num_matches'] for rec in igblast.values())
            sim_data['mappings'][read_name][gene_type] = {
                'min_igblast_p': min_igblast_p,
                'min_igblast_L': min_igblast_L,
                'min_igblast_m': min_igblast_m,
            }

            if not mapped_genes:
                continue
            for gene in mapped_genes:
                # run overlap NW for all chosen genes
                gene_seq = genes[gene_type][gene]['seq']
                # print gene
                mapped_genes[gene] = _add_aln(read_seq[start_pos:], gene_seq,
                                              gene_type, mapped_genes[gene])
                aln = mapped_genes[gene]['alignment']
                mapped_genes[gene]['start_pos'] = start_pos
                mapped_genes[gene]['end_pos'] = start_pos \
                    + aln.origin_start \
                    + aln.projected_len(aln.transcript, on='origin')

                true_pos = gene in reads[read_name]['igblast'][gene_type]

                ours_m = aln.transcript.count('M')
                p_aln = mapped_genes[gene]['p_aln']
                higher_p = p_aln >= min_igblast_p and \
                    ours_m >= min_igblast_m - 2
                higher_m = ours_m >= min_igblast_m and \
                    p_aln >= min_igblast_p - .01
                true_pos_forgiving = higher_p or higher_m
                sys.stderr.write('      %s: %s(%s) ' %
                                 (gene_type,
                                  '+' if true_pos else '-',
                                  '+' if true_pos_forgiving else '-'))
                sys.stderr.write(
                    '%s match=%d (%d),p=%.2f(%.2f)\n' %
                    (gene, ours_m, min_igblast_m, p_aln, min_igblast_p)
                )

            start_pos = min(rec['end_pos']
                            for gene, rec in mapped_genes.items())
            sim_data['mappings'][read_name][gene_type].update(mapped_genes)

        sys.stderr.write('      * %.2f s\n' %
                         (sim_data['mappings'][read_name]['time']))
    return sim_data


def plot_ig_genotyping(sim_data, suffix=''):
    reads = sim_data['reads']

    comparison = {
        'p': {'V': [], 'D': [], 'J': []},
        'K': {'V': [], 'D': [], 'J': []},
        'num_match': {'V': [], 'D': [], 'J': []},
    }
    accuracy = {
        'strict': {'V': 0, 'D': 0, 'J': 0},
        'forgiving': {'V': 0, 'D': 0, 'J': 0},
    }

    elapsed_times = []
    for read, mappings in sim_data['mappings'].items():
        elapsed_times.append(mappings['time'])

    for gene_type in 'VDJ':
        num_agreements_strict = 0
        num_agreements_forgiving = 0
        total_predictions = 0
        for read, mappings in sim_data['mappings'].items():
            if mappings[gene_type] is None:
                continue
            # pop these metrics so we can iterate over genes
            min_igblast_p = mappings[gene_type].pop('min_igblast_p')
            min_igblast_L = mappings[gene_type].pop('min_igblast_L')
            min_igblast_m = mappings[gene_type].pop('min_igblast_m')

            for gene, rec in mappings[gene_type].items():
                total_predictions += 1

                # NOTE we're duplicating this logic to allow reevaluating
                # without redo-ing everything; eventually merge it into the
                # sim_* function. Note that we need to distinguish between
                # literal agreements between ours and igblast and those cases
                # where we argue our match has comparable quality to those of
                # igblast.
                color = 'r'
                if gene in reads[read]['igblast'][gene_type]:
                    num_agreements_strict += 1
                    num_agreements_forgiving += 1
                    color = 'g'
                else:
                    p_aln = rec['p_aln']
                    ours_m = rec['alignment'].transcript.count('M')
                    higher_p = p_aln >= min_igblast_p and \
                        ours_m >= min_igblast_m - 1
                    higher_m = ours_m >= min_igblast_m and \
                        p_aln >= min_igblast_p - .01
                    if higher_p or higher_m:
                        num_agreements_forgiving += 1
                        color = 'g'
                comparison['p'][gene_type].append(
                    (rec['p_aln'], min_igblast_p, color)
                )
                comparison['K'][gene_type].append(
                    (rec['len_aln'], min_igblast_L, color)
                )

        accuracy['strict'][gene_type] = \
            100. * num_agreements_strict / total_predictions
        accuracy['forgiving'][gene_type] = \
            100. * num_agreements_forgiving / total_predictions
        sys.stderr.write('%s %.2f %.2f' % (gene_type,
                                           accuracy['strict'][gene_type],
                                           accuracy['forgiving'][gene_type]))

    avg_time = sum(elapsed_times) / len(sim_data['mappings'])
    print 't', avg_time

    def _extract_with_noise(mode, gene_type_):
        mag = {'p': .005, 'K': .5, 'num_match': .5}[mode]
        xs = [rec[0] for rec in comparison[mode][gene_type_]]
        xs += np.random.randn(len(comparison[mode][gene_type_])) * mag
        ys = [rec[1] for rec in comparison[mode][gene_type_]]
        ys += np.random.randn(len(comparison[mode][gene_type_])) * mag
        colors = [rec[2] for rec in comparison[mode][gene_type_]]
        return xs, ys, colors

    # probability of ours vs igblast
    fig = plt.figure(figsize=(11, 8))
    ax_p_V = fig.add_subplot(2, 3, 1)
    ax_p_D = fig.add_subplot(2, 3, 2)
    ax_p_J = fig.add_subplot(2, 3, 3)
    ax_K_V = fig.add_subplot(2, 3, 4)
    ax_K_D = fig.add_subplot(2, 3, 5)
    ax_K_J = fig.add_subplot(2, 3, 6)

    for gene_type, ax in zip('VDJ', [ax_p_V, ax_p_D, ax_p_J]):
        xs, ys, colors = _extract_with_noise('p', gene_type)
        ax.scatter(xs, ys, c=colors, alpha=.6, s=20, lw=0)
        ax.set_title('%s genes: \\%%%.2f (\\%%%.2f)' %
                     (gene_type,
                      accuracy['strict'][gene_type],
                      accuracy['forgiving'][gene_type]))
        ax.set_xlabel('WordBlot similarity')
        ax.set_ylabel('IgBlast similarity')
        # NOTE this can mislead if output is not checked already
        ax.set_xlim(.7, 1.05)
        ax.set_ylim(.7, 1.05)
        ax.set_aspect('equal')
        ax.plot([0, 1], [0, 1], c='k', lw=1, ls='--', alpha=.6)

    print 'avg time', avg_time

    for gene_type, ax in zip('VDJ', [ax_K_V, ax_K_D, ax_K_J]):
        xs, ys, colors = _extract_with_noise('K', gene_type)
        ax.scatter(xs, ys, c=colors, alpha=.4, s=20, lw=0)
        ax.set_xlabel('WordBlot aligned length')
        ax.set_ylabel('IgBlast aligned length')
        ax.set_aspect('equal')
        x_range, y_range = ax.get_xlim(), ax.get_ylim()
        xy_range = (min(x_range[0], y_range[0]), max(x_range[1], y_range[1]))
        ax.set_xlim(*xy_range)
        ax.set_ylim(*xy_range)
        ax.plot(ax.get_xlim(), ax.get_ylim(), c='k', lw=1, ls='--', alpha=.6)

    savefig(fig, 'ig_genotyping%s.png' % suffix)


def exp_ig_genotyping():
    """Shows the performance of Word-Blot in genotyping Immunoglobin heavy
    chain genotyping. A thousand reads (average length 240nt) covering the
    mature VDJ region of chromosome 14 from the stanford S22 dataset are
    genotyped by Word-Blot against the IMGT list of Immunoglobin heavy chain
    genes:

    * 358 genes and variants for V with average length 292nt,
    * 44 genes and variants for D with average length 24nt,
    * 13 genes and variants for J with average length 53nt.

    For each read and each gene type (V, D, or J) 3 candidates are offered by
    Word-Blot which are then compared against the same output of IgBlast.

    For each gene type we consider two measures of accuracy:

    * the percentage of Word-Blot top 3 candidates that are also IgBlast
      top 3 candidates.
    * a more forgiving measure which accepts the following candidates as "at
      least as good as IgBlast candidates":

        * those genes reported by Word-Blot that have a *longer* alignment than
          the shortest IgBlast candidate alignment while their percent identity
          is at most 1 point below that of the worst IgBlast candidate,
        * those genes with a *higher percent identity* than the worst IgBlast
          candidate with an aligned length at most 2 nucleotides shorter than
          the shortest IgBlast candidate.

      The relevant measures for Word-Blot candidates (exact value for percent
      identity and aligned length) are obtained by *banded local* alignment in
      the diagonal strip suggested by Word-Blot. To ensure comparability of
      results the same alignment scores are used as those of IgBlast (gap open
      -5, gap extend -2, and mismatch -1, -3, and -2 for V, D, and J
      respectively).

    **Supported Claims**

    * Despite relying on statistical properties of kmers, by using short word
      lengths Word-Blot performs well and acceptably fast even for small
      sequence lengths and for discriminating highly similar sequences.

    .. figure::
        https://www.dropbox.com/s/k69jw7w8mwh2biv/
        ig_genotyping_first_1000.png?raw=1
       :target:
        https://www.dropbox.com/s/k69jw7w8mwh2biv/
        ig_genotyping_first_1000.png?raw=1
       :alt: lightbox

       For each of the gene types, V (*left*, word length 8), D (*middle*, word
       length 4), and J (*right*, word length 6),
       alignment lengths (*top*) and match probabilities (*bottom*) of top 3
       candidates reported by Word-Blot and IgBlast are compared. For each
       Word-Blot candidate the corresponding IgBlast coordinate is that of the
       worst of the three reported by IgBlast for the same read. The two
       measures of accuracy for each gene type are shown (more forgiving
       measure in parentheses). Each gene mapping is color coded, greens are
       those that are in some way "at least as good as IgBlast candidates" and
       reds are the rest. Average mapping time for each read is 0.7 second.
    """
    p_min = .8
    wordlens = {'J': 6, 'V': 8, 'D': 4}
    # cf. https://ncbiinsights.ncbi.nlm.nih.gov/tag/igblast/
    # https://www.ncbi.nlm.nih.gov/books/NBK279684/
    # note: I'm forcing these scores on blast as well:
    mismatch_scores = {'V': -1, 'D': -3, 'J': -2}
    minlens = {'V': 100, 'D': 10, 'J': 10}
    gap_open_score = -5
    gap_extend_score = -2
    suffix = '_first_1000'
    dumpfile = 'igh_s22%s.txt' % suffix

    A = Alphabet('ACGT')

    reads_file = 'data/igh-s22/s22%s.fa' % suffix
    # TODO incorporate the commands in igblast_notes.md in here (as docs or
    # automated code).
    igblast_file = 'data/igh-s22/igblast%s_clean.out' % suffix

    log('loading reads')
    reads = {}
    with open(reads_file) as f:
        for raw_seq, name, _ in load_fasta(f, num_seqs=-1):
            read = A.parse(fill_in_unknown(raw_seq, A))
            reads[name] = {
                'seq': read,
                'igblast': {'V': {}, 'D': {}, 'J': {}},
            }

    with open(igblast_file) as f:
        for line in f.readlines():
            rec = dict(zip(['gene_type', 'read', 'gene', 'p', 'length'],
                           line.strip().split()))
            gene, gene_type, name = rec['gene'], rec['gene_type'], rec['read']
            num_m, length = rec['length'].split('/')
            reads[name]['igblast'][gene_type][gene] = {
                'p': float(rec['p']) / 100,
                'length': int(length),
                'num_matches': int(num_m),
            }

    genes = {'V': {}, 'D': {}, 'J': {}}
    repertoire_prefix = 'data/igh-s22/imgt/'
    for key in genes:
        with open(repertoire_prefix + key + '.fa') as f:
            for raw_seq, name, _ in load_fasta(f):
                seq = A.parse(fill_in_unknown(raw_seq.upper(), A))
                genes[key][name] = {
                    'seq': seq,
                }
    log('running Ig genotyping...')
    sim_data = sim_ig_genotyping(
        reads, genes, wordlens=wordlens, p_min=p_min, minlens=minlens,
        mismatch_scores=mismatch_scores,
        gap_open_score=gap_open_score,
        gap_extend_score=gap_extend_score,
        dumpfile=dumpfile, ignore_existing=False
    )
    plot_ig_genotyping(sim_data, suffix)


if __name__ == '__main__':
    exp_ig_genotyping()
