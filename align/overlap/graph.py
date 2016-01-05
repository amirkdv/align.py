import sys
import igraph
from termcolor import colored


class OverlapGraph(object):
    """Wraps an :class:`igraph.Graph` object with additional methods to build
    and process an overlap graph.

    Attributes:
        iG (igraph.Graph): The graph object.

    Args:
        G (Optional[igraph.Graph]): The graph object to initialize with; no
            processing is done and if the object is ``None`` a new directed
            graph is instantiated.
    """
    def __init__(self, G=None):
        self.iG = G if G else igraph.Graph(directed=True)
        assert(isinstance(self.iG, igraph.Graph))
        self.v_highlight = '#b5ffb5'
        self.e_highlight = '#00b400'

    def _endpoint_names(self, eid):
        """Internal helper: igraph is not too happy when we munge vertex IDs
        since it keeps renumbering them according to its memory allocation
        scheme. Instead convert everything to "name"s which are the original
        sequence IDs.

        See: https://lists.nongnu.org/archive/html/igraph-help/2010-03/msg00078.html
        """
        if isinstance(eid, igraph.Edge):
            eid = eid.index
        uid, vid = self.iG.es[eid].tuple
        return self.iG.vs[uid]['name'], self.iG.vs[vid]['name']

    def _vids_to_names(self, vids):
        return [self.iG.vs[vid]['name'] for vid in vids]

    def eid_to_str(self, eid, maxlen=50):
        """Prepares an edge for pretty printing. Truncates and paths the end
        point labels (``name`` is used as label) to ensure they both have
        length ``maxlen``.
        """
        u, v = self._endpoint_names(eid)
        u, v = u[:maxlen].ljust(maxlen), v[:maxlen].rjust(maxlen)
        w = self.iG.es[eid]['weight']
        w = ('+--[%.2f]-->' % w).ljust(20)
        return '%s %s %s\n' % (u, w, v)

    def break_cycles(self, method='ip'):
        """Removes a
        `feedback arc set <https://en.wikipedia.org/wiki/Feedback_arc_set>`__
        from the graph. Depending on the ``method`` the result may not be
        optimal.

        Keyword Args:
            method (str): The FAS discovery algorithm; passed to
                :func:`igraph.Graph.feedback_arc_set`. Default uses an
                integer programming formulation which is guaranteed to be
                optimal but is slow on large graphs. The alternative is
                ``eades`` which uses a suboptimal `heuristic
                <http://www.sciencedirect.com/science/article/pii/002001909390079O>`__.
        """
        if self.iG.is_dag():
            return
        rm = self.iG.feedback_arc_set(
            weights=self.iG.es['weight'], method=method
        )
        for e in rm:
            sys.stderr.write('removed edge: %s' % self.eid_to_str(e))
        self.iG.delete_edges(rm)

    def longest_path(self, exclude=[], equal_weights=False):
        """Finds the heaviest path (and potantially the longest path in the
        sense of number of edges) of the graph, excluding vertices whose name
        is included in ``exclude``. This, naturally requires that the graph is
        acyclic. Assuming the graph is a DAG, we can find the longest path in
        two steps:

        - Find a topological ordering of the graph in :math:`O(|V|+|E|)` time,
        - Find a heaviest path using the sorting in :math:`O(|V|)` time.

        Keyword Arguments:
            exclude (Optional[List[str]]): A list of vertex names to be
                excluded from the graph when finding the longest path. This is
                only of use to :func:`all_longest_paths`.
            equal_weights (Optional[bool]): If truthy, all edges are considered
                equal in which sense the solution is the literal longest path.

        Returns:
            list[str]: A list of vertex names in order of appearance in the
                longest path.
        """
        def weight_of_edge(u, v):
            if equal_weights:
                return 1
            else:
                return self.iG.es['weight'][self.iG.get_eid(u, v)]

        sorting = self._vids_to_names(self.iG.topological_sorting())
        sorting = [v for v in sorting if v not in exclude]
        # longest paths ending at each vertex keyed by vertex. Each entry is a
        # tuple of (<weight, from>) where `from` is any of the predecessors
        # giving the maximum weight.
        longest_paths = {}
        for v in sorting:
            if v in exclude:
                continue
            incoming = self._vids_to_names(self.iG.predecessors(v))
            incoming = [x for x in incoming if x not in exclude]
            if not incoming:
                longest_paths[v] = (0, None)
            else:
                w = lambda x: longest_paths[x][0] + weight_of_edge(x, v)
                cands = [(w(u), u) for u in incoming]
                longest_paths[v] = sorted(
                    cands, key=lambda x: x[0], reverse=True
                )[0]

        if not longest_paths:
            return []

        # Find the terminal vertex of the longest path:
        end = sorted(
            longest_paths.items(), key=lambda x: x[1][0], reverse=True
        )[0][0]
        path = []
        # Trace back the entire path:
        while end and longest_paths:
            path = [end] + path
            end = longest_paths.pop(end)[1]

        # Don't report trivial paths:
        return path if len(path) > 1 else []

    def all_longest_paths(self, equal_weights=False):
        """Repeatedly finds the longest path in the graph while excluding
        vertices that are already included in a path. See :func:`longest_path`.
        All keyword arguments are passed as-is to :func:`longest_path`.

        Returns:
            List[List[str]]: A list of paths, each a list of vertex names in
                order of appearance in the path.
        """
        paths = []
        exclude = []
        while True:
            path = self.longest_path(exclude=exclude)
            if not path:
                break
            paths += [path]
            exclude += path
        return paths

    def layout(self, full=False, equal_weights=False):
        """Finds the heaviest path (or potentially the longest path) of the
        directed graph and creates a new :class:`OverlapGraph` containing only
        this layout path. Optionally, we can demand that ALL longest paths of
        the graph are reported (to ensure all vertices are included in some
        sub-layout), see :func:`all_longest_paths`.

        Keyword Args:
            full (bool): If truthy, an effort is made to add other paths to
                cover all vertices of the graph.
            equal_weights (Optional[bool]): see :func:`longest_path`.

        Returns:
            overlap.OverlapGraph: A linear subgraph (the heaviest path).

        Raises:
            AssertionError: If the graph is not acyclic.
        """
        assert(self.iG.is_dag())
        if full:
            paths = self.all_longest_paths(equal_weights=equal_weights)
        else:
            paths = [self.longest_path(equal_weights=equal_weights)]
        eids = []
        for path in paths:
            for idx in range(1, len(path)):
                eids += [self.iG.get_eid(path[idx-1], path[idx])]

        return OverlapGraph(self.iG.subgraph_edges(eids))

    # the paths are names not ids
    def draw(self, fname, **kw):
        """Draws the graph and potentially highlights provided paths.

        Keyword Arguments:
            highlight_paths ([List[List[str]]]): A list of paths to be
                highlighted. All edges of the path and the starting vertex
                are highlighted green.
            edge_color ([List|str]): Passed to :func:`igraph.Graph.plot`.
                Default is all black unless paths to be highlighted are
                specified. If provided, overrides path highlighting.
            vertex_color ([List|str]): Passed to :func:`igraph.Graph.plot`.
                Default is all white unless paths to be highlighted are
                specified in which case starting vertices are green.
            edge_width ([List|float]): Passed to :func:`igraph.Graph.plot`.
                Default is 10 for edges in highlighted path and 1 otherwise.
            edge_arrow_widge ([List|float]): Passed to
                :func:`igraph.Graph.plot`. Default is 3 for highlighted edges
                and 1 otherwise.
            edge_curvred (float): Passed to :func:`igraph.Graph.plot`. Default
                is 0.1.
        """
        highlight_paths = kw.get('highlight_paths', [])

        def e_in_path(eid):
            u, v = self._endpoint_names(eid)
            return any([
                u in p and v in p and
                p.index(u) == p.index(v) - 1 for p in highlight_paths
            ])

        v_start_path = lambda v: any([p[0] == v for p in highlight_paths])

        # Sugiyama works on non-DAG graphs as well
        n = len(self.iG.vs)
        layout_kw = {'maxiter': n * 20, 'weights': None}
        if 'weight' in self.iG.es.attributes():
            layout_kw['weights'] = 'weight'
        plot_kw = {
            'layout': self.iG.layout_sugiyama(**layout_kw),
            'bbox': (n*150, n*150),
            'vertex_size': 150,
            'vertex_label': [x.replace(' ', '\n') for x in self.iG.vs['name']],
            'vertex_label_size': 18,
            'vertex_color': kw.get('vertex_color', [self.v_highlight if v_start_path(v) else 'white' for v in self.iG.vs['name']]),
            'edge_width': kw.get('edge_width', [10 if e_in_path(e) else 1 for e in self.iG.es]),
            'edge_arrow_width': kw.get('edge_arrow_width', [3 if e_in_path(e) else 1 for e in self.iG.es]),
            'edge_color': kw.get('edge_color', [self.e_highlight if e_in_path(e) else 'black' for e in self.iG.es]),
            'edge_curved': kw.get('edge_curved', 0.1),
            'margin': 200,
        }
        igraph.plot(self.iG, fname, **plot_kw)

    def diff_text(self, OG, f=sys.stdout, summary_only=True, weights_from='theirs'):
        """Prints a diff-style comparison of our :attr:`iG` against another
        given :class:`OverlapGraph` and writes the output to the given file
        handle. Missing edges are printed in red with a leading '-' and added
        edges are printed in green with a leading '+'.

        Args:
            OG (OverlapGraph): The "to" directed graph ("from" is us).

        Keyword Args:
            f (Optional[file]): Open file handle to which output is written;
                default is ``sys.stdout``.
            summary_only (Optional[bool]): Only show a summary of changes and
                not edge-by-edge diff; default is True.
            weights_from (Optional[str]): Which graph's edge weights should be
                used for common edges, either 'ours' or 'theirs'; default is
                'theirs'.
        """
        sE1 = set([self._endpoint_names(e) for e in self.iG.es])
        sE2 = set([OG._endpoint_names(e) for e in OG.iG.es])
        assert(weights_from in ['ours', 'theirs'])
        def _edge_str(endpoints):
            if endpoints in sE1 and endpoints in sE2:
                if weights_from == 'ours':
                    return self.eid_to_str(self.iG.get_eid(*endpoints))
                else:
                    return OG.eid_to_str(OG.iG.get_eid(*endpoints))
            if endpoints in sE1:
                return self.eid_to_str(self.iG.get_eid(*endpoints))
            elif endpoints in sE2:
                return OG.eid_to_str(OG.iG.get_eid(*endpoints))
            else:
                raise RuntimeError("This should not have happened")
        missing, added, both = sE1 - sE2, sE2 - sE1, sE1.intersection(sE2)
        missing_pctg = len(missing)*100.0/len(sE1)
        added_pctg = len(added)*100.0/len(sE1)
        f.write(
            'G1 (%d edges) --> G2 (%d edges): %%%.2f lost, %%%.2f added\n' %
            (len(sE1), len(sE2), missing_pctg, added_pctg)
        )
        if summary_only:
            return
        diff = [('-', edge) for edge in missing] + \
            [('+', edge) for edge in added] + [(None, edge) for edge in both]
        for edge in sorted(diff, cmp=lambda x, y: cmp(x[1], y[1])):
            color = None
            prefix = ' ' if edge[0] is None else edge[0]
            line = '%s %s' % (prefix, _edge_str(edge[1]))
            if edge[0] == '-':
                color = 'red'
            elif edge[0] == '+':
                color = 'green'

            if color and f.isatty():
                f.write(colored(line, color=color))
            else:
                f.write(line)

    def diff_draw(self, OG, fname, figsize=None):
        """Draws the difference between our :attr:`iG` against another
        given :class:`OverlapGraph`. Shared edges are in black, missing edges
        (from ours to ``OG``) are in red and added edges are in green.

        Args:
            OG (OverlapGraph): The "to" directed graph ("from" is us).
            fname (string): Path to which plot is saved, passed as is to
                :func:`draw`.
        """
        e_to_names = lambda G, e: (G.vs[e[0]]['name'], G.vs[e[1]]['name'])
        sE1 = set([self._endpoint_names(e) for e in self.iG.es])
        sE2 = set([OG._endpoint_names(e) for e in OG.iG.es])
        G = OverlapGraph()
        G.iG.add_vertices(list(
            set(self.iG.vs['name']).union(set(OG.iG.vs['name']))
        ))
        G.iG.add_edges(list(sE1.union(sE2)))
        both, missing, added = sE1.intersection(sE2), sE1 - sE2, sE2 - sE1
        edge_color = []
        for e in G.iG.es:
            e = G._endpoint_names(e)
            if e in both:
                edge_color += ['black']
            elif e in missing:
                edge_color += ['red']
            elif e in added:
                edge_color += ['green']

        vertex_color = ['white' if v.degree(mode=igraph.IN) else self.v_highlight for v in G.iG.vs]

        G.draw(fname, edge_color=edge_color, vertex_color=vertex_color,
               edge_width=5, edge_arrow_width=3, edge_curved=0.01)

    def save(self, fname):
        """Saves the graph in GML format

        Args:
            fname (str): path to GML file.
        """
        self.iG.write_gml(fname)