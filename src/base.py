from multiprocessing import Queue, Process, Event
from queue import Empty, Full
from collections import Counter
import logging
from graphviz import Digraph
from copy import copy

class Sentinel(object):
    """
        This class is used to indicate the end of a stream. When a instance of Sentinel is
        passed to a Pipe it will shut itself down.
    """
    def __repr__(self):
        return 'sentinel'

class Logger(object):
    """
        Logger class used by Pipe. There are five levels of logs: INFO, DEBUG, WARNING, ERROR and CRITICAL.
        By default logger is set to INFO.
    """

    def __init__(self, lvl='INFO'):
        self.log_lvl_map = {'INFO':logging.INFO,
                            'DEBUG':logging.DEBUG,
                            'WARNING':logging.WARNING,
                            'ERROR':logging.ERROR,
                            'CRITICAL':logging.CRITICAL}

        assert(lvl in self.log_lvl_map), "log_lvl must be one of: {}".format(self.log_lvl_map.keys())
        self.lvl = self.log_lvl_map[lvl]
        self.logger = logging.getLogger("logger")
        self.logger.propagate = False

        # jupyter already has a logger initialized
        # this avoids initializing it multiple times
        if hasattr(self.logger, 'handler_set'):
            while self.logger.handlers:
                self.logger.handlers.pop()
        ch = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(pname)s - %(message)s')
        ch.setFormatter(formatter)
        ch.setLevel(lvl)
        self.logger.addHandler(ch)
        self.logger.setLevel(lvl)
        self.logger.handler_set = True

    def log(self, msg, name, lvl='info'):

        """
            Logs messages.

            :param msg: message to log
            :param name: name of object invoking logs
            :param lvl: log level, one of: info, debug, warning, error or critical
            :return: None
        """

        extra = {'pname':name}
        if lvl == 'critical':
            self.logger.critical(msg, extra=extra)
        elif lvl == 'debug':
            self.logger.debug(msg, extra=extra)
        elif lvl == 'warning':
            self.logger.warning(msg, extra=extra)
        elif lvl == 'error':
            self.logger.error(msg, extra=extra)
        else:
            self.logger.info(msg, extra=extra)


class Stream(object):

    """
        Based off of a multiprocessing queue, Stream handles moving data between Pipe segments.
    """

    def __init__(self, name = 'stream', buffer_size=1, timeout=None, monitor=False):
        self.q = Queue(buffer_size)
        self.timeout = timeout
        self.buffer_size = buffer_size
        self.name = name
        self.monitor = monitor
        self.pipes_out = [] # Reference to Pipes that put onto this stream
        self.pipes_in = []  # Reference to Pipes that get from this stream
        self.logger = None

    def _id(self):
        return str(id(self))

    def __hash__(self):
        return int(self._id())

    def __eq__(self, other):
        return self.__hash__() == hash(other)

    def add_pipe_in(self, pipe_in):
        self.pipes_in.append(pipe_in)

    def add_pipe_out(self, pipe_out):
        self.pipes_out.append(pipe_out)

    def empty(self):
        return self.q.empty()

    def full(self):
        return self.q.full()

    def capacity(self):
        return 100.0*self.q.qsize()/self.buffer_size

    def set_logger(self, logger):
        self.logger = logger

    def flush(self):
        try:
            while True:
                self.q.get_nowait()
        except Empty:
            pass

    def get(self, timeout=1):

        # While pipes out are running and not empty try to get data
        # timeout value is necessary else get may run indefinitely after pipes out shutdown

        x = None
        while (any([p._continue() for p in self.pipes_out]) or not self.q.empty()):
            try:
                x = self.q.get(timeout=timeout or self.timeout)
                if self.monitor:
                    self.logger.log('capacity:{:0.2f}%'.format(self.capacity()),
                                    self.name+':get')
                break
            except Empty:
                continue
        return x

    def put(self, x, timeout=1):

        # While pipes in are running try to put data
        # no need to check if full since Full exception is caught
        # timeout value is necessary else put may run indefinitely after pipes in shutdown

        while any([p._continue() for p in self.pipes_in]):
            try:
                if x is None:
                    break
                self.q.put(x, timeout=timeout or self.timeout)
                if self.monitor:
                    self.logger.log('capacity:{:0.2f}%'.format(self.capacity()),
                                    self.name+':put')
                break
            except Full:
                continue

class Pipe(object):
    """
        Base class for all pipe segments. Pipes use two sets of Streams: upstreams and downstreams.
        Generally Pipes except data from upstreams and pass downstream after a transformation.
        All pipe segments run on their own thread or process, which allows them to run in
        parallel with other segments.

        Number of upstreams should be equal to number of functor args. Likewise, number of downstreams
        should be equal to number of functor outputs.

        When Pipe produces a None it will not be passed downstream. In this case nothing will be placed
        on the downstreams. This allows the user to create 'switches' based on internal logic in the functor.


        Base initializer
        -----------------

        :param functor: Python function, class, generator or corountine
        :param name: String associated with pipe segment
        :param upstreams: List of Streams that are inputs to functor
        :param downstreams: List of Streams that are outputs of functor
        :param init_kwargs: Kwargs to initiate class object on process (no used when func_type = 'function')

    """

    def __init__(self, functor, name, upstreams=[], downstreams=[],
                 ignore_exceptions=[], init_kwargs={}, stateful=False):

        # Public methods
        self.functor = functor
        self.name = name
        self.init_kwargs = init_kwargs
        self.stateful = stateful
        self.upstreams = upstreams
        self.downstreams = downstreams
        self.ignore_exceptions = ignore_exceptions

        # Private methods
        self._n_desc = 0
        self._n_ances = 0
        self._n_rcvd_term_sigs = 0
        self._n_outputs = len(self.downstreams)
        self._n_inputs = len(self.upstreams)
        self._term_flag = Event()
        self._global_term_flag = None
        self._logger = None

    def __repr__(self):
        return self.name

    def _id(self):
        return str(id(self))

    def __hash__(self):
        return int(self._id())

    def __eq__(self, other):
        return self.__hash__() == hash(other)

    def set_logger(self, logger):
        self._logger = logger

    def set_term_flag(self, term_flag):
        self._term_flag = term_flag

    def set_global_term_flag(self, term_flag):
        self._global_term_flag = term_flag

    def set_upstreams(self, upstreams):
        self.upstreams = upstreams

    def set_downstreams(self, downstreams):
        self.downstreams = downstreams

    def get_upstreams(self):
        return self.upstreams

    def get_downstreams(self):
        return self.downstreams

    def public_vars(self):
        return {k:v for k,v in vars(self).items() if k[0] != '_'}

    def reset(self):
        self._n_rcvd_term_sigs = 0
        self._term_flag.clear()
        for stream in self.downstreams:
            stream.flush()

    def _in(self):
        x = [stream.get() for stream in self.upstreams]
        self._logger.log("in({})".format([repr(x_i) for x_i in x]), self.name, 'debug')
        return x

    def _out(self, x):
        if self._n_outputs <=1: x = [x]
        self._logger.log("out({})".format([repr(x_i) for x_i in x]), self.name, 'debug')
        for x_i, stream in zip(x, self.downstreams):
            stream.put(x_i)

    def _continue(self):
        return not (self._term_flag.is_set() or self._global_term_flag.is_set())

    def _contains_sentinel(self, x):
        for x_i in x:
            if x_i is Sentinel:
                return True
        return False

    def _contains_none(self, x):
        for x_i in x:
            if x_i is None:
                return True
        return False

    def _terminate_global(self):
        self._global_term_flag.set()
        self._logger.log("Global termination", self.name, "error")
        return True

    def _terminate_local(self):

        # Each time a Sentinel is caught this method is called
        # Pipe segment is only shutdown if its recieved a Sentinel from each Pipe upstream
        # If all upstream Pipes are accounted for:
        #    1) set term flag
        #    2) send 1 Sentinel to each downstream Pipe
        #    3) return True

        if self._n_rcvd_term_sigs < self._n_ances:
            self._n_rcvd_term_sigs += 1
            return False
        else:
            self._term_flag.set()
            for _ in range(self._n_desc):
                self._out([Sentinel]*self._n_outputs if self._n_outputs > 1 else Sentinel)
            self._logger.log("Local termination", self.name)
            return True

    def run_functor(self):
        pass

    def run_pipe(self, name=None):

        if self.stateful:
            assert hasattr(self.functor, 'run'), 'ERROR: stateful functor class must implement "run" method'
            cls = self.functor(**self.init_kwargs)
            self.functor = cls.run

        if name is not None:
            self.name = name

        try:
            self.run_functor()
        except KeyboardInterrupt:
            self._logger.log("KeyboardInterrupt", self.name, 'error')


class PipeSystem(object):

    """
        PipeSystem connects Pipes and creats process pool. Pipes are run and closed with a built PipeSystem.

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

    def __init__(self, pipes=[]):
        self.pipes = pipes
        self.streams = None
        self.processes = None
        self.built = False

    def build(self, log_lvl='INFO', monitor=False, ignore_exceptions=None):
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
            self._connect_upstreams(p)
            self._connect_downstreams(p)

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
        if self.processes is None:
            self.build()
        for proc in self.processes:
            proc.start()

    def close(self):
        for proc in self.processes:
            proc.join()

    def reset(self):
        self.global_term.clear()
        for p in self.pipes:
            p.reset()
            p.set_logger(self.logger)

        # Create new processes since they can only be started once
        self.processes = [Process(target=p.run_pipe, args=[p.name], name=p.name)
                          for p in self.pipes]

    def _connect_downstreams(self, p):
        for stream in p.get_downstreams():
            stream.add_pipe_out(p)
            for p_in in stream.pipes_in:
                p_in._n_ances += 1

    def _connect_upstreams(self, p):
        for stream in p.get_upstreams():
            stream.add_pipe_in(p)
            for p_out in stream.pipes_out:
                p_out._n_desc += 1


    def diagram(self, draw_streams=False):
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

    def add(self, pipe, n_processes=1, buffer_size=1):

        if len(self.segments) > 0:
            s = Stream(buffer_size=buffer_size,
                       name = 'stream_{}'.format(self.sid),
                       monitor=self.monitor)
            self.sid += 1
            for seg in self.segments[-1]:
                seg.set_downstreams([s])
            pipe.set_upstreams([s])

        seg = [copy(pipe) for _ in range(n_processes)]
        self.pipes += seg
        self.segments.append(seg)
