"""Minipipe has two APIs PipeLine and PipeSystem. PipeLine is for sequential pipelines while
PipeSystem can be used in any topology."""

from minipipe.pipes import Source
from minipipe.base import Logger, Stream
from multiprocessing import Process, Event
from collections import Counter
from graphviz import Digraph
from copy import copy

class PipeSystem(object):

    """
        PipeSystem connects Pipes and creates process pool. Pipes are run and closed with a built PipeSystem.

        Toy example:

        .. code-block:: python

            # Define functors
            def genRand(n=10):
                for _ in range(n):
                    yield np.random.rand(10)

            def batch(batch_size=2):
                x = (yield)
                for i in range(len(x)//batch_size):
                    yield x[i*batch_size:(i+1)*batch_size]

            def sumBatch(x):
                return x.sum()

            def split(x):
                return [x, None] if x > 1 else [None, x]

            def output_gt_1(x):
                print '1 <',x

            def output_lt_1(x):
                print '1 >',x

            # Define streams
            s1, s2, s3, s4, s5 = Stream(), Stream(), Stream(), Stream(), Stream()

            # Create Pipe segments with up/downstreams
            # Order is not important
            pipes = [
                Pipe(genRand, 'source1', downstreams=[s1], func_type='generator'),
                Pipe(genRand, 'source2', downstreams=[s1], func_type='generator'),
                Pipe(batch, 'batcher', upstreams=[s1], downstreams=[s2], func_type='coroutine'),
                Pipe(sumBatch, 'sum', upstreams=[s2], downstreams=[s3]),
                Pipe(sumBatch, 'sum', upstreams=[s2], downstreams=[s3]),
                Pipe(sumBatch, 'sum', upstreams=[s2], downstreams=[s3]),
                Pipe(split, 'split', upstreams=[s2], downstreams=[s4, s5]),
                Pipe(output_gt_1, 'print_gt_1', upstreams=[s4]),
                Pipe(output_lt_1, 'print_lt_1', upstreams=[s5]),
            ]

            # Build pipesystem
            psys = PipeSystem(pipes)
            psys.build()

            # Run pipesystem
            psys.run()
            psys.close()

    """

    def __init__(self, pipes):
        self.pipes = pipes
        self.streams = None
        self.processes = None
        self.built = False

    def build(self, log_lvl='INFO', monitor=False, ignore_exceptions=None):
        """Connects pipe segments together and builds graph."""

        self.log_lvl = log_lvl
        self.monitor = monitor
        self.ignore_exceptions = ignore_exceptions
        self.logger = Logger(log_lvl)
        self.global_term = Event()

        # Handle name collisions
        pnames = Counter([p.name for p in self.pipes])
        for pname, cnt in pnames.items():
            if cnt > 1:
                p_with_collisions = filter(lambda x: x.name==pname, self.pipes)
                for i, p in enumerate(p_with_collisions):
                    p.name += '_{}'.format(i)

        # Connect graph and set global term flag
        for p in self.pipes:
            if self.ignore_exceptions is not None:
                p.ignore_exceptions = self.ignore_exceptions
            p.set_global_term_flag(self.global_term)
            #self._connect_upstreams(p)
            #self._connect_downstreams(p)
            self._connect_streams(p)

        # For each pipe count all upstreams and downstreams.
        # Counts are used to determine the number of sentinels a pipe should receive before terminating.
        for p in self.pipes:
            self._count_relatives(p)

        # Create process pool
        self.processes = [Process(target=p.run_pipe, args=[p.name], name=p.name)
                          for p in self.pipes]

        # Add logger to each pipe
        for p in self.pipes:
            p.set_logger(self.logger)
            for s in p.downstreams + p.upstreams:
                if (s.monitor or self.monitor) and s.logger is None:
                    s.set_logger(self.logger)

        self.built = True

    def run(self):
        """Runs pipeline."""
        if self.processes is None:
            self.build()
        for proc in self.processes:
            proc.start()

    def close(self):
        """Joins pipeline."""
        for proc in self.processes:
            proc.join()

    def reset(self):
        """Resets pipeline."""
        self.global_term.clear()
        for p in self.pipes:
            p.reset()
            p.set_logger(self.logger)

        # Create new processes since they can only be started once
        self.processes = [Process(target=p.run_pipe, args=[p.name], name=p.name)
                          for p in self.pipes]

    #def _connect_downstreams(self, p):
    #    for stream in p.get_downstreams():
    #        stream.add_pipe_out(p)
            #for p_in in stream.pipes_in:
            #    p_in._n_ances += 1

    #def _connect_upstreams(self, p):
    #    for stream in p.get_upstreams():
    #        stream.add_pipe_in(p)
            #for p_out in stream.pipes_out:
            #    p_out._n_desc += 1

    def _connect_streams(self, p):
        for stream in p.get_downstreams():
            stream.add_pipe_out(p)
        for stream in p.get_upstreams():
            stream.add_pipe_in(p)

    def _count_relatives(self, p):
        for stream in p.get_downstreams():
            for p_in in stream.pipes_in:
                p_in._n_ances += 1
        for stream in p.get_upstreams():
            for p_out in stream.pipes_out:
                p_out._n_desc += 1


    def diagram(self, draw_streams=False):
        """Draws a graph diagram of pipeline."""

        assert(self.built==True), "ERROR: PipeSystem must be built first"
        g = Digraph()
        edges = set()

        # Assumes graph is a DAG thus iterate over downstreams only
        # There can only be one edge between nodes
        for p in self.pipes:
            g.node(p._id(), p.name)
            for s in p.get_downstreams():
                if draw_streams:
                    g.node(s._id(), s.name, shape='rectangle')
                    edge = (p._id(), s._id())
                    if edge not in edges:
                        edges.add(edge)
                        g.edge(*edge)
                for p_in in s.pipes_in:
                    g.node(p_in._id(), p_in.name)
                    if draw_streams:
                        edge = (s._id(), p_in._id())
                    else:
                        edge = (p._id(), p_in._id())
                    if edge not in edges:
                        edges.add(edge)
                        g.edge(*edge)
        return g


class PipeLine(PipeSystem):

    """
        A simplified API for linear PipeSytems.

        Toy example:

        .. code-block:: python

            # Define functors
            def genRand(n=10):
                for _ in range(n):
                    yield np.random.rand(10)

            def batch(batch_size=2):
                x = (yield)
                for i in range(len(x)//batch_size):
                    yield x[i*batch_size:(i+1)*batch_size]

            def sumBatch(x):
                return x.sum()

            def print_out(x):
                print (x)

            # Define pipeline
            pline = PipeLine()
            pline.add(Pipe(genRand, 'source1', func_type='generator'))
            pline.add(Pipe(batch, 'batcher', func_type='coroutine'), buffer_size = 10)
            pline.add(Pipe(sumBatch, 'sum'), n_processes = 3)
            pline.add(Pipe(print_out, 'print'))

            # Build pipeline
            pline.build()

            # Run pipeline
            pline.run()
            pline.close()

    """

    def __init__(self, monitor=False):
        self.monitor = monitor
        self.segments = []
        self.pipes = []
        self.sid = 0
        super(PipeLine, self).__init__(self.pipes)

    def add(self, pipe, n_processes=1, buffer_size=3):
        """Adds a pipe segment to the pipeline.

           :param pipe: Pipe segment to add to PipeLine
           :param n_processes: Number of processes (workers) to assign to pipe segment
           :param buffer_size: Size of Stream buffer
           :return: None
        """
        # Python generators cannot be split
        assert not (isinstance(pipe, Source) and n_processes > 1), 'Use PipeSystem API for multiple Sources'

        # After the Source connect each segment with a Stream
        if len(self.segments) > 0:
            s = Stream(buffer_size=buffer_size,
                       name = 'stream_{}'.format(self.sid),
                       monitor=self.monitor)
            self.sid += 1
            for seg in self.segments[-1]:
                seg.set_downstreams([s])
            pipe.set_upstreams([s])

        # Create a copy of the pipe segment for each process
        seg = [copy(pipe) for _ in range(n_processes)]

        self.pipes += seg
        self.segments.append(seg)