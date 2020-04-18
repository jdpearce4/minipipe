"""Base classes"""

from multiprocessing import Queue, Event, SimpleQueue
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
            :param name: name of logger
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
        The Stream class handles moving data between Pipe segments. If plasma=True then pyarrow.plasma will be used
        to move data between pipe segments, with a multiprocessing.Queue used to send object IDs (keys) between
        processes. Otherwise multiprocessing.Queue will be used to send data between processes.

        For large data, especially numpy arrays and pandas dataframes, it is recommended to use plasma=True. For small
        native python objects use plasma=False.

        :param name: String, name of Stream
        :param buffer_size: Int, max size of queue. Will be ignored if type(queue) = "multiprocessing.SimpleQueue"
        :param timeout: Int, timeout(s) value for Queue.put and Queue.get methods
        :param monitor: Bool, log stream I/O times
        :param queue: Queue, user defined queue object. Must be a multiprocessing queue such as
            multiprocessing.SimpleQueue or torch.multiprocessing.queue. multiprocessing.Queue is default.
        :param plasma: Bool, to use PyArrow.Plasma store or not. PyArrow must by installed. See docs.
        :param plasma_store: String, path to directory to use for plasma store. Streams are designed to share
        plasma stores. Each unique plasma_store will spawn a new subprocess
        :return: None
    """

    def __init__(self, buffer_size=1, timeout=None, monitor=False, name=None, queue=None,
                 plasma=False, plasma_store='/tmp/minipipe'):

        self.buffer_size = buffer_size
        self.q = queue or Queue(buffer_size)
        self.name = name or ('plasma' if plasma else 'queue')
        self.timeout = timeout
        self.plasma = plasma
        self.monitor = monitor
        self.pipes_out = [] # Reference to Pipes that put onto this stream
        self.pipes_in = []  # Reference to Pipes that get from this stream
        self.logger = None
        self.plasma_store = plasma_store

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

    def setlogger(self, logger):
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
                    self.logger.log('capacity:{:0.2f}%'.format(self.capacity()), self.name+':get')
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
                    self.logger.log('capacity:{:0.2f}%'.format(self.capacity()), self.name+':put')
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

    def __init__(self, functor):

        # Public methods
        self.functor = functor
        self.upstreams = []
        self.downstreams = []
        self.ignore_exceptions = []
        self.term_flag = Event()
        self.global_term_flag = None
        self.logger = None

        # Use name of function/class as default
        try:
            self.name = functor.__name__
        except AttributeError:
            self.name = type(functor).__name__

        # Private methods
        self._n_desc = 0
        self._n_ances = 0
        self._n_rcvd_term_sigs = 0
        self._n_outputs = 0
        self._n_inputs = 0
      

    def __repr__(self):
        return self.name

    def __copy__(self):
        cls = self.__class__
        cp = cls.__new__(cls)
        cp.__dict__.update(self.__dict__)
        cp.term_flag = Event()
        return cp

    def _id(self):
        return str(id(self))

    def __hash__(self):
        return int(self._id())

    def __eq__(self, other):
        return self.__hash__() == hash(other)

    def set_upstreams(self, upstreams):
        if not isinstance(upstreams, list):
            upstreams = [upstreams]
        for upstream in upstreams:
            assert (isinstance(upstream, Stream)), "Error: upstreams must be of minipipe.Stream type"
        self.upstreams = upstreams
        self._n_inputs = len(upstreams)

    def set_downstreams(self, downstreams):
        if not isinstance(downstreams, list):
            downstreams = [downstreams]
        for downstream in self.downstreams:
            assert (isinstance(downstream, Stream)), "Error: downtreams must be of minipipe.Stream type"
        self.downstreams = downstreams
        self._n_outputs = len(downstreams)

    def get_plasma_stores(self):
        plasma_stores = set()
        for stream in self.upstreams + self.downstreams:
            if stream.plasma:
                plasma_stores.add(stream.plasma_store)
        return list(plasma_stores)

    def reset(self):
        self._n_rcvd_term_sigs = 0
        self.term_flag.clear()
        self._reset_functor()
        for stream in self.downstreams:
            stream.flush()

    def _in(self):
        # For each stream in upstreams get data (pickle stream) or object ID (plasma stream)
        # If stream is plasma stream use object ID to get data from plasma store
        # Return list of data from each stream
        x = []
        for stream in self.upstreams:
            x_i = stream.get()
            if stream.plasma and not (x_i is Sentinel or x_i is None):
                if self._plasma_contains_object_id(stream.plasma_store, x_i):
                    x_i = self.plasma[stream.plasma_store].get(x_i)
                else:
                    x_i = None
            x.append(x_i)
        # Log repr for debugging
        self.logger.log("in({})".format([type(x_i) for x_i in x]), self.name, 'debug')
        return x

    def _out(self, x):
        # Make list if not already one
        if self._n_outputs <=1:
            x = [x]
        # Put data into downstreams (pickle stream) or data into plasma store and object ID into downstream Queue
        for x_i, stream in zip(x, self.downstreams):
            if stream.plasma and not (x_i is Sentinel or x_i is None):
                put_in_plasma = []
                found = False
                # To avoid putting the same object in plasma
                for x_j, obj_id in put_in_plasma:
                    if x_i is x_j:
                        stream.put(obj_id)
                        found = True
                        break
                if not found:
                    obj_id = self.plasma[stream.plasma_store].put(x_i)
                    stream.put(obj_id)
                    put_in_plasma.append((x_i, obj_id))
            else:
                stream.put(x_i)
        # Log repr out for debugging
        self.logger.log("out({})".format([type(x_i) for x_i in x]), self.name, 'debug')

    def _continue(self):
        return not (self.term_flag.is_set() or self.global_term_flag.is_set())

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
        self.global_term_flag.set()
        self.logger.log("Global termination", self.name, "error")
        return True

    def _plasma_contains_object_id(self, store, obj_id):
        if not self.plasma[store].contains(obj_id):
            self.logger.log("Object ID missing from plasma store. Object may be evicted",
                             self.name, "error")
            self.logger.log("Increase plasma memory or reduce data chunk size.",
                             self.name, "info")
            self._terminate_global()
            self._terminate_local()
            return False
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
            self.term_flag.set()
            for _ in range(self._n_desc):
                self._out([Sentinel]*self._n_outputs if self._n_outputs > 1 else Sentinel)
            self.logger.log("Local termination", self.name)
            return True

    def _run_loop(self):
        # To be implemented in derived classes
        pass

    def run_pipe(self, name=None):
        # This method is called once on local process

        if name is not None:
            self.name = name

        # Check if any upstreams or downstreams are plasma streams
        # If at least one plasma stream check if pyarrow is installed
        plasma_stores = self.get_plasma_stores()
        if plasma_stores:
            try:
                import pyarrow.plasma as plasma
            except ModuleNotFoundError:
                self.logger.log("pyarrow.plasma not found", self.name, 'error')

        # Connect to plasma store and create client
        self.plasma = {}
        for store in plasma_stores:
            try:
                self.plasma[store] = plasma.connect(store)
            except ArrowIOError:
                self.logger.log("pyarrow.plasma could not connect", self.name, 'error')

        # Check if local_init exists and if so initialize on local process
        for name, mthd in vars(self.functor).items():
            if name == 'local_init' or hasattr(mthd, 'local_init'):
                mthd(self=self.functor_inst)

        try:
            # run functor loop on local process
            self._run_loop()

            # check if local_term method exists, if so run once after pipe segment has terminated
            for name, mthd in vars(self.functor).items():
                if name == 'local_term' or hasattr(mthd, 'local_term'):
                    mthd(self=self.functor_inst)

            # check if functor returns a result via the result method. If so pass result to result queue.
            for name, mthd in vars(self.functor).items():
                if name == 'local_result' or hasattr(mthd, 'local_result'):
                    res = mthd(self=self.functor_inst)
                    self.resq.put({self.name:res})

            # Disconnect plasma clients
            for store, client in self.plasma.items():
                self.logger.log(f'Disconnecting plasma {store} client', self.name, 'info')
                client.disconnect()

        except KeyboardInterrupt:
            self.logger.log("KeyboardInterrupt", self.name, 'error')
            raise KeyboardInterrupt

    # Decorators
    def init(func):
        func.local_init = True
        return func

    def term(func):
        func.local_term = True
        return func

    def call(func):
        func.local_call = True
        return func

    def result(func):
        func.local_result = True
        return func

