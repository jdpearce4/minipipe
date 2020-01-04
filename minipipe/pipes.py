""" Derived Pipe classes """

from minipipe.base import Pipe, Sentinel

class Source(Pipe):
    """
        Source pipes are used to load and/or generate data. Sources have no upstreams, but will have one or more
        downstreams. Functor must be a valid Python generator. The generator should be initialized before passing
        as argument.

        :param functor: Python generator
        :param name: String associated with pipe segment
        :param downstreams: List of Streams that are outputs of functor
        :param ignore_exceptions: List of exceptions to ignore while pipeline is running
    """

    def __init__(self, functor_obj, name='Source', downstreams=None, ignore_exceptions=None):

        # Source has no upstreams
        super(Source, self).__init__(functor_obj, name, None, downstreams, ignore_exceptions)

    def run_functor(self):

        # Generator functors are used for sources
        # Will terminate once end of generator is reached

        x = None
        while self._continue():
            try:

                # Get next item from generator
                try:
                    x = next(self.functor)
                except TypeError:
                    # If generator is not initialized
                    self.functor = self.functor()
                    x = next(self.functor)

                # Check for Sentinel signaling termination
                if x is Sentinel:
                    self._terminate_local()
                    break

                # Do nothing on python None
                if x is None:
                    continue

                self._out(x)

            # Terminate once end of generator is reached
            except StopIteration:
                self._logger.log('End of stream', self.name)
                self._terminate_local()

            # These exceptions are ignored raising WARNING only
            except BaseException as e:
                if e.__class__ in self.ignore_exceptions:
                    self._logger.log(str(e), self.name, 'warning')
                    continue
                else:
                    self._logger.log(str(e), self.name, 'error')
                    self._terminate_global()
                    raise e


class Sink(Pipe):
    """
            Sink pipes are typically used to save/output data. Sinks have no downstreams, but will have one or more
            upstreams. Functor should be either a Python function or class with a "run" method and optionally
            "local_init" and "local_term" methods. Local_init, if supplied will be called once on the local process
            before run, while local_term will be called once afterwards.

            :param functor: Python function or class
            :param name: String associated with pipe segment
            :param upstreams: List of Streams that are inputs to functor
            :param init_kwargs: Kwargs to initiate class object on process (no used when func_type = 'function')
            :param ignore_exceptions: List of exceptions to ignore while pipeline is running

        """

    def __init__(self, functor_obj, name='Sink', upstreams=None,
                 ignore_exceptions=None, init_kwargs=None):

        # Sink has no downstreams
        super(Sink, self).__init__(functor_obj, name, upstreams, None,
                                   ignore_exceptions, init_kwargs)

    def run_functor(self):

        x = None
        while self._continue():
            try:

                x = self._in()

                # Check for Sentinel signaling termination
                if self._contains_sentinel(x):
                    if self._terminate_local():
                        break
                    else:
                        continue

                # Do nothing on python None
                if self._contains_none(x):
                    continue

                x = self.functor(*x)
                self._out(x)

            # These exceptions are ignored raising WARNING only
            except BaseException as e:
                if e.__class__ in self.ignore_exceptions:
                    self._logger.log(str(e), self.name, 'warning')
                    continue
                else:
                    self._logger.log(str(e), self.name, 'error')
                    self._terminate_global()
                    raise e


class Transform(Pipe):
    """
            Transform pipes are used to perform arbitrary transformations on data. Transforms will have one or more
            upstreams and downstreams. Functor should be either a Python function or class with a "run" method and optionally
            "local_init" and "local_term" methods. Local_init, if supplied will be called once on the local process
            before run, while local_term will be called once afterwards.

            :param functor: Python function or class
            :param name: String associated with pipe segment
            :param upstreams: List of Streams that are inputs to functor
            :param downstreams: List of Streams that are outputs of functor
            :param init_kwargs: Kwargs to initiate class object on process (no used when func_type = 'function')
            :param ignore_exceptions: List of exceptions to ignore while pipeline is running
        """

    def __init__(self, functor_obj, name='Transform', upstreams=None, downstreams=None,
                 ignore_exceptions=None, init_kwargs=None):

        super(Transform, self).__init__(functor_obj, name, upstreams, downstreams,
                                        ignore_exceptions, init_kwargs)

    def run_functor(self):

        x = None
        while self._continue():
            try:

                x = self._in()

                # Check for Sentinel signaling termination
                if self._contains_sentinel(x):
                    if self._terminate_local():
                        break
                    else:
                        continue

                # Do nothing on python None
                if self._contains_none(x):
                    continue

                x = self.functor(*x)
                self._out(x)

            # These exceptions are ignored raising WARNING only
            except BaseException as e:
                if e.__class__ in self.ignore_exceptions:
                    self._logger.log(str(e), self.name, 'warning')
                    continue
                else:
                    self._logger.log(str(e), self.name, 'error')
                    self._terminate_global()
                    raise e

class Regulator(Pipe):
    """
            Regulator pipes are a special type of transformation that changes the data chunk throughput, typically used
            for batching or accumulating data. Regulators can have both upstreams and downstreams. Functor should be a
            Python coroutine. The coroutine should not be initialized, instead use init_kwargs to initialize on the local
            process.

            :param functor: Python coroutines
            :param name: String associated with pipe segment
            :param upstreams: List of Streams that are inputs to functor
            :param downstreams: List of Streams that are outputs of functor
            :param init_kwargs: Kwargs to initiate class object on process (no used when func_type = 'function')
            :param ignore_exceptions: List of exceptions to ignore while pipeline is running
        """

    def __init__(self, functor_obj, name='Regulator', upstreams=None, downstreams=None,
                 ignore_exceptions=None, init_kwargs=None):

        super(Regulator, self).__init__(functor_obj, name, upstreams, downstreams,
                                        ignore_exceptions, init_kwargs)

    def run_functor(self):

        # Coroutine functors act as a transformation and source
        # Useful when the data needs to be broken up or accumulated
        # On StopIteration coroutine is reset

        coroutine = self.functor(**self.init_kwargs)
        next(coroutine)
        x = None
        while self._continue():
            try:

                x = self._in()

                # Check for Sentinel signaling termination
                if self._contains_sentinel(x):
                    if self._terminate_local():
                        break
                    else:
                        continue

                # Do nothing on python None
                if self._contains_none(x):
                    continue

                # Send data to coroutine
                x_i = coroutine.send(*x)

                # Iterate over coroutine output
                while x_i is not None:
                    self._out(x_i)
                    try:
                        x_i = next(coroutine)
                    except StopIteration:
                        # Reset coroutine for next data
                        coroutine = self.functor(**self.init_kwargs)
                        next(coroutine)
                        break

            # These exceptions are ignored raising WARNING only
            except BaseException as e:
                if e.__class__ in self.ignore_exceptions:
                    self._logger.log(str(e), self.name, 'warning')
                    continue
                else:
                    self._logger.log(str(e), self.name, 'error')
                    self._terminate_global()
                    raise e
