""" Parent pipe classes """

from minipipe.base import Pipe, Sentinel

class Source(Pipe):

    def __init__(self, functor, name='Source', downstreams=[],
                 ignore_exceptions=[], init_kwargs={}, stateful=False):
        # Source has no upstreams
        super(Source, self).__init__(functor, name, [], downstreams,
                                     ignore_exceptions, init_kwargs, stateful)

    def run_functor(self):

        # Generator functors are used for sources
        # Will terminate once end of generator is reached

        generator = self.functor(**self.init_kwargs)
        x = None
        while self._continue():
            try:
                x = generator.next()
                if x is Sentinel:
                    self._terminate_local()
                    break
                if x is None:
                    continue
                self._out(x)
            except StopIteration:
                self._logger.log('End of stream', self.name)
                self._terminate_local()
            except BaseException as e: # These exceptions are ignored raising WARNING only
                if e.__class__ in self.ignore_exceptions:
                    self._logger.log(str(e), self.name, 'warning')
                    continue
                else:
                    self._logger.log(str(e), self.name, 'error')
                    self._terminate_global()
                    raise e


class Sink(Pipe):

    def __init__(self, functor, name='Sink', upstreams=[],
                 ignore_exceptions=[], stateful=False):
        # Sink has no downstreams
        super(Sink, self).__init__(functor, name, upstreams, [],
                                   ignore_exceptions, stateful)

    def run_functor(self):
        # Function functors are statless transformations

        x = None
        while self._continue():
            try:
                x = self._in()
                if self._contains_sentinel(x):
                    if self._terminate_local():
                        break
                    else:
                        continue
                if self._contains_none(x):
                    continue
                x = self.functor(*x)
                self._out(x)
            except BaseException as e: # These exceptions are ignored raising WARNING only
                if e.__class__ in self.ignore_exceptions:
                    self._logger.log(str(e), self.name, 'warning')
                    continue
                else:
                    self._logger.log(str(e), self.name, 'error')
                    self._terminate_global()
                    raise e


class Transform(Pipe):

    def __init__(self, functor, name='Transform', upstreams=[], downstreams=[],
                 ignore_exceptions=[], init_kwargs={}, stateful=False):
        super(Transform, self).__init__(functor, name, upstreams, downstreams,
                                        ignore_exceptions, init_kwargs, stateful)

    def run_functor(self):

        x = None
        while self._continue():
            try:
                x = self._in()
                if self._contains_sentinel(x):
                    if self._terminate_local():
                        break
                    else:
                        continue
                if self._contains_none(x):
                    continue
                x = self.functor(*x)
                self._out(x)
            except BaseException as e: # These exceptions are ignored raising WARNING only
                if e.__class__ in self.ignore_exceptions:
                    self._logger.log(str(e), self.name, 'warning')
                    continue
                else:
                    self._logger.log(str(e), self.name, 'error')
                    self._terminate_global()
                    raise e

class Regulator(Pipe):

    def __init__(self, functor, name='Regulator', upstreams=[], downstreams=[],
                 ignore_exceptions=[], init_kwargs={}, stateful=False):
        super(Regulator, self).__init__(functor, name, upstreams, downstreams,
                                        ignore_exceptions, init_kwargs, stateful)

    def run_functor(self):

        # Coroutine functors act as a transformation and source
        # Useful when the data needs to be broken up or accumulated
        # On StopIteration coroutine is reset

        corountine = self.functor(**self.init_kwargs)
        next(corountine)
        x = None
        while self._continue():
            try:
                x = self._in()
                if self._contains_sentinel(x):
                    if self._terminate_local():
                        break
                    else:
                        continue
                if self._contains_none(x):
                    continue
                x_i = corountine.send(*x)
                while x_i is not None:
                    self._out(x_i)
                    try:
                        x_i = corountine.next()
                    except StopIteration:
                        corountine = self.functor(**self.init_kwargs)
                        next(corountine)
                        break
            except BaseException as e: # These exceptions are ignored raising WARNING only
                if e.__class__ in self.ignore_exceptions:
                    self._logger.log(str(e), self.name, 'warning')
                    continue
                else:
                    self._logger.log(str(e), self.name, 'error')
                    self._terminate_global()
                    raise e
