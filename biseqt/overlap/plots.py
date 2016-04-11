from .discovery import most_signifcant_shift
import os.path
from math import sqrt, ceil
from matplotlib import pyplot as plt
from .. import ProgressIndicator

# FIXME docs
def plot_num_seeds_discrimination(path, index, true_overlaps, num_bins=500):
    plt.clf()
    seqinfo = index.seqdb.seqinfo()
    ids = seqinfo.keys()
    msg = 'Counting the number of seeds for all pairs of sequences'
    indicator = ProgressIndicator(msg, len(ids) * (len(ids)-1) / 2.0)
    indicator.start()
    pos = []
    neg = []
    for S_id_idx in range(len(ids)):
        for T_id_idx in range(S_id_idx+1, len(ids)):
            indicator.progress()
            S_id, T_id = ids[S_id_idx], ids[T_id_idx]
            count = len(index.seeds(S_id, T_id))
            if count == 0:
                continue
            if set([S_id,T_id]) in true_overlaps:
                pos += [count]
            else:
                neg += [count]

    indicator.finish()

    n_neg, bins_neg, hist_neg = plt.hist(neg, num_bins, color='red',
        histtype='step', cumulative=True, normed=True, label='Non-overlapping reads')
    n_pos, bins_pos, hist_pos = plt.hist(pos, num_bins, color='green',
        histtype='step', cumulative=True, normed=True, label='Overlapping reads')
    xmax = max(
        bins_neg[len(filter(lambda x: n_neg[x]<0.999, range(len(bins_neg)-1)))],
        bins_pos[len(filter(lambda x: n_pos[x]<0.999, range(len(bins_pos)-1)))]
    )
    plt.grid(True)
    plt.xlim(-xmax/10, xmax)
    plt.ylim(-0.1, 1.2)
    plt.axvline(x=0, ymin=-0.1, ymax=1.2, color='k')
    plt.axhline(y=0, xmin=-100, xmax=xmax, color='k')
    plt.xticks([i*100 for i in range(int(xmax/100) + 1)], rotation='vertical')
    plt.yticks([i*0.1 for i in range(11)], rotation='vertical')
    plt.tick_params(axis='x', labelsize=8, direction='vertical')
    plt.xlabel('Number of matching %d-mers' % index.wordlen)
    plt.ylabel('Proportion of read-pairs (cumulative)')
    plt.legend(loc='right')
    plt.savefig(path)

# FIXME docs
def plot_seed_extension_rws(path, seqinfo, max_rws=225, draw_type='-+',
    logfile='scores.txt', true_shifts={}):

    with open(logfile) as f:
        data = [l.strip().split() for l in f.readlines() if l.strip()[-1] in draw_type]

    data = data[:max_rws]
    data = [[d[0], eval(d[1]), d[2]] for d in data]
    indicator = ProgressIndicator('plotting score random walks', len(data))
    indicator.start()
    dim = ceil(sqrt(len(data)))

    plt.clf()
    fig = plt.figure(figsize=(5*dim,5*dim))
    for idx, datum in enumerate(data):
        indicator.progress()
        S_tok, T_tok = datum[0][1:-1].split(',')
        S_id, S_idx = [int(i) for i in S_tok.split(':')]
        T_id, T_idx = [int(i) for i in T_tok.split(':')]
        S_start, T_start = seqinfo[S_id]['start'], seqinfo[T_id]['start']
        ax = fig.add_subplot(dim, dim, idx+1)
        ax.set_title('Sequences %d vs %d' % (S_id, T_id))
        if true_overlaps:
            edge = tuple(sorted((S_id, T_id)))
            if edge in true_shifts:
                color = 'green'
                ax.set_title(ax.get_title() +
                    ' (true shift = %d)' % (true_shifts[edge]))
            else:
                color = 'red'
        else:
            color = 'k'

        xs = [x*50 for x in range(len(datum[1]))]
        label = ' '.join([str(S_idx - T_idx), datum[2]])
        ax.plot(xs, datum[1], color=color, label=label)
        ax.legend()

    indicator.finish()
    plt.savefig(path)


# FIXME docs
def plot_shift_signifiance_discrimination(path, index, true_overlaps, num_bins=500):
    seqinfo = index.seqdb.seqinfo()
    ids = seqinfo.keys()
    #ids = ids[:100]
    pos_pvalues = []
    neg_pvalues = []
    msg = 'Finding most significant shift for all pairs of sequences'
    indicator = ProgressIndicator(msg, len(ids) * (len(ids)-1) / 2.0)
    indicator.start()
    for S_id_idx in range(len(ids)):
        for T_id_idx in range(S_id_idx+1, len(ids)):
            S_id, T_id = ids[S_id_idx], ids[T_id_idx]
            if seqinfo[S_id]['name'] == seqinfo[T_id]['name']:
                continue
            indicator.progress()
            S_graph_name = seqinfo[S_id]['name'] + ('-' if seqinfo[S_id]['rc'] else '+')
            T_graph_name = seqinfo[T_id]['name'] + ('-' if seqinfo[T_id]['rc'] else '+')
            _, significance = most_signifcant_shift(S_id, T_id, index)
            #_, significance = index.most_signifcant_shift(S_id, T_id)
            if significance is None:
                continue
            if set([S_graph_name, T_graph_name]) in true_overlaps:
                pos_pvalues += [significance]
            else:
                neg_pvalues += [significance]

    indicator.finish()

    plt.clf()
    # hist returns 3 lists (n, bins, _): n is values at bins, bins is edges.
    n_neg, bins_neg, _ = plt.hist(neg_pvalues, num_bins, color='red',
        histtype='step', cumulative=True, normed=True, label='Non-overlapping reads')
    n_pos, bins_pos, _= plt.hist(pos_pvalues, num_bins, color='green',
        histtype='step', cumulative=True, normed=True, label='Overlapping reads')
    xmax = min(
        bins_neg[len(filter(lambda x: n_neg[x] < 1 - 0.001, range(len(bins_neg)-1)))],
        bins_pos[len(filter(lambda x: n_pos[x] < 1 - 0.001, range(len(bins_pos)-1)))]
    )
    plt.grid(True)
    plt.xlim(-50, xmax)
    ymax = max(max(n_neg), max(n_pos))*1.1
    plt.ylim(ymax*-0.1, ymax)
    plt.axvline(x=0, ymin=plt.ylim()[0], ymax=plt.ylim()[1], color='k')
    plt.axhline(y=0, xmin=plt.xlim()[0], xmax=plt.xlim()[1], color='k')
    x_step = 100
    y_step = 0.05
    plt.xticks([int(plt.xlim()[0]) + i*x_step for i in range(int((plt.xlim()[1]-plt.xlim()[0])/x_step) + 1)], rotation=90)
    plt.yticks([i*y_step for i in range(int(plt.ylim()[1]/y_step))])
    plt.xlabel('largest significance for a shift window on %d-mers' % index.wordlen)
    plt.ylabel('Proportion of read-pairs (cumulative)')
    plt.legend(loc='upper left', fontsize=10)
    plt.tight_layout()
    plt.savefig(path, dpi=300)

def plot_all_seeds(index, rolling_sum_width, basedir='', true_overlaps=[], mappings={}):
    seqinfo = index.seqdb.seqinfo()
    ids = seqinfo.keys()
    indicator = ProgressIndicator('Plotting all seeds',
        len(ids) * (len(ids) - 1) / 2.0, percentage=False)
    indicator.start()
    for S_id_idx in range(len(ids)):
        for T_id_idx in range(S_id_idx+1, len(ids)):
            indicator.progress()
            S_id, T_id = ids[S_id_idx], ids[T_id_idx]
            S_name, T_name = seqinfo[S_id]['name'], seqinfo[T_id]['name']
            S_start = mappings[S_name].ref_from if mappings[S_name].strand == '+' else mappings[S_name].ref_to
            T_start = mappings[T_name].ref_from if mappings[T_name].strand == '+' else mappings[T_name].ref_to
            S_len, T_len = seqinfo[S_id]['length'], seqinfo[T_id]['length']
            seeds = index.seeds(S_id, T_id)
            if not seeds:
                continue
            best_shift, log_pvalue = most_signifcant_shift(S_len, T_len,
                seeds, rolling_sum_width)
            label = 'Most significant shift = %d\nlog(p-value)=%.2f' % (best_shift, log_pvalue)
            overlay = [(best_shift, '#333333', label)]

            path = os.path.join(basedir, '%d_%d' % (S_id, T_id))
            if true_overlaps:
                if set([S_id, T_id]) in true_overlaps:
                    color = 'green'
                    path += '.p.png'
                    true_shift = T_start - S_start
                    overlay += [(true_shift, 'green', 'True shift = %d' % true_shift)]
                else:
                    path += '.n.png'
                    color = 'red'

                plot_seeds(path, seeds, seqinfo, color=color, shift_overlay=overlay)
            else:
                path += '.png'
                plot_seeds(path, seeds, seqinfo, shift_overlay=overlay)

    indicator.finish()

def plot_seeds(path, seeds, seqinfo, color='k', shift_overlay=[]):
    plt.clf()
    plt.gca().set_aspect('equal')
    plt.scatter([x.tx.S_idx for x in seeds], [x.tx.T_idx for x in seeds],
        marker='o', s=5, color=color)
    plt.ylim(-1000)
    plt.xlim(-1000)
    plt.grid(True)

    S_id, T_id = seeds[0].S_id, seeds[0].T_id
    S_name, T_name = seqinfo[S_id]['name'], seqinfo[T_id]['name']
    S_len, T_len = seqinfo[S_id]['length'], seqinfo[T_id]['length']

    for shift, color, label in shift_overlay:
        xrange = (max(0, shift), S_len)
        yrange = (max(0, -shift), S_len - shift)
        plt.plot(xrange, yrange, alpha=0.4, linewidth=5, color=color, label=label)

    plt.title('%s vs. %s\n%d total seeds' % (S_name, T_name, len(seeds)), fontsize=8)
    plt.axvline(x=0, ymin=plt.ylim()[0], ymax=plt.ylim()[1], color='k')
    plt.axhline(y=0, xmin=plt.xlim()[0], xmax=plt.xlim()[1], color='k')

    plt.xlabel('Position in %s' % S_name)
    plt.ylabel('Position in %s' % T_name)
    plt.legend(prop={'size':8})
    plt.ticklabel_format(style='sci', axis='both', scilimits=(0,0))
    plt.savefig(path, dpi=300)
