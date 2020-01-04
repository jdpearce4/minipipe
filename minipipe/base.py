"""Base classes"""

from multiprocessing import Queue, Event
from queue import Empty, Full
import logging

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

        :param lvl: log level, one of: info, debug, warning, error or critical
        :return: None
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

    def __init__(self, name = 'stream', buffer_size=3, timeout=None, monitor=False):
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
        :param ignore_exceptions: List of exceptions to ignore while pipeline is running
        :param init_kwargs: Kwargs to initiate class object on process (no used when func_type = 'function')
        :param stateful: Set to True when using a class functor. Class functors must implement a 'run' method

    """

    def __init__(self, functor_obj, name, upstreams=None, downstreams=None,
                 ignore_exceptions=None, init_kwargs=None):

        # Public methods
        self.functor_obj = functor_obj
        self.name = name
        self.init_kwargs = init_kwargs or {}
        self.upstreams = upstreams or []
        self.downstreams = downstreams or []
        self.ignore_exceptions = ignore_exceptions or []

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

    def __copy__(self):
        cls = self.__class__
        cp = cls.__new__(cls)
        cp.__dict__.update(self.__dict__)
        cp._term_flag = Event()
        return cp

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
        self._n_inputs = len(upstreams)

    def set_downstreams(self, downstreams):
        self.downstreams = downstreams
        self._n_outputs = len(downstreams)

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
        if self._n_outputs <=1:
            x = [x]
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

        self._n_rcvd_term_sigs += 1
        if self._n_rcvd_term_sigs < self._n_ances:
            return False
        else:
            self._term_flag.set()
            for _ in range(self._n_desc):
                self._out([Sentinel]*self._n_outputs if self._n_outputs > 1 else Sentinel)
            self._logger.log("Local termination", self.name)
            return True

    def run_functor(self):
        # To be implemented in derived classes
        pass

    def run_pipe(self, name=None):
        # This method is called once on local process

        if name is not None:
            self.name = name

        # Check if local_init exists and if so initialize on local process
        if hasattr(self.functor_obj, 'local_init'):
            self.functor_obj.local_init(**self.init_kwargs)

        # Check if run method exists, if so use it as functor, otherwise use __call__ method
        if hasattr(self.functor_obj, 'run'):
            self.functor = self.functor_obj.run
        else:
            self.functor = self.functor_obj

        try:
            # run functor loop on local process
            self.run_functor()

            # check if local_term method exists, if so run once after pipe segment has terminated
            if hasattr(self.functor_obj, 'local_term'):
                self.functor_obj.local_term()

        except KeyboardInterrupt:
            self._logger.log("KeyboardInterrupt", self.name, 'error')


