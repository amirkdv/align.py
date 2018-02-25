# -*- coding: utf-8 -*-
# FIXME docs
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

import struct
import os
import apsw
import logging

from .util import Logger
from .sequence import Alphabet, Sequence

# FIXME docs
DIGITS = '0123456789abcdefghijklmnopqrstuvwxyz'


# FIXME update docs
def kmer_as_int(contents, alphabet):
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
    assert isinstance(alphabet, Alphabet)
    # TODO document dependence on word length
    as_str = ''.join(DIGITS[c] for c in contents)
    return int(as_str, len(alphabet))


def as_kmer_seq(seq, wordlen):
    """A generator for kmer hit tuples of the form ``(kmer, pos)``. Kmers
    are represented in integer form (cf. :func:`kmer_as_int`).

    Args:
        seq (sequence.Sequence): The sequence to be scanned.

    Returns:
        list: of integers representing kmers.
    """
    assert isinstance(seq, Sequence)
    kmers = []
    for pos in range(len(seq) - wordlen + 1):
        kmer = kmer_as_int(seq.contents[pos: pos + wordlen], seq.alphabet)
        kmers.append(kmer)
    return kmers


class KmerDBWrapper(object):
    """Generic wrapper for an SQLite database for Kmers.

    Attributes:
        name (str): String name used as a suffix for table names.
        path (str): Path to the SQLite datbase (or ``:memory:``).
        alphabet (sequence.Alphabet): The alphabet for sequences in the database.
        wordlen (int): Length of kmers of interest to this index.
        init_script (str): SQL script to be executed upon initialization;
            typically creates tables needed by the class.
    """
    def __init__(self, name='', path=':memory:', alphabet=None, wordlen=None,
                 log_level=logging.INFO, init_script=None):
        self.name = name
        assert isinstance(wordlen, int)
        assert isinstance(alphabet, Alphabet)
        assert len(alphabet) <= len(DIGITS), \
            'Maximum alphabet size of %d exceeded' % len(DIGITS)
        self.alphabet = alphabet
        int_size = 8 * struct.calcsize('P')
        assert wordlen < (int_size - 1)/2., \
            'Maximum kmer length %d for %d-bit integers exceeded' % \
            (wordlen, int_size)
        self.wordlen = wordlen

        if path == ':memory:':
            self.path = path
            relpath = path
        else:
            self.path = os.path.abspath(path)
            assert os.path.exists(self.path) or \
                os.access(os.path.dirname(self.path), os.W_OK), \
                'Database %s is not writable' % self.path
            relpath = os.path.relpath(self.path, os.getcwd())

        log_header = '%d-mer cache (%s)' % (self.wordlen, relpath)
        self._logger = Logger(log_level=log_level, header=log_header)
        self.log_level = log_level
        self._connection = None

        self.init_script = init_script
        if self.init_script:
            with self.connection() as conn:
                conn.cursor().execute(self.init_script)

    # FIXME compare with old-tip and figure out what the deal with resetting is
    def connection(self, reset=False):
        """Provides a SQLite database connection that can be used as a context
        manager. The returned object is always the same connection object
        belonging to the :class:`KmerIndex` instance (otherwise in-memory
        connections would reset the database contents upon every invocation).

        Returns:
            apsw.Connection
        """
        if reset or self._connection is None:
            self._connection = apsw.Connection(self.path)
        return self._connection

    def log(self, *args, **kwargs):
        """Wraps :class:`Logger.log`."""
        self._logger.log(*args, **kwargs)


class KmerCache(KmerDBWrapper):
    """A cache backed by SQLite for representations of sequences as integer
    sequences. Upon initialization the following SQL script is executed

    .. code-block:: sql

        CREATE TABLE seq_kmers (
            'seq' VARCHAR,   -- content identifier of sequence
            'kmres' VARCHAR, -- comma separated representation of sequence
                             -- as integers encoding kmers.
        );

    This implies that any time only one ``KmerCache`` can exist with the same
    path.
    FIXME: using the same database for different word lengths / alphabets is
    quietly accepted (and wrong results returned).
    """
    def __init__(self, name='', **kw):
        self.name = name
        init_script = """
            CREATE TABLE IF NOT EXISTS %s (
                'seq' VARCHAR,   -- content identifier of sequence
                'kmers' VARCHAR  -- comma separated representation of sequence
                                 -- as integers encoding kmers.
            );
        """ % self.kmers_table
        kw['name'] = name
        super(KmerCache, self).__init__(init_script=init_script, **kw)

    @property
    def kmers_table(self):
        """The kmer hits table name ``seq_kmers_[name]``, cf.
        :attr:`KmerDBWrapper.name`."""
        return 'seq_kmers_%s' % self.name

    def cached_seqs(self):
        """Returns content identifiers for all cached sequences."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT seq from %s' % self.kmers_table)
            return [x[0] for x in cursor]

    def as_kmer_seq(self, seq):
        """Return the integer representation of a given sequence.

        Args:
            seq (sequence.Sequence): input sequence.

        Returns:
            list: list of integers of length ``n-w+1`` containing kmers in
                input sequence represented as an integer, cf.
                :func:`as_kmer_seq`.
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT kmers from %s WHERE seq = ?' % self.kmers_table,
                (seq.content_id,)
            )
            for kmer_seq in cursor:
                return eval(kmer_seq[0])
        # cache miss, translate to kmer sequence
        self.log('producing kmer representation for sequence %s' %
                 seq.content_id[:8])
        kmer_seq = as_kmer_seq(seq, self.wordlen)
        with self.connection() as conn:
            q = 'INSERT INTO %s (seq, kmers) VALUES (?, ?)' % self.kmers_table
            conn.cursor().execute(q, (seq.content_id, repr(kmer_seq)))
        return kmer_seq


class KmerIndex(KmerDBWrapper):
    """An index backed by SQLite for occurences of kmers in a body of
    sequences. Upon initialization the following script is executated:

    .. code-block:: sql

        CREATE TABLE kmers_[name] (
          'kmer'  INTEGER,      -- The kmer in integer representation.
          'seq'   INTEGER,      -- integer identifier of sequence
          'pos'   INTEGER       -- the position of kmer in sequence.
        );

        CREATE TABLE IF NOT EXISTS kmer_indexed_[name] (
          'seq'  VARCHAR,                           -- content id,
          'seqid' INTEGER PRIMARY KEY AUTOINCREMENT -- integer id.
        );

    Attributes:
        name (str):
        cache (KmerCache): optional :class:`KmerCache` object to use for
            retrieving integer representations of sequences.
    """
    def __init__(self, name='', kmer_cache=None, **kw):
        self.name = name
        init_script = """
            CREATE TABLE IF NOT EXISTS %s (
              'kmer'  INTEGER,      -- the kmer in integer representation.
              'seqid' INTEGER,      -- integer identifier of sequence
                                    -- REFERENCES kmer_indexed(seqid), but not
                                    -- declared to avoid integrity checks
              'pos'   INTEGER       -- the position of kmer in sequence.
            );

            CREATE TABLE IF NOT EXISTS %s (
              'seq'  VARCHAR,                           -- content id,
              'seqid' INTEGER PRIMARY KEY AUTOINCREMENT -- integer id.
            );
        """ % (self.kmers_table, self.log_table)
        kw['name'] = name
        super(KmerIndex, self).__init__(init_script=init_script, **kw)
        if kmer_cache:
            assert isinstance(kmer_cache, KmerCache)
            assert kmer_cache.wordlen == self.wordlen
            assert kmer_cache.alphabet == self.alphabet
            self.kmer_cache = kmer_cache
        else:
            self.kmer_cache = None

    @property
    def kmers_table(self):
        """The kmer hits table name ``kmers_[name]``, cf.
        :attr:`KmerDBWrapper.name`."""
        return 'kmers_' + self.name

    @property
    def log_table(self):
        """The log table name ``kmer_indexed_[name]``, cf.
        :attr:`KmerDBWrapper.name`."""
        return 'kmer_indexed_' + self.name

    def index_kmers(self, seq):
        """ Indexes all kmers observed in the given sequence in
        :attr:`kmers_table`.

        Args:
            seq (sequence.Sequence): The sequence just inserted into the
                database.
            seqid (int): The integer identifier to use for sequence.
        """
        if self.kmer_cache:
            kmer_seq = self.kmer_cache.as_kmer_seq(seq)
        else:
            kmer_seq = as_kmer_seq(seq, self.wordlen)

        with self.connection() as conn:
            self.log('indexing kmers for sequence %s' % seq.content_id[:8])
            cursor = conn.cursor()
            q = 'SELECT seqid FROM %s WHERE seq = ?' % self.log_table
            for seqid in cursor.execute(q, (seq.content_id,)):
                self.log('sequence %s already indexed, skipping.' %
                         seq.content_id[:8])
                return seqid[0]
            q = """
                INSERT INTO %s (seq) VALUES (?);
                SELECT last_insert_rowid();
            """ % self.log_table
            seqid = cursor.execute(q, (seq.content_id,)).next()[0]
            q = """
                INSERT INTO %s (kmer, seqid, pos)
                VALUES (?,?,?)
            """ % self.kmers_table
            cursor.executemany(q, ((kmer, seqid, pos)
                                   for pos, kmer in enumerate(kmer_seq)))
            return seqid

    def create_sql_index(self):
        """Creates SQL index over the ``kmer`` column of ``kmers`` table."""
        self.log('Creating SQL index for table %s.' % self.kmers_table)
        with self.connection() as conn:
            q = """
                CREATE INDEX IF NOT EXISTS idx_%s ON %s (kmer);
            """ % (self.kmers_table, self.kmers_table)
            conn.cursor().execute(q)

    def hits(self, kmer):
        """Returns all hits of a given kmer in indexed sequences.

        Args:
            kmer (int): kmer of interest.

        Returns:
            list:
                A list of 2-tuples containing sequence ids (int) and positions.
        """
        assert isinstance(kmer, int)
        query = 'SELECT seqid, pos FROM %s WHERE kmer = ?' % self.kmers_table
        with self.connection() as conn:
            return list(conn.cursor().execute(query, (kmer,)))

    def kmers(self):
        """Returns all observed kmers.

        Returns:
            list: list of kmers in integer representation.
        """
        self.create_sql_index()  # FIXME do we need this?
        query = 'SELECT DISTINCT kmer FROM %s' % self.kmers_table
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            return [x[0] for x in cursor]

    def drop_data(self):
        """Drop all tables created by this object."""
        with self.connection() as conn:
            conn.cursor().execute('DROP TABLE %s; DROP TABLE %s;' %
                                  (self.kmers_table, self.logs_table))
