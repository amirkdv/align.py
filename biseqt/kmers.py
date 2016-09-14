# -*- coding: utf-8 -*-
"""
.. wikisection:: overview
    :title: Kmers

    The :mod:`biseqt.kmers` module provides tools for k-mer analysis.

    >>> from biseqt.database import DB
    >>> from biseqt.sequence import Alphabet
    >>> from biseqt.kmers import KmerIndex
    >>> A = Alphabet('ACGT')
    >>> db = DB('example.db', A)
    >>> kmer_index = KmerIndex(db)
    >>> db.initialize()
    >>> with open('example.fa') as f:
    ...     db.load_fasta(f)
    >>> kmer_index.kmers()  # yields (kmer, hits)
    >>> kmer_index.score_kmers()  # repetitive kmers get higher scores
    >>> kmer_index.kmers(max_score=10)  # exclude high scoring kmers
"""

from math import log
import struct

from .database import DB
from .stochastics import binomial_to_normal, normal_neg_log_pvalue


class KmerIndex(object):
    """An index for kmers, their occurences in a body of sequences, and
    :class:`seeds <Seed>`.

    Attributes:
        db (database.DB): The sequence :class:`database <biseqt.database.DB>`.
        wordlen (int): Length of kmers of interest to this index.
        hits_table (str): ``kmers_N_hits`` contains occurences of each kmer
            where ``N`` is :attr:`wordlen`.
        scores_table (str): ``kmers_N_scores`` contains scores of each kmer
            (``N`` is :attr:`wordlen`).
        status_table (str): ``kmers_N_indexed`` contains metadata about scanned
            sequences (``N`` is :attr:`wordlen`).
    """
    def __init__(self, db, wordlen):
        assert isinstance(db, DB)
        self.db = db
        self.wordlen = wordlen

        self.kmers_table = 'kmers_%d' % self.wordlen
        self.status_table = 'kmers_%d_indexed' % self.wordlen

        db.add_event_listener('db-initialized', self.initialize)
        db.add_event_listener('sequence-inserted', self.store_kmers)

        self._digits = '0123456789abcdefghijklmnopqrstuvwxyz'
        assert len(self.db.alphabet) <= len(self._digits), \
            'Maximum alphabet size of %d exceeded' % len(self._digits)

        int_size = 8 * struct.calcsize('P')
        assert self.wordlen < (int_size - 1)/2., \
            'Maximum kmer length %d for %d-bit integers exceeded' % \
            (self.wordlen, int_size)

    _init_script = """
    -- Kmer index initialization script
        CREATE TABLE IF NOT EXISTS %s (
          'seq'   INTEGER,
          'kmers' VARCHAR
        );
        CREATE TABLE IF NOT EXISTS %s ( -- status table
          'id'     INTEGER REFERENCES sequence(id),
                                        -- the id of an indexed sequence
          'length' INTEGER              -- the length of the sequence
        );
    """

    def initialize(self, conn):
        """Event handler for "db-initialized" (cf. :attr:`DB.events
        <biseqt.database.DB.events>`). Creates three tables:

        * :attr:`hits_table`,
        * :attr:`scores_table`,
        * :attr:`status_table`.

        Args:
            conn (sqlite3.Connection): An open connection to operate on.
        """
        conn.cursor().execute(self._init_script % (self.kmers_table, self.status_table))

    # put the initialization script in the docs
    initialize.__doc__ += '\n\n\t.. code-block:: sql\n\t%s\n' % \
                          '\n\t'.join(_init_script.split('\n'))

    def log(self, *args, **kwargs):
        """Wraps :func:`log <biseqt.database.DB.log>` of :attr:`db`."""
        self.db.log(*args, **kwargs)

    def kmer_as_int(self, contents):
        """Calculates the integer representation of a kmer by treating its
        contents as digits in the base of alphabet length. For instance, in the
        DNA alphabet ``AGA`` becomes :math:`(020)_4` which is 8. Note that
        each kmer gives a unique integer as long as all kmers have the same
        word length (which is the case here). There are two restrictions
        imposed on the word length and alphabet size (enforced in
        :func:`__init__`):

        * The alphabet must be such that all letters can be represented by
          single ASCII characters between ``[0-9a-z]`` (cf. int_). This
          implies a maximum alphabet size of 36.
        * The word length must be such that a single integer can store the
          entire representation of a kmer. This requires that we have:

          .. math::
            k < \\frac{I-1}{2}

          where :math:`k` is the word length and :math:`I` is the number of
          bits allocated for an integer. For instance, on a 64-bit system the
          maximum word length is 31.

        .. _int: https://docs.python.org/2/library/functions.html#int

        .. wikisection:: dev
            :title: Integer Sizes

            All kmers are stored as their integer representation to save on
            space and processing time. Python_ is flexible with the maximum
            size of integers, as integers automatically switch to longs, which
            have "unlimited precision". SQLite_, too, is flexible but has a
            maximum integer cap of 64-bits: integers take 2, 4, 6, or 8 bytes
            per integer dependning on the size it needs.

            The checks resulting from maximum integer size are performed in
            :func:`KmerIndex.__init__ <KmerIndex>` which basically block kmers
            taking more than 64-bit integers to represent.

            .. _python: https://docs.python.org/2/library/stdtypes.html\
                        #numeric-types-int-float-long-complex
            .. _sqlite: https://www.sqlite.org/datatype3.html#section_2
        """
        # document dependence on word length
        as_str = ''.join(self._digits[c] for c in contents)
        return int(as_str, len(self.db.alphabet))

    def as_kmer_sequence(self, seq):
        """A generator for kmer hit tuples of the form ``(kmer, pos)``. Kmers
        are represented in integer form (cf. :func:`kmer_as_int`).

        Args:
            seq (sequence.Sequence): The sequence to be scanned.

        Yields:
            tuple: a kmer and its starting position in ``seq``.
        """
        kmers = []
        for pos in range(len(seq) - self.wordlen + 1):
            kmers.append(self.kmer_as_int(seq.contents[pos: pos + self.wordlen]))
        return kmers

    def store_kmers(self, conn, seq, rec):
        """Event handler for "sequence-inserted" (cf. :attr:`database.events
        <biseqt.database.events>`). Indexes all kmers observed in the given
        sequence in :attr:`hits_table`.

        Args:
            conn (sqlite3.Connection): SQLite connection to operate on.
            seq (sequence.Sequence): The sequence just inserted into the
                database.
            rec (database.Record): The record object corresponding to the
                insertion of ``seq`` with the :attr:`id
                <biseqt.database.Record.id>` field populated.
        """
        cursor = conn.cursor()
        q = 'SELECT * FROM %s WHERE id = ?' % self.status_table
        cursor.execute(q, (rec.id,))
        if sum(1 for _ in cursor) > 0:
            return

        cursor.execute(
            'INSERT INTO %s (seq, kmers) VALUES (?, ?)' % self.kmers_table,
            (rec.id, repr(self.as_kmer_sequence(seq)))
        )
        cursor.execute(
            'INSERT INTO %s (id, length) VALUES (?, ?)' % self.status_table,
            (rec.id, len(seq))
        )

    def total_length_indexed(self):
        """The total number of letters, among all sequences, indexed so far.

        Returns:
            int
        """
        with self.db.connection() as conn:
            cursor = conn.cursor()
            q = 'SELECT SUM(length) FROM kmers_%d_indexed' % self.wordlen
            cursor.execute(q)
            return int(cursor.next()[0])

    def num_kmers(self):
        """The total number of kmers, among all sequences, observed so far.

        Returns:
            int
        """
        with self.db.connection() as conn:
            q = 'SELECT COUNT(DISTINCT kmer) FROM %s' % self.hits_table
            return conn.cursor().execute(q).next()[0]

    def score_kmers(self, only_missing=True):
        """Calculates the negative log p-value for the number of occurences of
        each kmer under the null hypothesis of a binomial distribution. The
        binomial distribution is approximated by a normal distribution for
        numeric stability (cf. :func:`binomial_to_normal()
        <biseqt.stochastics.binomial_to_normal>`) and then a Bonferroni
        correction for the total number of kmers (cf.  :func:`num_kmers`) is
        applied to the raw negative log p-value given by
        :func:`normal_neg_log_pvalue
        <biseqt.stochastics.normal_neg_log_pvalue`. The higher the score of a
        kmer, the more likely it is that it belongs to a repeat structure.

        Keyword Args:
            only_missing (bool): Whether to re-score all kmers or only those
                with a ``NULL`` score; default is True.
        """
        self.log('Scoring all observed kmers by repetition.')
        N = self.num_kmers()
        L = self.total_length_indexed()
        kmer_probability = 1./(len(self.db.alphabet) ** self.wordlen)
        mu, sd = binomial_to_normal(L, kmer_probability)

        def score_calculator(num_occurrences):
            # Bonferroni correction:
            return - log(N) + normal_neg_log_pvalue(mu, sd, num_occurrences)

        if only_missing:
            self._update_score_table()
            select = """
                SELECT hits.kmer, COUNT(*) FROM %s AS hits
                INNER JOIN %s AS scores ON scores.kmer = hits.kmer
                WHERE score is NULL
                GROUP BY hits.kmer
            """ % (self.hits_table, self.scores_table)
        else:
            select = """
                SELECT kmer, COUNT(*) FROM %s GROUP BY kmer
            """ % self.hits_table
        update = 'UPDATE %s SET score = ? WHERE kmer = ?' % self.scores_table

        self.create_sql_index()
        with self.db.connection() as conn:
            select_cursor, insert_cursor = conn.cursor(), conn.cursor()
            select_cursor.execute(select)
            for kmer, count in select_cursor:
                score = score_calculator(count)
                insert_cursor.execute(update, (score, kmer))

    # FIXME is there a point to this anymore?
    def scanned_sequences(self, ids=None):
        """Yields the ids and lengths of all scanned sequences from the
        ``kmer_indexed_N`` table.

        Yields:
            tuple:
                The sequence integer identifier and the length of the sequence.
        """
        query = 'SELECT id, length FROM %s' % self.status_table
        if ids is not None:
            query += ' WHERE id IN (%s)' % ', '.join('?' for _ in ids)
        else:
            ids = tuple()
        with self.db.connection(reset=True) as conn: # FIXME parallelism hack
            cursor = conn.cursor()
            cursor.execute(query, ids)
            for _id, _len in cursor:
                yield _id, _len

    def create_sql_index(self):
        """Creates SQL indices over :attr:`hits_table`."""
        self.log('Creating SQL indices for %s.' % self.hits_table)
        with self.db.connection() as conn:
            conn.cursor().execute("""
                CREATE INDEX IF NOT EXISTS %s_kmer ON %s (kmer);
                CREATE INDEX IF NOT EXISTS %s_seq ON %s (seq);
            """ % ((self.hits_table,) * 4))

    def drop_sql_index(self):
        """Drops SQL indices created by :func:`create_sql_index`."""
        self.log('Dropping SQL indices for %s.' % self.hits_table)
        with self.db.connection() as conn:
            conn.cursor().execute("""
                DROP INDEX IF EXISTS %s_kmer;
                DROP INDEX IF EXISTS %s_seq;
            """ % ((self.hits_table,) * 2))

    def hits(self, kmer):
        """Returns all hits of a given kmer, represented as an integer or a
        tuple of sequence :attr:`contents <biseqt.sequence.Sequence.contents>`.

        Args:
            kmer (int|tuple): The kmer of interest.

        Returns:
            list:
                A list of 2-tuples containing sequence ids (as in the
                ``sequence`` table) and positions.
        """
        if isinstance(kmer, tuple):
            kmer = self.kmer_as_int(kmer)
        query = 'SELECT seq, pos FROM %s WHERE kmer = ?' % self.hits_table
        with self.db.connection() as conn:
            return list(conn.cursor().execute(query, (kmer,)))

    def _update_score_table(self):
        with self.db.connection() as conn:
            conn.cursor().execute("""
                INSERT OR IGNORE INTO %s (kmer)
                SELECT DISTINCT kmer FROM %s
            """ % (self.scores_table, self.hits_table))

    def kmers(self, ids):
        """Lazy-loads the observed kmers, their occurences, and their score.

        Keyword Args:
            max_score (float): The maximum score (which is negative log
                p-value) for kmers to be included (cf.  :func:`score_kmers`).
                Default is None in which case all kmers are included.

        Yields:
            tuple:
                The kmer in integer representation, a list of occurences where
                each occurence is a tuple of sequence id and position, and
                the score for the kmer.
        """
        with self.db.connection(reset=True) as conn: # FIXME parallel hack
            cursor = conn.cursor()
            q = 'SELECT seq, kmers FROM %s WHERE seq IN (%s)' % \
                (self.kmers_table, ', '.join('?' for _ in ids))
            cursor.execute(q, ids)
            for seqid, kmers in cursor:
                yield seqid, eval(kmers)
