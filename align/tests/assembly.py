#!/usr/bin/env python
import sys
import os
import networkx as nx

from .. import pw, tuples, seq, assembly

A = seq.Alphabet('ACGT')

params = {
    'wordlen': 5,           # tuple word lengths
    'genome_length': 1500,  # length of randomly generated genome
    'coverage': 4,          # coverage of random sequencing reads
    'read_len_mean': 300,   # average length of sequencing read
    'read_len_var': 10,     # variance of sequencing read length
    'go_prob': 0.05,        # gap open score
    'ge_prob': 0.3,         # gap extend score
    'subst_probs': [[0.97 if k==i else 0.01 for k in range(4)] for i in range(4)],
    'min_align_score': 120, # minimum overlap alignment score to constitue an edge
    'window': 20,           # rolling window length for tuple extension
    'drop_threshold': 10,   # what constitutes a drop in score of a window
    'max_succ_drops': 3     # how many consecutive drops are allowed
}
subst_scores = pw.AlignParams.subst_scores_from_probs(params['subst_probs'], A)
go_score, ge_score = pw.AlignParams.gap_scores_from_probs(params['go_prob'], params['ge_prob'])
C = pw.AlignParams(
    alphabet=A, subst_scores=subst_scores,
    go_score=go_score, ge_score=ge_score
)

def show_params():
    print 'Substitution probabilities:'
    for i in params['subst_probs']:
        print i
    print 'Substitution scores:'
    for i in subst_scores:
        print [round(f,2) for f in i]
    print 'Pr(go) = %.2f, Pr(ge) = %.2f +----> Score(go)=%.2f, Score(ge)=%.2f' % \
        (params['go_prob'], params['ge_prob'], go_score, ge_score)

    print 'drop_threshold = %.2f, max_succ_drops = %d, window = %d' % \
        (params['drop_threshold'], params['max_succ_drops'], params['window'])

def create_example(db):
    show_params()
    seq.make_sequencing_fixture('genome.fa', 'reads.fa',
        genome_length=params['genome_length'],
        coverage=params['coverage'],
        len_mean=params['read_len_mean'],
        len_var=params['read_len_var'],
        subst_probs=params['subst_probs'],
        ge_prob=params['ge_prob'],
        go_prob=params['go_prob']
    )
    B = tuples.TuplesDB(db, alphabet=A)
    B.initdb()
    B.populate('reads.fa');
    I = tuples.Index(B, wordlen=params['wordlen'])
    I.initdb()
    I.index()

def overlap_by_seed_extension(db, path):
    show_params()
    B = tuples.TuplesDB(db, alphabet=A)
    I = tuples.Index(B, wordlen=params['wordlen'])
    G = assembly.overlap_graph_by_seed_extension(I, C,
        max_succ_drops=params['max_succ_drops'], window=params['window'],
        drop_threshold=params['drop_threshold'])
    G.save(path)
