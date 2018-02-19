#!/usr/bin/env python
import numpy as np
import matplotlib.gridspec as gridspec
from matplotlib import pyplot as plt
from bisect import bisect_left
from scipy.special import erf

from util import log, color_code, plot_with_sd, with_dumpfile, savefig
from real_homologies import sample_opseq


def time_in_band(K, g, r):
    A = r / (np.sqrt(2 * g * K))
    return erf(A) \
        + A * (2 / np.sqrt(np.pi) * np.exp(-A ** 2) - 4 * A * (1 - erf(A)))


def sample_edit_sequences(K, g, n_samples, bio=False):
    if bio:
        opseqs_path = 'data/leishmenia/blasr_opseqs.fa'
        with open(opseqs_path) as f:
            opseq = f.read().strip()
        return sample_opseq(opseq, K, g, n_samples)
    else:
        return [''.join(np.random.choice(list('MID'),
                        p=[1-g, g / 2, g / 2], size=K))
                for _ in range(n_samples)]


@with_dumpfile
def sim_time_in_band(K, gs, rs, n_samples, **kw):
    sim_data = {
        'in_band': {'sim': np.zeros((len(gs), len(rs), n_samples)),
                    'bio': np.zeros((len(gs), len(rs), n_samples))},
        'gs': gs,
        'rs': rs,
        'K': K,
    }
    for g_idx, g in enumerate(gs):
        d0 = K
        for key, bio in zip(['sim', 'bio'], [False, True]):
            log('sampling homologies for g = %.2f (%s data)' % (g, key))
            samples = sample_edit_sequences(K, g, n_samples, bio=bio)
            for sample_idx, opseq in enumerate(samples):
                time_at_d_ = np.zeros(2*K)
                i, j = 0, 0
                print len(opseq), g, 1 - 1. * opseq.count('M') / len(opseq)
                for op in opseq:
                    d = i - j
                    time_at_d_[d + d0] += 1
                    if op in 'DM':
                        i += 1
                    if op in 'IM':
                        j += 1
                cum_time_at_d_ = np.cumsum(time_at_d_)
                for r_idx, r in enumerate(rs):
                    in_band = cum_time_at_d_[d0 + r] - cum_time_at_d_[d0 - r]
                    prop = in_band / K
                    assert prop <= 1
                    sim_data['in_band'][key][g_idx][r_idx][sample_idx] = prop
    return sim_data


def plot_time_in_band(sim_data, cutoff_epsilon, path=None):
    assert path
    gs = sim_data['gs']
    rs = sim_data['rs']
    K = sim_data['K']
    assert sim_data['in_band']['sim'].shape == sim_data['in_band']['bio'].shape
    n_samples = sim_data['in_band']['sim'].shape[2]

    fig = plt.figure(figsize=(10, 7))

    grids = gridspec.GridSpec(2, 2, width_ratios=[1.2, 1])

    ax_mod = fig.add_subplot(grids[:, 0])  # model
    ax_sim = fig.add_subplot(grids[0, 1])  # simulation
    ax_bio = fig.add_subplot(grids[1, 1])  # biological data

    colors = color_code(gs)

    for g_idx, (color, g) in enumerate(zip(colors, gs)):
        vs = [erf(r / (2 * np.sqrt(g * K))) for r in rs]
        r_lim = rs[bisect_left(vs, 1 - .5 * cutoff_epsilon)]
        r_cutoff = rs[bisect_left(vs, 1 - cutoff_epsilon)]
        us = [time_in_band(K, g, r) for r in rs]
        kw = {'color': color, 'lw': 1.5, 'alpha': .8}
        ax_mod.plot(rs, vs, label='$g = %.2f$' % g, **kw)  # simplified model
        ax_mod.plot(rs, us, ls='--', **kw)                 # full correct model
        ax_mod.axvline(r_cutoff, color=color, lw=5, alpha=.3)
        ax_mod.grid(True)
        ax_mod.set_xlabel('Band radius')
        ax_mod.set_ylabel('proportion of time in band')
        ax_mod.legend(loc='lower right', fontsize=12)
        ax_mod.set_xlim(0, r_lim)
        ax_mod.set_ylim(0, 1.2)

        for key, ax in zip(['sim', 'bio'], [ax_sim, ax_bio]):
            res = sim_data['in_band'][key][g_idx, :, :]

            plot_with_sd(ax, rs, res, axis=1, y_max=1, color=color, lw=1.5)
            ax.axvline(r_cutoff, color=color, lw=5, alpha=.3)
            ax.set_xlim(0, r_lim)
            ax.set_ylim(0, 1.2)
            ax.grid(True)
            ax.set_title('%s. data' % key, fontsize=8)

            r_cutoff = rs[bisect_left(vs, 1 - cutoff_epsilon)]
            print 'g = %.2f: effective mean time in band (%s) = %f' % \
                (g, key, sim_data['in_band'][key][g_idx, r_cutoff, :].mean())

    fig.suptitle('$K = %d$, \# samples = $%d$' % (K, n_samples))
    fig.tight_layout(rect=[0, 0.03, 1, 0.95])
    savefig(fig, path, comment='time in band simulation')


def exp_time_in_band():
    K = 1000
    gs = [.05, .15]
    n_samples = 100
    rs = range(0, 400)
    cutoff_epsilon = 1e-6  # for vertical lines showing calculated cutoff

    dumpfile = 'band_radius.txt'
    plot_path = 'band_radius.png'
    sim_data = sim_time_in_band(K, gs, rs, n_samples, dumpfile=dumpfile,
                                ignore_existing=False)
    plot_time_in_band(sim_data, cutoff_epsilon, path=plot_path)


if __name__ == '__main__':
    exp_time_in_band()