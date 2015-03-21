import os
import pytest
import json
import logging
import logging.handlers
import pyethereum.slogging as slogging


class TestHandler(logging.handlers.BufferingHandler):

    def __init__(self):
        logging.Handler.__init__(self)
        self.capacity = 10000
        self.buffer = []

    @property
    def logged(self):
        # returns just the message part (no formatting)
        if len(self.buffer):
            return self.buffer.pop().getMessage()
        return None

    def does_log(self, logcall):
        assert self.logged is None
        logcall('abc')
        sl = self.logged
        return bool(sl and 'abc' in sl)


def get_test_handler():
    "handler.bufffer = [] has the logged lines"
    th = TestHandler()
    logging.getLogger().handlers = [th]
    return th

def setup_logging(config_string='', log_json=False):
    # setsup default logging
    slogging.configure(config_string=config_string, log_json=log_json)
    th = get_test_handler()
    return th


########## TESTS ###############

def test_testhandler():
    th = get_test_handler()
    assert th.logged == None
    th = setup_logging()
    assert th.logged is None
    log = slogging.get_logger('a')
    log.warn('abc')
    assert 'abc' in th.logged
    assert th.logged is None
    # same with does_log
    assert th.does_log(log.warn)
    assert not th.does_log(log.debug)


def test_baseconfig():
    # test default loglevel INFO
    th = setup_logging()
    log = slogging.get_logger()
    assert th.does_log(log.error)
    assert th.does_log(log.critical)
    assert th.does_log(log.warn)
    assert th.does_log(log.warn)
    assert th.does_log(log.info)
    assert not th.does_log(log.debug)
    assert not th.does_log(log.trace)
    config_string = ':inFO,a:trace,a.b:debug'
    th = setup_logging(config_string=config_string)

def test_lvl_trace():
    config_string = ':trace'
    th = setup_logging(config_string=config_string)
    log = slogging.get_logger()
    assert th.does_log(log.debug)
    assert th.does_log(log.trace)

def test_incremental():
    config_string = ':trace'
    th = setup_logging(config_string=config_string)
    log = slogging.get_logger()
    # incremental context
    log = log.bind(first='one')
    log.error('nice', a=1, b=2)
    assert 'first' in th.logged
    log = log.bind(second='two')
    log.error('nice', a=1, b=2)
    l = th.logged
    assert 'first' in l and 'two' in l

def test_jsonconfig():
    th = setup_logging(log_json=True)
    log = slogging.get_logger('prefix')
    log.warn('abc', a=1)
    assert json.loads(th.logged) == dict(event='prefix.abc', a=1)


def test_kvprinter():
    # we can not test formatting
    config_string = ':inFO,a:trace,a.b:debug'
    th = setup_logging(config_string=config_string)
    # log level info
    log = slogging.get_logger('foo')
    log.info('baz', arg=2)
    l = th.logged
    assert 'baz' in l

def test_namespaces():
    config_string = ':inFO,a:trace,a.b:debug'
    th = setup_logging(config_string=config_string)
    # log level info
    log = slogging.get_logger()
    log_a = slogging.get_logger('a')
    log_a_b = slogging.get_logger('a.b')
    assert th.does_log(log.info)
    assert not th.does_log(log.debug)
    assert th.does_log(log_a.trace)
    assert th.does_log(log_a_b.debug)
    assert not th.does_log(log_a_b.trace)

def test_tracebacks():
    th = setup_logging()
    log = slogging.get_logger()
    def div(a,b):
        try:
            r =  a/b
            log.error('heres the stack', stack_info=True)
        except Exception as e:
            log.error('an Exception trace should preceed this msg', exc_info=True)
    div(1,0)
    assert 'an Exception' in th.logged
    div(1,1)
    assert 'the stack' in th.logged

def test_listeners():
    th = setup_logging()
    log = slogging.get_logger()

    called = []
    def log_cb(event_dict):
        called.append(event_dict)

    # activate listener
    slogging.log_listeners.listeners.append(log_cb)
    log.error('test listener', abc='thislistener')
    assert 'thislistener' in th.logged
    r = called.pop()
    assert r == dict(event='test listener', abc='thislistener')

    log.trace('trace is usually filtered', abc='thislistener')
    assert th.logged is None
    assert 'abc' in called.pop()

    # deactivate listener
    slogging.log_listeners.listeners.remove(log_cb)
    log.error('test listener', abc='nolistener')
    assert 'nolistener' in th.logged
    assert not called

def test_logger_names():
    th = setup_logging()
    names = set(['a','b','c'])
    for n in names:
        slogging.get_logger(n)
    assert names.issubset(set(slogging.get_logger_names()))

def test_is_active():
    th = setup_logging()
    log = slogging.get_logger()
    assert not log.is_active('trace')
    assert not log.is_active('debug')
    assert log.is_active('info')
    assert log.is_active('warn')

    # activate w/ listner
    slogging.log_listeners.listeners.append(lambda x:x)
    assert log.is_active('trace')
    slogging.log_listeners.listeners.pop()
    assert not log.is_active('trace')


def test_lazy_log():
    """
    test lacy evaluation of json log data
    e.g.
    class LogState
    class LogMemory
    """

    called_json = []
    called_print = []

    class Expensive(object):
        def __structlog__(self):
            called_json.append(1)
            return 'expensive data preparation'

        def __repr__(self):
            called_print.append(1)
            return 'expensive data preparation'

    th = setup_logging(log_json=True)
    log = slogging.get_logger()
    log.trace('no', data=Expensive())
    assert not called_print
    assert not called_json
    log.info('yes', data=Expensive())
    assert called_json.pop()
    assert not called_print

    th = setup_logging()
    log = slogging.get_logger()
    log.trace('no', data=Expensive())
    assert not called_print
    assert not called_json
    log.info('yes', data=Expensive())
    assert not called_json
    assert called_print.pop()


def test_get_configuration():
    config_string = ':INFO,a:TRACE,a.b:DEBUG'
    log_json = False
    slogging.configure(config_string=config_string, log_json=log_json)
    config = slogging.get_configuration()
    assert config['log_json'] == log_json
    assert set(config['config_string'].split(',')) == set(config_string.split(','))

    log_json = True
    slogging.configure(config_string=config_string, log_json=log_json)
    config = slogging.get_configuration()
    assert config['log_json'] == log_json
    assert set(config['config_string'].split(',')) == set(config_string.split(','))

    # set config differntly
    slogging.configure(config_string=':TRACE', log_json=False)
    config2 = slogging.get_configuration()

    # test whether we get original config
    slogging.configure(**config)
    config = slogging.get_configuration()
    assert config['log_json'] == log_json
    assert set(config['config_string'].split(',')) == set(config_string.split(','))



def test_recorder():
    th = setup_logging()
    log = slogging.get_logger()

    # test info
    recorder = slogging.LogRecorder()
    assert len(slogging.log_listeners.listeners) == 1
    log.info('a', v=1)
    assert th.logged
    r = recorder.pop_records()
    assert r[0] == dict(event='a', v=1)
    assert len(slogging.log_listeners.listeners) == 0

    # test trace
    recorder = slogging.LogRecorder()
    assert len(slogging.log_listeners.listeners) == 1
    log.trace('a', v=1)
    assert not th.logged
    r = recorder.pop_records()
    assert r[0] == dict(event='a', v=1)
    assert len(slogging.log_listeners.listeners) == 0

# examples

def test_howto_use_in_tests():
    # select what you want to see.
    # e.g. TRACE from vm except for pre_state :DEBUG otherwise
    config_string = ':DEBUG,eth.vm:TRACE,vm.pre_state:INFO'
    slogging.configure(config_string=config_string)
    log = slogging.get_logger('tests.logging')
    log.info('test starts')


def test_how_to_use_as_vm_logger():
    """
    don't log until there was an error
    """

    config_string = ':DEBUG,eth.vm:INFO'
    slogging.configure(config_string=config_string)
    log = slogging.get_logger('eth.vm')

    # record all logs
    def run_vm(raise_error=False):
        log.trace('op', pc=1)
        log.trace('op', pc=2)
        if raise_error:
            raise Exception

    recorder = slogging.LogRecorder()
    try:
        run_vm(raise_error=True)
    except:
        log = slogging.get_logger('eth.vm')
        for x in recorder.pop_records():
            log.info(x.pop('event'), **x)


