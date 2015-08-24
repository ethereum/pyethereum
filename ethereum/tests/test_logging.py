import json
import logging
import logging.handlers
import ethereum.slogging as slogging


class TestHandler(logging.handlers.BufferingHandler):

    def __init__(self):
        logging.Handler.__init__(self)
        self.capacity = 10000
        self.buffer = []

    @property
    def logged(self):
        # returns just the message part (no formatting)
        if len(self.buffer):
            msg = self.buffer.pop().getMessage()
            return msg
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
    ethlogger = slogging.getLogger()
    ethlogger.handlers = [th]
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

def test_baseconfig2():
    # test loglevels
    th = setup_logging(':info,p2p.discovery:debug,p2p.peer:debug,p2p:warn,eth:debug,eth.chain.tx:info')
    root = slogging.get_logger()
    assert th.does_log(root.error)
    assert th.does_log(root.info)
    assert not th.does_log(root.debug)
    p2p_discovery = slogging.get_logger('p2p.discovery')
    assert th.does_log(p2p_discovery.error)
    assert th.does_log(p2p_discovery.info)
    assert th.does_log(p2p_discovery.debug)
    p2p_peer = slogging.get_logger('p2p.peer')
    assert th.does_log(p2p_peer.error)
    assert th.does_log(p2p_peer.info)
    assert th.does_log(p2p_peer.debug)
    p2p = slogging.get_logger('p2p')
    assert th.does_log(p2p.error)
    assert th.does_log(p2p.warn)
    assert th.does_log(p2p.warning)
    assert not th.does_log(p2p.info)
    assert not th.does_log(p2p.debug)
    eth = slogging.get_logger('eth')
    assert th.does_log(eth.error)
    assert th.does_log(eth.warn)
    assert th.does_log(eth.warning)
    assert th.does_log(eth.info)
    assert th.does_log(eth.debug)
    eth_chain_tx = slogging.get_logger('eth.chain.tx')
    assert th.does_log(eth_chain_tx.error)
    assert th.does_log(eth_chain_tx.warn)
    assert th.does_log(eth_chain_tx.warning)
    assert th.does_log(eth_chain_tx.info)
    assert not th.does_log(eth_chain_tx.debug)

def test_is_active2():
    setup_logging(':info')
    tester = slogging.get_logger('tester')
    assert tester.is_active(level_name='info')
    assert not tester.is_active(level_name='trace')


def test_lvl_trace():
    config_string = ':trace'
    th = setup_logging(config_string=config_string)
    log = slogging.get_logger()
    assert th.does_log(log.debug)
    assert th.does_log(log.trace)

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

    def div(a, b):
        try:
            r = a / b
            log.error('heres the stack', stack_info=True)
        except Exception as e:
            log.error('an Exception trace should preceed this msg', exc_info=True)
    div(1, 0)
    assert 'an Exception' in th.logged
    div(1, 1)
    assert 'the stack' in th.logged


def test_listeners():
    th = setup_logging()
    log = slogging.get_logger()

    called = []

    def log_cb(event_dict):
        called.append(event_dict)

    # handler for handling listiners
    exec_handler = slogging.ExecHandler()
    exec_handler.setLevel(logging.TRACE)
    log.addHandler(exec_handler)

    # activate listener
    slogging.log_listeners.listeners.append(log_cb) # Add handlers
    log.error('test listener', abc='thislistener')
    assert 'thislistener' in th.logged
    r = called.pop()
    assert r == dict(event='test listener', abc='thislistener')

    log.trace('trace is usually filtered', abc='thislistener') # this handler for function log_cb does not work
    assert th.logged is None

    # deactivate listener
    slogging.log_listeners.listeners.remove(log_cb)
    log.error('test listener', abc='nolistener')
    assert 'nolistener' in th.logged
    assert not called


def test_logger_names():
    th = setup_logging()
    names = set(['a', 'b', 'c'])
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
    slogging.log_listeners.listeners.append(lambda x: x)

    exec_handler = slogging.ExecHandler()
    exec_handler.setLevel(logging.TRACE)
    log.addHandler(exec_handler)

    for i in log.handlers:
        if isinstance(i, slogging.ExecHandler):
            i.setLevel(logging.TRACE)
            exechandler = i
    assert slogging.checkLevel(exechandler, 'trace')
    slogging.log_listeners.listeners.pop()
    assert not log.is_active('trace')


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

    th = setup_logging(log_json=True)
    log = slogging.get_logger()
    log.trace('no', data=Expensive())
    assert not called_print
    log.info('yes', data=Expensive()) # !!!!!!!!!!!!!
    assert called_print.pop()


def test_get_configuration():
    root_logger = slogging.getLogger()
    root_logger.manager.loggerDict = {} # clear old loggers
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
    th = setup_logging(log_json=True)
    log = slogging.get_logger()

    exec_handler = slogging.ExecHandler(log_json=log.log_json)
    exec_handler.setLevel(logging.TRACE)
    log.addHandler(exec_handler)

    # test info
    recorder = slogging.LogRecorder()
    assert len(slogging.log_listeners.listeners) == 1
    log.info('a', v=1)
    assert th.logged
    r = recorder.pop_records()
    assert r[0] == dict(event='a', v=1)
    assert len(slogging.log_listeners.listeners) == 0

    # test trace
    log.setLevel(logging.TRACE)
    recorder = slogging.LogRecorder()
    assert len(slogging.log_listeners.listeners) == 1
    log.trace('a', v=1)
    assert th.logged
    r = recorder.pop_records()
    assert r[0] == dict(event='a', v=1)
    assert len(slogging.log_listeners.listeners) == 0


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


def test_cleanup():
    config_string = ':debug'
    slogging.configure(config_string=config_string)

def test_logger_filter():
    th = setup_logging()
    log_a = slogging.get_logger("a")
    log_a.info("log_a", v=1)
    assert "log_a" in th.logged

    log_a_a = slogging.get_logger("a.a")
    log_a_a.info("log_a_a", v=1)
    assert "log_a_a" in th.logged

    log_a.addFilter(logging.Filter("log_a"))
    log_a.info("log", v=1)
    assert not th.logged
    log_a_a.info("log_a_a", v=1)
    assert th.logged

    log_a.removeFilter("log_a")
    log_a.addFilter("log_a_a")
    log_a.info("log_a mes", v=1)
    assert not th.logged
    log_a_a.info("log_a_a mes", v=1)
    assert "log_a_a mes" in th.logged

class TestFilter(logging.Filter):
    """
    This is test class for filter record in logger
    """
    def filter(self, record):
        if "filtering!" in record.msg:
            return True
        else:
            return False


def test_logger_filter_records():
    """
    message has record if add TestFilter and record have msg "not filter!"
    """

    th = setup_logging()
    log_a = slogging.get_logger("a")
    log_a.filters = []

    # add exechandler
    exec_handler = slogging.ExecHandler()
    log_a.addHandler(exec_handler)

    #add filter
    f = TestFilter()
    log_a.addFilter(f)

    called = []
    def log_cb(event_dict):
        called.append(event_dict)

    slogging.log_listeners.listeners.append(log_cb)
    log_a.info("log_a", a=11, b=22)
    assert not called
    log_a.info("log_a filtering! ", a=1, b=2)
    assert called.pop()


try:
    unicode
    _unicode = True
except NameError:
    _unicode = False
records = []
def helper_emit_stream_handler(self, record):
    """
    Emit a record.

    If a formatter is specified, it is used to format the record.
    The record is then written to the stream with a trailing newline.  If
    exception information is present, it is formatted using
    traceback.print_exception and appended to the stream.  If the stream
    has an 'encoding' attribute, it is used to determine how to do the
    output to the stream.
    """

    records.append(record)

    try:
        msg = self.format(record)
        stream = self.stream
        fs = "%s\n"
        if not _unicode: #if no unicode support...
            stream.write(fs % msg)
        else:
            try:
                if (isinstance(msg, unicode) and
                    getattr(stream, 'encoding', None)):
                    ufs = u'%s\n'
                    try:
                        stream.write(ufs % msg)
                    except UnicodeEncodeError:
                        #Printing to terminals sometimes fails. For example,
                        #with an encoding of 'cp1251', the above write will
                        #work if written to a stream opened or wrapped by
                        #the codecs module, but fail when writing to a
                        #terminal even when the codepage is set to cp1251.
                        #An extra encoding step seems to be needed.
                        stream.write((ufs % msg).encode(stream.encoding))
                else:
                    stream.write(fs % msg)
            except UnicodeError:
                stream.write(fs % msg.encode("UTF-8"))
        self.flush()
    except (KeyboardInterrupt, SystemExit):
        raise
    except:
        self.handleError(record)

def standart_logging():
    """
    Test stndart loggin
    2 handlers: basic and stream handler
    """
    root_logger = logging.getLogger()
    root_logger.handlers = [] # clear handlers
    stream_handler = logging.StreamHandler()
    logging.StreamHandler.emit = helper_emit_stream_handler # Substitute function for test handlers with formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    test_handler = TestHandler()
    root_logger.addHandler(test_handler)
    root_logger.info("standart logging")
    record = records.pop()
    assert 'root' in record.name
    assert 'INFO' in record.levelname
    assert 'standart logging' in record.msg

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
    log.error('nice', a=3, b=2)
    l = th.logged
    assert 'a=3' in l and 'b=2' in l

def test_count_logging_handlers():
    config_string = ':WARNING'
    config_string1 = ':DEBUG,eth:INFO'
    config_string2 = ':DEBUG,eth.vm:INFO'
    main_logger = slogging.getLogger()
    # check main logger
    slogging.configure(config_string)
    assert len(main_logger.handlers) == 1
    slogging.configure(config_string)
    assert len(main_logger.handlers) == 1

    # check named logger
    eth_logger = slogging.getLogger('eth')
    slogging.configure(config_string1)
    assert len(eth_logger.handlers) == 1
    slogging.configure(config_string1)
    assert len(eth_logger.handlers) == 1

    # check child of named logger
    eth_vm_logger = slogging.getLogger('eth.vm')
    slogging.configure(config_string2)
    assert len(eth_vm_logger.handlers) == 1
    slogging.configure(config_string2)
    assert len(eth_vm_logger.handlers) == 1

if __name__ == '__main__':
    pass