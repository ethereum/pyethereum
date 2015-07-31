import structlog
import logging
import sys
import json
from logging.handlers import MemoryHandler
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


class KeyValueRenderer(structlog.processors.KeyValueRenderer):

    """
    Render `event_dict` as a list of ``Key=repr(Value)`` pairs.
    Prefix with event
    """

    def __call__(self, _, __, event_dict):
        msg = event_dict.pop('event', '')
        kvs = ' '.join(k + '=' + hexprint(v) for k, v in self._ordered_items(event_dict))
        return "%s\t%s" % (msg, kvs)


class JSONRenderer():

    "JSON Render which prefixes namespace"

    def __init__(self, **dumps_kw):
        self._dumps_kw = dumps_kw

    def __call__(self, logger, name, event_dict):
        event_dict = dict(event_dict)
        event_dict['event'] = logger.name + '.' + event_dict['event'].lower().replace(' ', '_')
        return json.dumps(event_dict, cls=structlog.processors._JSONFallbackEncoder,
                          **self._dumps_kw)


######## TRACE ##########

class BoundLoggerTrace(structlog.stdlib.BoundLogger):

    "adds trace"

    def trace(self, event=None, **kw):
        """
        Process event and call ``Logger.trace()`` with the result.
        """
        return self._proxy_to_logger('trace', event, **kw)

    def is_active(self, level_name='trace'):
        """
        this is not faster, than logging.
        can be used set flag in vm context
        """
        # any listeners?
        if self._processors and isinstance(self._processors[0], LogListeners) \
                and self._processors[0].listeners:
            return True
        # log level filter
        return self._logger.isEnabledFor(structlog.stdlib._NAME_TO_LEVEL[level_name])


structlog.stdlib.TRACE = TRACE = 5
structlog.stdlib._NAME_TO_LEVEL['trace'] = TRACE
logging.addLevelName(TRACE, "TRACE")

formatter_list = [ 'name', 'levelno', 'levelname', 'pathname', 'filename', 'module',
    'lineno', 'funcName', 'created', 'asctime', 'msecs', 'relativeCreated', 'thread',
    'threadName', 'process', 'message', 'exc_info', 'extra']

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
#FORMAT = "%(levelname)s:%(module)s %(asctime)-15s %(message)s"


def setup_stdlib_logging(level, fmt):
    logging.root = logging.RootLogger(level)
    logging.Logger.root = logging.root
    logging.Logger.manager = logging.Manager(logging.Logger.root)
    stream = sys.stderr
    hdlr = logging.StreamHandler(stream)
    fmt = logging.Formatter(fmt, None)
    hdlr.setFormatter(fmt)
    logging.root.addHandler(hdlr)


def configure_old(config_string='', log_json=False):
    # configure structlog
    processors = [
        log_listeners,  # before level filtering
        structlog.stdlib.filter_by_level,
        structlog.processors.StackInfoRenderer()
    ]
    if log_json:
        processors.append(JSONRenderer(sort_keys=True))
    else:
        processors.extend([
            structlog.processors.ExceptionPrettyPrinter(file=None),
            KeyValueRenderer(sort_keys=True, key_order=None)
        ])
    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=BoundLoggerTrace,
        # later calls on configure() dont have any effect on already cached loggers
        cache_logger_on_first_use=True,
    )
    # configure standard logging
    if log_json:
        format = JSON_FORMAT
    else:
        format = PRINT_FORMAT
    setup_stdlib_logging(DEFAULT_LOGLEVEL, format)
    if config_string:
        configure_loglevels(config_string)

configure_logging = configure_old  # for unambigious imports
# setup default config
#configure()

def get_configuration():
    """
    get a configuration (snapshot) that can be used to call configure
    snapshot = get_configuration()
    configure(**snapshot)
    """
    name_levels = [('', logging.getLevelName(logging.getLogger().level))]
    for name, logger in list(logging.Logger.manager.loggerDict.items()):
        name_levels.append((name, logging.getLevelName(logger.level)))
    config_string = ','.join('%s:%s' % x for x in name_levels)
    struct_root = get_logger().bind()
    log_json = bool([p for p in struct_root._processors if
                     isinstance(p, structlog.processors.JSONRenderer)])
    return dict(config_string=config_string, log_json=log_json)

# helpers
known_loggers = set()  # know to structlog (i.e. maybe not yet initialized w/ logging)


def get_logger_names():
    # logging.Logger.manager.loggerDict.keys() # used ones
    # initialized at module load get_logger
    return sorted(known_loggers, key=lambda x: '' if not x else x)

#----------------------------- from standart logging module width some modifications ----------------------------
class ethLogger(logging.Logger):
    def __init__(self, name, level=DEFAULT_LOGLEVEL):
        super(ethLogger, self).__init__(name, level=level)

    def is_active(self, level_name='trace'):
        return self.isEnabledFor(logging._checkLevel(level_name.upper()))
        #getLogger()
        #self.setLevel(getattr(logging, level_name.upper()))

    def makeRecord(self, name, level, fn, lno, msg, args, exc_info, func=None, extra=None, dict_val=None):
        """
        A factory method which can be overridden in subclasses to create
        specialized LogRecords.
        """
        rv = logging.LogRecord(name, level, fn, lno, msg, args, exc_info, func)
        if extra is not None:
            for key in extra:
                if (key in ["message", "asctime"]) or (key in rv.__dict__):
                    raise KeyError("Attempt to overwrite %r in LogRecord" % key)
                rv.__dict__[key] = extra[key]
        if dict_val:
            rv.dict_val = dict_val
        return rv

    def _log(self, level, msg, args, exc_info=None, extra=None, dict_val=None):
        """
        Low-level logging routine which creates a LogRecord and then calls
        all the handlers of this logger to handle the record.
        """
        if logging._srcfile:
            #IronPython doesn't track Python frames, so findCaller raises an
            #exception on some versions of IronPython. We trap it here so that
            #IronPython can use logging.
            try:
                fn, lno, func = self.findCaller()
            except ValueError:
                fn, lno, func = "(unknown file)", 0, "(unknown function)"
        else:
            fn, lno, func = "(unknown file)", 0, "(unknown function)"
        if exc_info:
            if not isinstance(exc_info, tuple):
                exc_info = sys.exc_info()
        record = self.makeRecord(self.name, level, fn, lno, msg, args, exc_info, func, extra, dict_val)
        self.handle(record)

class RootLogger(ethLogger):
    """
    A root logger is not that different to any other logger, except that
    it must have a logging level and there is only one instance of it in
    the hierarchy.
    """
    def __init__(self, level, log_json=False):
        """
        Initialize the logger with the name "root".
        """
        ethLogger.__init__(self, "root", level)
        self.log_json = False

class ethManager(logging.Manager):
    def __init__(self, rootnode):
        self.loggerClass = ethLogger
        super(ethManager, self).__init__(rootnode)

    def getLogger(self, name):
        logging.setLoggerClass(ethLogger)
        return super(ethManager, self).getLogger(name)

rootLogger = RootLogger(DEFAULT_LOGLEVEL)
ethLogger.root = rootLogger
ethLogger.manager = ethManager(ethLogger.root)

def help_make_kws(kws, name, msg, log_json=False):
    new_kws = {}
    message = ""
    dict_val = {}

    if log_json == True:
        message = {}
        for i in kws:
            if i not in formatter_list:
                print i, "=", kws[i]
                #s = " {i}={kwsi}".format(i=i, kwsi=str(kws[i]))
                #message += s
                message[i]=kws[i]
            else:
                new_kws[i] = kws[i]
    else:
        message = ""
        for i in kws:
            if i not in formatter_list:
                print i, "=", kws[i]
                s = " {i}={kwsi}".format(i=i, kwsi=str(kws[i]))
                message += s
            else:
                new_kws[i] = kws[i]

    for i in kws:
        if i not in formatter_list:
            dict_val[i] = kws[i]
    if name != rootLogger.name:
        msg1 = {'event': "{}.{}".format(name, msg)}
    else:
        msg1 = {'event': "{}".format(msg)}
    dict_val.update(msg1)

    if log_json == True:
        if name != rootLogger.name:
            message1 = {'event': "{}.{}".format(name, msg)}
        else:
            message1 = {'event': "{}".format(msg)}
        message.update(message1)
        msg = json.dumps(message)
    else:
        msg += message

    return new_kws, dict_val, msg

# this function extends standart logging module
def _trace(self, msg, *args, **kwargs):
    # Yes, logger takes its '*args' as 'args'.

    if hasattr(self, "log_json"):
        new_kws, dict_val, new_message = help_make_kws(kwargs, self.name, msg, self.log_json)
    else:
        new_kws, dict_val, new_message = help_make_kws(kwargs, self.name, msg)

    if self.isEnabledFor(TRACE):
        self._log(TRACE, new_message, args, dict_val=dict_val, **new_kws)

# this function extends standart logging module
def _info(self, msg, *args, **kwargs):
    # Yes, logger takes its '*args' as 'args'.
    if hasattr(self, "log_json"):
        new_kws, dict_val, new_message = help_make_kws(kwargs, self.name, msg, self.log_json)
    else:
        new_kws, dict_val, new_message = help_make_kws(kwargs, self.name, msg)
    if self.isEnabledFor(logging.INFO):
        self._log(logging.INFO, new_message, args, dict_val=dict_val, **new_kws)

def _debug(self, msg, *args, **kwargs):
    new_message = ""
    if hasattr(self, "log_json"):
        new_kws, dict_val, new_message = help_make_kws(kwargs, self.name, msg, self.log_json)
    else:
        new_kws, dict_val, new_message = help_make_kws(kwargs, self.name, msg)

    if self.isEnabledFor(logging.DEBUG):
        self._log(logging.DEBUG, new_message, args, dict_val=dict_val, **new_kws)

def _warning(self, msg, *args, **kwargs):
    new_message = ""
    if hasattr(self, "log_json"):
        new_kws, dict_val, new_message = help_make_kws(kwargs, self.name, msg, self.log_json)
    else:
        new_kws, dict_val, new_message = help_make_kws(kwargs, self.name, msg)

    if self.isEnabledFor(logging.WARNING):
        self._log(logging.WARNING, new_message, args, dict_val=dict_val, **new_kws)

def _error(self, msg, *args, **kwargs):
    new_message = ""
    if hasattr(self, "log_json"):
        new_kws, dict_val, new_message = help_make_kws(kwargs, self.name, msg, self.log_json)
    else:
        new_kws, dict_val, new_message = help_make_kws(kwargs, self.name, msg)

    if self.isEnabledFor(logging.ERROR):
        self._log(logging.ERROR, new_message, args, dict_val=dict_val, **new_kws)

def _exception(self, msg, *args, **kwargs):
    """
    Convenience method for logging an ERROR with exception information.
    """
    kwargs['exc_info'] = 1
    _error(msg, *args, **kwargs)

def _critical(self, msg, *args, **kwargs):
    new_message = ""
    if hasattr(self, "log_json"):
        new_kws, dict_val, new_message = help_make_kws(kwargs, self.name, msg, self.log_json)
    else:
        new_kws, dict_val, new_message = help_make_kws(kwargs, self.name, msg)

    if self.isEnabledFor(logging.CRITICAL):
        self._log(logging.CRITICAL, new_message, args, dict_val=dict_val, **new_kws)

logging.Logger.trace = _trace
logging.TRACE = TRACE
logging.Logger.info = _info
logging.Logger.debug = _debug
logging.Logger.warning = _warning
logging.Logger.warn = _warning
logging.Logger.error = _error
logging.Logger.exception = _exception
logging.Logger.critical = _critical
logging.Logger.fatal = _critical


class ExecHandler(logging.Handler):
    def __init__(self):
        super(ExecHandler, self).__init__()

    def emit(self, record):
        for i in log_listeners.listeners:
            i(record.dict_val)


def getLogger(name=None):
    """
    Return a logger with the specified name, creating it if necessary.

    If no name is specified, return the root logger.
    """

    if name:
        ethlogger = ethLogger.manager.getLogger(name)
        ethlogger.log_json = rootLogger.log_json
        #ethlogger.setLevel(DEFAULT_LOGLEVEL)
        #FORMAT = "%(levelname)s:%(module)s %(asctime)-15s %(message)s"
        #logging.basicConfig(format=FORMAT)
        # add stream handler

        #ch = logging.StreamHandler()
        #ch.setLevel(DEFAULT_LOGLEVEL)
        #formatter = logging.Formatter(FORMAT)
        #ch.setFormatter(formatter)
        #ethlogger.addHandler(ch)

        #mh = MemoryHandler(10000)
        #mh.setLevel(DEFAULT_LOGLEVEL)
        #mh.setFormatter(FORMAT)
        #ethlogger.addHandler(mh)

        #for h in logging.getLogger().handlers: # add root handlers into
            #for i in ethLogger.getLogger(name).handlers:
        #    ethlogger.addHandler(h)
        return ethlogger
    else:
        return rootLogger

def set_level(name, level):
    assert not isinstance(level, int)
    #logging.getLogger(name).setLevel(getattr(logging, level.upper()))
    logger = getLogger(name)
    logger.handlers = []
    logger.setLevel(getattr(logging, level.upper()))
    ch = logging.StreamHandler()
    #if ch not in ethlogger.root.handlers:
    ch.setLevel(getattr(logging, level.upper()))
    formatter = logging.Formatter(PRINT_FORMAT)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    eh = ExecHandler()
    eh.setLevel(getattr(logging, level.upper()))
    logger.addHandler(eh)


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
    #setup_stdlib_logging(DEFAULT_LOGLEVEL, format)

    logging.basicConfig(format=format, level=DEFAULT_LOGLEVEL) # work only first time
    ethlogger = getLogger()
    #ethlogger.setLevel(DEFAULT_LOGLEVEL)

    if config_string:
        configure_loglevels(config_string)

configure()

#----------------------------- / from standart logging module width some modifications ----------------------------
def get_logger(name=None):
    known_loggers.add(name)
    return getLogger(name)
    #return structlog.get_logger(name)


# quick debug
def DEBUG(msg, **kargs):
    "temporary logger during development that is always on"
    #log = structlog.get_logger('DEBUG')
    #log.critical('-' * 20)
    #log.critical(msg, **kargs)
    logger = logging.getLogger('DEBUG')
    logger.setLevel(logging.DEBUG)
    logger.debug(msg)

