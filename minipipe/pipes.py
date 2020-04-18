""" Derived Pipe classes """

from minipipe.base import Pipe, Sentinel
import functools
from copy import copy

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

    def __init__(self, functor):
        functools.update_wrapper(self, functor)
        super(Source, self).__init__(functor)

    def __call__(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs
        self.generator = self.functor(*args, **kwargs)
        return copy(self)

    def __iter__(self):
        return self.generator

    def __next__(self):
        return next(self.generator)

    def _reset_functor(self):
        self.generator = self.functor(*self.args, **self.kwargs)

    def _run_loop(self):

        # Generator functors are used for sources
        # Will terminate once end of generator is reached

        x = None
        while self._continue():
            try:

                # Get next item from generator
                x = next(self.generator)

                # Check for Sentinel signaling termination
                if x is Sentinel:
                    self._terminate_local()
                    break

                # Do nothing on None
                if x is None:
                    continue

                self._out(x)

            # Terminate once end of generator is reached
            except StopIteration:
                self.logger.log('End of stream', self.name)
                self._terminate_local()

            # These exceptions are ignored raising WARNING only
            except BaseException as e:
                if e.__class__ in self.ignore_exceptions:
                    self.logger.log(str(e), self.name, 'warning')
                    continue
                else:
                    self.logger.log(str(e), self.name, 'error')
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

    def __init__(self, functor):
        functools.update_wrapper(self, functor)
        self._functor_is_function = type(functor) == type(lambda _: _)
        if self._functor_is_function:
            self.function = functor
        super(Sink, self).__init__(functor)

    def __call__(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs
        if self._functor_is_function:
            return self.function(*args, **kwargs)
        else:
            self.functor_inst = self.functor(*args, **kwargs)
            for name, mthd in vars(self.functor).items():
                if name[:2] + name[-2:] != '_' * 4:  # checks for public methods
                    vars(self).update({name: functools.partial(mthd, self.functor_inst)})
                if name == 'local_call' or hasattr(mthd, 'local_call'):
                    self.function = functools.partial(mthd, self.functor_inst)

            return copy(self)

    def _reset_functor(self):
        if not self._functor_is_function:
            self.__call__(*self.args, **self.kwargs)

    def _run_loop(self):

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

                # Run functor or local_call function
                self.function(*x)

            # These exceptions are ignored raising WARNING only
            except BaseException as e:
                if e.__class__ in self.ignore_exceptions:
                    self.logger.log(str(e), self.name, 'warning')
                    continue
                else:
                    self.logger.log(str(e), self.name, 'error')
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

    def __init__(self, functor):
        functools.update_wrapper(self, functor)
        self._functor_is_function = type(functor) == type(lambda _: _)
        if self._functor_is_function:
            self.function = functor
        super(Transform, self).__init__(functor)

    def __call__(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs
        if self._functor_is_function:
            return self.function(*args, **kwargs)
        else:
            self.functor_inst = self.functor(*args, **kwargs)
            for name, mthd in vars(self.functor).items():
                if name[:2] + name[-2:] != '_'*4: #checks for public methods
                    vars(self).update({name:functools.partial(mthd, self.functor_inst)})
                if name == 'local_call' or hasattr(mthd, 'local_call'):
                    self.function = functools.partial(mthd, self.functor_inst)

            return copy(self)

    def _reset_functor(self):
        if not self._functor_is_function:
            self.__call__(*self.args, **self.kwargs)

    def _run_loop(self):

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
                # Run functor or local_call function
                x = self.function(*x)
                self._out(x)

            # These exceptions are ignored raising WARNING only
            except BaseException as e:
                if e.__class__ in self.ignore_exceptions:
                    self.logger.log(str(e), self.name, 'warning')
                    continue
                else:
                    self.logger.log(str(e), self.name, 'error')
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

    def __init__(self, functor):
        functools.update_wrapper(self, functor)
        super(Regulator, self).__init__(functor)

    def __call__(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs
        self.coroutine = self.functor(*args, **kwargs)
        next(self.coroutine)
        return copy(self)

    def __iter__(self):
        return self.coroutine

    def __next__(self):
        return next(self.coroutine)

    def _reset_functor(self):
        self.coroutine = self.functor(*self.args, **self.kwargs)
        next(self.coroutine)

    def _run_loop(self):

        # Coroutine functors act as a transformation and source
        # Useful when the data needs to be broken up or accumulated
        # On StopIteration coroutine is reset

        x = None
        #self.__call__()

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
                x_i = self.coroutine.send(*x)

                # Iterate over coroutine output
                while x_i is not None:
                    self._out(x_i)
                    try:
                        x_i = next(self.coroutine)
                    except StopIteration:
                        # Reset coroutine for next data
                        self._reset_functor()
                        break

            # These exceptions are ignored raising WARNING only
            except BaseException as e:
                if e.__class__ in self.ignore_exceptions:
                    self.logger.log(str(e), self.name, 'warning')
                    continue
                else:
                    self.logger.log(str(e), self.name, 'error')
                    self._terminate_global()
                    raise e
