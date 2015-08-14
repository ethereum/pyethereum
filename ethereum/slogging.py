import logging
import json
import re

"""
See test_logging.py for examples

Basic usage:
log = get_logger('eth.vm.op')
log.trace('event name', some=data)

Use Namespaces for components and subprotocols
net
net.handshake
net.frames
p2p.peer
p2p.peermanager
eth.vm
eth.vm.op
eth.vm.mem
eth.chain
eth.chain.new_block
"""
#!---------------

FORMAT = "%(levelname)s:%(module)s %(asctime)-15s %(message)s"

def hexprint(x):
    return repr(x)

# add level trace into logging
TRACE = 5
logging.addLevelName(TRACE, "TRACE")
logging.TRACE = TRACE


formatter_set = frozenset(['name', 'levelno', 'levelname', 'pathname', 'filename', 'module',
    'lineno', 'funcName', 'created', 'asctime', 'msecs', 'relativeCreated', 'thread',
    'threadName', 'process', 'message', 'exc_info', 'extra'])

######### listeners ###############


class LogListeners(object):

    """
    allow to register listeners
    """

    def __init__(self):
        self.listeners = []

    def __call__(self, logger, name, event_dict):
        #raise Exception
        e = dict(event_dict)
        for l in self.listeners:
            l(e)
        return event_dict

log_listeners = LogListeners()


class LogRecorder(object):

    """
    temporarily records all logs, w/o level filtering
    use only once!
    """
    max_capacity = 1000 * 1000  # check we are not forgotten or abused

    def __init__(self):
        self._records = []
        log_listeners.listeners.append(self.add_log)

    def add_log(self, msg):
        self._records.append(msg)
        assert len(self._records) < self.max_capacity

    def pop_records(self):
        # can only be called once
        r = self._records[:]
        self._records = None
        log_listeners.listeners.remove(self.add_log)
        return r

### configure #####################

DEFAULT_LOGLEVEL = logging.INFO
JSON_FORMAT = '%(message)s'
PRINT_FORMAT = '%(levelname)s:%(name)s\t%(message)s'


def get_configuration():
    """
    get a configuration (snapshot) that can be used to call configure
    snapshot = get_configuration()
    configure(**snapshot)
    """
    rootLogger = getLogger()
    name_levels = [('', logging.getLevelName(rootLogger.level))]

    for name, logger in list(rootLogger.manager.loggerDict.items()):
        name_levels.append((name, logging.getLevelName(logger.level)))
    config_string = ','.join('%s:%s' % x for x in name_levels)

    return dict(config_string=config_string, log_json=rootLogger.log_json)

# helpers
known_loggers = set()  # know to structlog (i.e. maybe not yet initialized w/ logging)


def get_logger_names():
    # logging.Logger.manager.loggerDict.keys() # used ones
    # initialized at module load get_logger
    return sorted(known_loggers, key=lambda x: '' if not x else x)

#----------------------------- from standart logging module with some modifications ----------------------------
def bind_decorator(fun):
    def wrapper(self, msg, *args, **kwargs):
        if kwargs:
            kwargs.update(**self.context_head)
            kwargs.update(**self.context_bind)
        fun(self, msg, *args, **kwargs)
    return wrapper

class EthLogger(logging.Logger):
    def __init__(self, name, level=DEFAULT_LOGLEVEL):
        self.context_head = {}
        self.context_bind = {}
        self.warn = self.warning
        super(EthLogger, self).__init__(name, level=level)

    def is_active(self, level_name='trace'):
        return self.isEnabledFor(logging._checkLevel(level_name.upper()))

    def help_make_kws(self, kws, name, msg, log_json=False):
        """
        The function separate standart logging from  arbitrary log parameters
        """
        new_kws = {}
        message = None

        if log_json:
            message = {}
            for i in kws:
                if i not in formatter_set:  # levelno, asctime......
                    if type(kws[i]) not in (int, long, float, complex):
                        message[i] = repr(kws[i])
                    else:
                        message[i] = kws[i]
                else:
                    new_kws[i] = kws[i]

            if name != rootLogger.name:
                message1 = {'event': "{}.{}".format(name, msg)}
            else:
                message1 = {'event': "{}".format(msg)}
            message.update(message1)
            msg = json.dumps(message)
        else:
            chunks = []
            for i in kws:
                if i not in formatter_set:
                    chunks.append(" {i}={kwsi}".format(i=i, kwsi=str(kws[i])))
                else:
                    new_kws[i] = kws[i]
            message = ''.join(chunks)
            msg += message

        return new_kws, msg

    def bind(self, **kwargs):
        for i in kwargs:
            if not len(self.context_head):
                self.context_head[i] = kwargs[i]
            else:
                self.context_bind[i] = kwargs[i]
        return self

    # this function extends standart logging module
    @bind_decorator
    def trace(self, msg, *args, **kwargs):
        # Yes, logger takes its '*args' as 'args'.

        if self.isEnabledFor(TRACE):
            new_kws, new_message = self.help_make_kws(kwargs, self.name, msg, getattr(self, "log_json", False))
            self._log(TRACE, new_message, args, **new_kws)

    # this function extends standart logging module
    @bind_decorator
    def info(self, msg, *args, **kwargs):
        # Yes, logger takes its '*args' as 'args'.
        if self.isEnabledFor(logging.INFO):
            new_kws, new_message = self.help_make_kws(kwargs, self.name, msg, getattr(self, "log_json", False) )
            self._log(logging.INFO, new_message, args, **new_kws)

    @bind_decorator
    def debug(self, msg, *args, **kwargs):
        if self.isEnabledFor(logging.DEBUG):
            new_kws, new_message = self.help_make_kws(kwargs, self.name, msg, getattr(self, "log_json", False) )
            self._log(logging.DEBUG, new_message, args, **new_kws)

    @bind_decorator
    def warning(self, msg, *args, **kwargs):
        new_message = ""
        if self.isEnabledFor(logging.WARNING):
            new_kws, new_message = self.help_make_kws(kwargs, self.name, msg, getattr(self, "log_json", False))
            self._log(logging.WARNING, new_message, args, **new_kws)

    @bind_decorator
    def error(self, msg, *args, **kwargs):
        new_message = ""
        if self.isEnabledFor(logging.ERROR):
            new_kws, new_message = self.help_make_kws(kwargs, self.name, msg, getattr(self, "log_json", False))
            self._log(logging.ERROR, new_message, args, **new_kws)

    @bind_decorator
    def exception(self, msg, *args, **kwargs):
        """
        Convenience method for logging an ERROR with exception information.
        """
        kwargs['exc_info'] = 1
        self.error(msg, *args, **kwargs)

    @bind_decorator
    def critical(self, msg, *args, **kwargs):
        new_message = ""
        if self.isEnabledFor(logging.CRITICAL):
            new_kws, new_message = self.help_make_kws(kwargs, self.name, msg, getattr(self, "log_json", False))
            self._log(logging.CRITICAL, new_message, args, **new_kws)

class RootLogger(EthLogger):
    """
    A root logger is not that different to any other logger, except that
    it must have a logging level and there is only one instance of it in
    the hierarchy.
    """
    def __init__(self, level):
        """
        Initialize the logger with the name "root".
        """
        EthLogger.__init__(self, "root", level)
        self.log_json = False

class EthManager(logging.Manager):
    def __init__(self, rootnode):
        self.context_head_key = None # head key for bind decorator
        self.context_bind = {} # dict for bind decorator
        self.loggerClass = EthLogger
        super(EthManager, self).__init__(rootnode)

    def getLogger(self, name):
        logging.setLoggerClass(EthLogger)
        return super(EthManager, self).getLogger(name)

rootLogger = RootLogger(DEFAULT_LOGLEVEL)
EthLogger.root = rootLogger
EthLogger.manager = EthManager(EthLogger.root)

"""
logging.Logger.trace = _trace
logging.Logger.info = _info
logging.Logger.debug = _debug
logging.Logger.warning = _warning
logging.Logger.warn = _warning
logging.Logger.error = _error
logging.Logger.exception = _exception
logging.Logger.critical = _critical
logging.Logger.fatal = _critical
"""

class ExecHandler(logging.Handler):
    def __init__(self, log_json=False):
        super(ExecHandler, self).__init__()
        self.log_json = log_json

    def emit(self, record):
        msg = record.msg
        d_keys_val = {}
        for lstn in log_listeners.listeners:
            if self.log_json:
                d_keys_val = json.loads(record.msg)
            else:
                for i in re.findall(r'(\w+=\w+)', record.msg):
                    k,v = i.split("=")
                    d_keys_val[k] = v
                    msg=msg.replace(i, "")
                d_keys_val['event'] = msg[:-1]
            lstn(d_keys_val)

#----------------------------- / from standart logging module with some modifications ----------------------------

def getLogger(name=None):
    """
    Return a logger with the specified name, creating it if necessary.

    If no name is specified, return the root logger.
    """

    if name:
        ethlogger = EthLogger.manager.getLogger(name)
        ethlogger.log_json = rootLogger.log_json
        return ethlogger
    else:
        return rootLogger

def set_level(name, level):
    assert not isinstance(level, int)
    #logging.getLogger(name).setLevel(getattr(logging, level.upper()))
    logger = getLogger(name)
    #logger.handlers = []
    logger.setLevel(getattr(logging, level.upper()))
    ch = logging.StreamHandler()
    #if ch not in ethlogger.root.handlers:
    ch.setLevel(getattr(logging, level.upper()))
    formatter = logging.Formatter(PRINT_FORMAT)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    #exec_handler = ExecHandler()
    #exec_handler.setLevel(getattr(logging, level.upper()))
    #exec_handler.setLevel(TRACE)
    #logger.addHandler(exec_handler)


def configure_loglevels(config_string):
    """
    config_string = ':debug,p2p:info,vm.op:trace'
    """
    assert ':' in config_string
    for name_levels in config_string.split(','):
        name, level = name_levels.split(':')
        set_level(name, level)

def configure(config_string='', log_json=False):
    if log_json:
        format = JSON_FORMAT
        rootLogger.log_json = True
    else:
        format = PRINT_FORMAT
        rootLogger.log_json = False

    logging.basicConfig(format=format, level=DEFAULT_LOGLEVEL) # work only first time
    ethlogger = getLogger()

    if config_string:
        configure_loglevels(config_string)

configure_logging = configure
configure()

def get_logger(name=None):
    known_loggers.add(name)
    return getLogger(name)
    #return structlog.get_logger(name)


def checkLevel(loghandler, level):
    if logging._checkLevel(loghandler.level) == logging._checkLevel(level.upper()):
        return True
# quick debug
def DEBUG(msg, **kargs):
    "temporary logger during development that is always on"
    logger = logging.getLogger('DEBUG')
    logger.setLevel(logging.DEBUG)
    logger.debug(msg)
