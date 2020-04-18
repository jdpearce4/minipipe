"""Minipipe has two APIs PipeLine and PipeSystem. PipeLine is for sequential pipelines while
PipeSystem can be used in any topology."""

from minipipe.pipes import Source, Sink
from minipipe.base import Logger, Stream
from multiprocessing import Process, Event, Queue
from queue import Empty
from subprocess import Popen, PIPE
from collections import Counter
from graphviz import Digraph
from copy import copy
from time import time

class Pipeline(object):

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
                Source(genRand, 'source1', downstreams=[s1]),
                Source(genRand, 'source2', downstreams=[s1]),
                Regulator(batch, 'batcher', upstreams=[s1], downstreams=[s2]),
                Transform(sumBatch, 'sum', upstreams=[s2], downstreams=[s3]),
                Transform(sumBatch, 'sum', upstreams=[s2], downstreams=[s3]),
                Transform(sumBatch, 'sum', upstreams=[s2], downstreams=[s3]),
                Transform(split, 'split', upstreams=[s2], downstreams=[s4, s5]),
                Sink(output_gt_1, 'print_gt_1', upstreams=[s4]),
                Sink(output_lt_1, 'print_lt_1', upstreams=[s5]),
            ]

            # Build pipesystem
            psys = PipeSystem(pipes)
            psys.build()

            # Run pipesystem
            psys.run()
            psys.close()

        :param pipes:, List[Pipes], List of Pipes with their upstreams/downstreams
        :param log_lvl: String, log level, one of: info, debug, warning, error or critical
        :param monitor: Bool, log stream I/O times
        :param ignore_exceptions: List of exceptions to ignore while pipeline is running
        :param plasma_memory: Int, memory (Gb) allocated to plasma store. Default 10Gb.
        :return: None

    """

    def __init__(self, pipes=None, log_lvl='INFO', monitor=False, ignore_exceptions=None,
                 plasma=False, plasma_store='/tmp/minipipe', plasma_memory=10):

        self.pipes = pipes or []
        self.log_lvl = log_lvl
        self.monitor = monitor
        self.ignore_exceptions = ignore_exceptions
        self.plasma = plasma
        self.plasma_store = plasma_store
        self.plasma_memory = int(plasma_memory*1e9)
        self.logger = Logger(log_lvl)

        self.streams = None
        self.processes = None
        self.segments = []
        self.built = False
        self.resq = None

    def add(self, pipes, upstream=None, downstream=None, buffer_size=1):
        """Adds a pipe segment to the pipeline.

           :param pipes: Pipes segment to add to PipeLine
           :param buffer_size: Size of Stream buffer
           :return: None
        """

        if not isinstance(pipes, list):
            pipes = [pipes]

        pipes = [copy(pipe) for pipe in pipes]

        for pipe in pipes:
            if upstream is not None:
                pipe.set_upstreams(upstream)
            if downstream is not None:
                pipe.set_downstreams(downstream)

        # After the Source connect each segment with a Stream
        if len(self.segments) > 0:
            name = 'plasma' if self.plasma else 'queue'
            s = Stream(buffer_size=buffer_size,
                       name=name,
                       monitor=self.monitor,
                       plasma=self.plasma,
                       plasma_store=self.plasma_store)

            for seg in self.segments[-1]:
                if not seg.downstreams and not isinstance(seg, Sink):
                    seg.downstreams = [s]
            for pipe in pipes:
                if not pipe.upstreams and not isinstance(pipe, Source):
                    pipe.upstreams = [s]

        self.pipes += pipes
        self.segments.append(pipes)

        return self


    def build(self):
        """Connects pipe segments together and builds pipe system graph. Creates child processes for each pipe segment.
         If at least one Stream has plasma=True then a plasma store subprocess is spawned, one for each unique plasma
         store (Stream.plasma_store).

        """
        self.global_term = Event()

        # Handle name collisions
        pnames = Counter([p.name for p in self.pipes])
        for pname, cnt in pnames.items():
            if cnt > 1:
                p_with_collisions = list(filter(lambda x: x.name==pname, self.pipes))
                for i, p in enumerate(p_with_collisions):
                    p.name += '_{}'.format(i)

        # Connect graph and set global term flag
        for p in self.pipes:
            if self.ignore_exceptions is not None:
                p.ignore_exceptions = self.ignore_exceptions
            p.global_term_flag = self.global_term
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
            p.logger = self.logger
            for s in p.downstreams + p.upstreams:
                if (s.monitor or self.monitor) and s.logger is None:
                    s.logger = self.logger

        # Get set of plasma stores used by Streams.
        self.plasma_stores = set()
        for p in self.pipes:
            self.plasma_stores.update(p.get_plasma_stores())

        # Check if any pipe segments need a result queue.
        for p in self.pipes:
            for name, mthd in vars(p.functor).items():
                if name == 'local_result' or hasattr(mthd, 'local_result'):
                    if self.resq is None:
                        self.resq = Queue()
                    p.resq = self.resq

        self.built = True
        return self

    def run(self, timeit=False, units='s'):
        """Runs pipeline."""

        time_conv = {'s': 1.0, 'ms': 1e3, 'us': 1e3,
                     'm': 1./60., 'h': 1./3600.}
        if timeit:
            assert(units in time_conv), f"units must be one of {time_conv.keys()}."
            t0 = time()

        if self.processes is None:
            self.build()

        # Create a subprocess for each plasma store.
        self.plasma_store_subprocs = []
        if self.plasma_stores:
            mem_per_store = int(self.plasma_memory / len(self.plasma_stores))

            for store in self.plasma_stores:
                args = ['plasma_store', '-m', str(mem_per_store), '-s', store]
                self.logger.log(f'Creating plasma store {store}', name='main', lvl='info')
                self.logger.log(f'Allocating {mem_per_store/1e9:0.3f} Gb memory', name='main', lvl='info')
                self.plasma_store_subprocs.append(Popen(args, stdout=PIPE, stderr=PIPE))

        # Start each process for pipes
        for proc in self.processes:
            proc.start()

        if timeit: t1 = time()

        ## Joins pipeline
        for proc in self.processes:
            proc.join()

        # Get results if any
        res = None
        if self.resq is not None:
            res = {}
            while not self.resq.empty():
                try:
                    res.update(self.resq.get())
                except Empty:
                    break

        # Terminate plasma store subprocesses
        for store, subproc in zip(self.plasma_stores, self.plasma_store_subprocs):
            self.logger.log(f'Terminating plasma store {store}', name='main', lvl='info')
            subproc.terminate()
            self.logger.log(f'Plasma store {store} terminated', name='main', lvl='info')

        if timeit:
            t2 = time()
            self.logger.log(f'Warm-up time: {(t1-t0)*time_conv[units]:0.2f}{units}', name='main', lvl='info')
            self.logger.log(f'Run time: {(t2-t1)*time_conv[units]:0.2f}{units}', name='main', lvl='info')
            self.logger.log(f'Total time: {(t2-t0)*time_conv[units]:0.2f}{units}', name='main', lvl='info')

        return res

    def reset(self):
        """Resets pipeline."""
        self.global_term.clear()
        for p in self.pipes:
            p.reset()
            p.logger = self.logger

        # Create new processes since they can only be started once
        self.processes = [Process(target=p.run_pipe, args=[p.name], name=p.name)
                          for p in self.pipes]

    def _connect_streams(self, p):
        for stream in p.downstreams:
            stream.add_pipe_out(p)
        for stream in p.upstreams:
            stream.add_pipe_in(p)

    def _count_relatives(self, p):
        for stream in p.downstreams:
            for p_in in stream.pipes_in:
                p_in._n_ances += 1
        for stream in p.upstreams:
            for p_out in stream.pipes_out:
                p_out._n_desc += 1


    def diagram(self, draw_streams=False):
        """Draws a graph diagram of pipeline.

           :params draw_streams: Bool, if True Streams will be included in graph diagram
           :return: graphviz Digraph object
        """

        assert(self.built==True), "ERROR: PipeSystem must be built first"
        g = Digraph()
        edges = set()

        # Assumes graph is a DAG thus iterate over downstreams only
        # There can only be one edge between nodes
        for p in self.pipes:
            g.node(p._id(), p.name)
            for s in p.downstreams:
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
