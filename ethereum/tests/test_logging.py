import json
import logging
import logging.handlers
import pytest
from ethereum import slogging


def setup_function(function):
    """ setup any state tied to the execution of the given function.
    Invoked for every test function in the module.
    """
    function.snapshot = slogging.get_configuration()


def teardown_function(function):
    """ teardown any state that was previously setup with a setup_function
    call.
    """
    slogging.configure(**function.snapshot)


@pytest.mark.parametrize('level_name', ['critical', 'error', 'warning', 'info', 'debug', 'trace'])
def test_basic(caplog, level_name):
    slogging.configure(":trace")
    log = slogging.get_logger()
    with caplog.at_level('TRACE'):
        getattr(log, level_name)(level_name)

    assert len(caplog.records) == 1
    assert caplog.records[0].levelname == level_name.upper()
    assert level_name in caplog.records[0].msg


def test_initial_config():
    slogging.getLogger().handlers = []
    slogging.configure()
    assert len(slogging.getLogger().handlers) == 1
    assert isinstance(slogging.getLogger().handlers[0], logging.StreamHandler)


def test_is_active():
    slogging.configure()
    tester = slogging.get_logger('tester')
    assert tester.is_active(level_name='info')
    assert not tester.is_active(level_name='trace')


def test_jsonconfig(caplog):
    slogging.configure(log_json=True)
    log = slogging.get_logger('prefix')
    log.warn('abc', a=1)
    assert json.loads(caplog.records[0].msg) == dict(event='prefix.abc', a=1, level='WARNING')


def test_configuration():
    config_string = ':inFO,a:trace,a.b:debug'
    slogging.configure(config_string=config_string)
    log = slogging.get_logger()
    log_a = slogging.get_logger('a')
    log_a_b = slogging.get_logger('a.b')
    assert log.is_active('info')
    assert not log.is_active('debug')
    assert log_a.is_active('trace')
    assert log_a_b.is_active('debug')
    assert not log_a_b.is_active('trace')


def test_tracebacks(caplog):
    slogging.configure()
    log = slogging.get_logger()

    def div(a, b):
        try:
            _ = a / b
            log.error('heres the stack', stack_info=True)
        except Exception as e:
            log.error('an Exception trace should preceed this msg', exc_info=True)
    div(1, 0)
    assert 'an Exception trace' in caplog.text
    assert 'Traceback' in caplog.text
    div(1, 1)
    assert 'the stack' in caplog.text


def test_listeners(caplog):
    slogging.configure()
    log = slogging.get_logger()

    called = []

    def log_cb(event_dict):
        called.append(event_dict)

    # activate listener
    slogging.log_listeners.append(log_cb)  # Add handlers
    log.error('test listener', abc='thislistener')
    assert 'thislistener' in caplog.text
    r = called.pop()
    assert r == dict(event='test listener', abc='thislistener')

    log.trace('trace is usually filtered', abc='thislistener')  # this handler for function log_cb does not work
    assert "trace is usually filtered" not in caplog.text

    # deactivate listener
    slogging.log_listeners.remove(log_cb)
    log.error('test listener', abc='nolistener')
    assert 'nolistener' in caplog.text
    assert not called


def test_logger_names():
    slogging.configure()
    names = {'a', 'b', 'c'}
    for n in names:
        slogging.get_logger(n)
    assert names.issubset(set(slogging.get_logger_names()))


def test_lazy_log():
    """
    test lacy evaluation of json log data
    e.g.
    class LogState
    class LogMemory
    """

    called_print = []

    class Expensive(object):

        def __repr__(self):
            called_print.append(1)
            return 'expensive data preparation'

    slogging.configure(log_json=True)
    log = slogging.get_logger()
    log.trace('no', data=Expensive())
    assert not called_print
    log.info('yes', data=Expensive())  # !!!!!!!!!!!!!
    assert called_print.pop()


def test_get_configuration():
    root_logger = slogging.getLogger()
    root_logger.manager.loggerDict = {}  # clear old loggers
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


def test_recorder(caplog):
    slogging.configure(log_json=True)
    log = slogging.get_logger()

    # test info
    recorder = slogging.LogRecorder()
    assert len(slogging.log_listeners) == 1
    log.info('a', v=1)
    assert "a" in caplog.text
    r = recorder.pop_records()
    assert r[0] == dict(event='a', v=1)
    assert len(slogging.log_listeners) == 0

    # test trace
    log.setLevel(logging.TRACE)
    recorder = slogging.LogRecorder()
    assert len(slogging.log_listeners) == 1
    log.trace('a', v=2)
    assert '"v": 2' in caplog.text
    r = recorder.pop_records()
    assert r[0] == dict(event='a', v=2)
    assert len(slogging.log_listeners) == 0


def test_howto_use_in_tests():
    # select what you want to see.
    # e.g. TRACE from vm except for pre_state :DEBUG otherwise
    slogging.configure(':DEBUG,eth.vm:TRACE,vm.pre_state:INFO')
    log = slogging.get_logger('tests.logging')
    log.info('test starts')


def test_how_to_use_as_vm_logger():
    """
    don't log until there was an error
    """
    slogging.configure(':DEBUG,eth.vm:INFO')
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


@pytest.mark.parametrize(
    ('logger_name', 'filter', 'should_log'),
    [
        ('a', None, True),
        ('a.a', 'a', True),
        ('a.a', 'a.a', True),
        ('a.a', 'b', False),

    ])
def test_logger_filter(caplog, logger_name, filter, should_log):
    slogging.configure()
    log = slogging.get_logger(logger_name)
    if filter:
        log.addFilter(logging.Filter(filter))
    log.info("testlogmessage", v=1)
    if should_log:
        assert "testlogmessage" in caplog.text
    else:
        assert "testlogmessage" not in caplog.text


def test_bound_logger(caplog):
    slogging.configure(config_string=':trace')
    real_log = slogging.getLogger()

    bound_log_1 = real_log.bind(key1="value1")
    with caplog.at_level(slogging.TRACE):
        bound_log_1.info("test1")
        assert "test1" in caplog.text
        assert 'key1=value1' in caplog.text

    bound_log_2 = bound_log_1.bind(key2="value2")
    with caplog.at_level(slogging.TRACE):
        bound_log_2.info("test2")
        assert "test2" in caplog.text
        assert 'key1=value1' in caplog.text
        assert 'key2=value2' in caplog.text


def test_bound_logger_isolation(caplog):
    """
    Ensure bound loggers don't "contaminate" their parent
    """
    slogging.configure(config_string=':trace')
    real_log = slogging.getLogger()

    bound_log_1 = real_log.bind(key1="value1")
    with caplog.at_level(slogging.TRACE):
        bound_log_1.info("test1")
        records = caplog.records
        assert len(records) == 1
        assert "test1" in records[0].msg
        assert 'key1=value1' in records[0].msg

    with caplog.at_level(slogging.TRACE):
        real_log.info("test2")
        records = caplog.records
        assert len(records) == 2
        assert "test2" in records[1].msg
        assert 'key1=value1' not in records[1].msg


def test_highlight(caplog):
    slogging.configure(log_json=False)
    log = slogging.getLogger()

    log.DEV('testmessage')
    assert "\033[91mtestmessage \033[0m" in caplog.records[0].msg


def test_shortcut_dev_logger(capsys):
    slogging.DEBUG('testmessage')
    out, err = capsys.readouterr()
    assert "\033[91mtestmessage \033[0m" in err


def test_logging_reconfigure():
    config_string = ':WARNING'
    config_string1 = ':DEBUG,eth:INFO'
    config_string2 = ':DEBUG,eth.vm:INFO'
    main_logger = slogging.getLogger()

    slogging.configure(config_string)
    assert len(main_logger.handlers) == 2  # pytest-capturelog adds it's own handler
    slogging.configure(config_string)
    assert len(main_logger.handlers) == 2  # pytest-capturelog adds it's own handler

    eth_logger = slogging.getLogger('eth')
    slogging.configure(config_string1)
    assert len(eth_logger.handlers) == 0
    slogging.configure(config_string1)
    assert len(eth_logger.handlers) == 0

    eth_vm_logger = slogging.getLogger('eth.vm')
    slogging.configure(config_string2)
    assert len(eth_vm_logger.handlers) == 0
    slogging.configure(config_string2)
    assert len(eth_vm_logger.handlers) == 0


@pytest.mark.parametrize(
    ('config', 'logger', 'level'), (
        (":WARNING", "", "WARNING"),
        (":DEBUG,eth:INFO", "", "DEBUG"),
        (":DEBUG,eth:INFO", "eth", "INFO"),
        (":DEBUG,eth:INFO,devp2p:INFO", "devp2p", "INFO"),))
def test_logging_reconfigure_levels(config, logger, level):
    slogging.configure(config)
    assert slogging.getLogger(logger).level == getattr(logging, level)


def test_set_level():
    slogging.set_level('test', 'CRITICAL')
    assert slogging.getLogger('test').level == logging.CRITICAL


@pytest.mark.parametrize(
    ('log_method', ), (
        ('DEV', ),
        ('trace', ),
        ('info', ),
    ))
def test_logging_source_file(caplog, log_method):
    slogging.configure(":trace")
    logger = slogging.getLogger("test")
    getattr(logger, log_method)("testmessage")

    v = caplog.records[0]
    print(v.pathname, v.module, v.name)
    assert caplog.records[0].module == "test_logging"
