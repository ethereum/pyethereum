import structlog
import logging
import sys
import json
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


class JSONRenderer(structlog.processors.JSONRenderer):

    "JSON Render which prefixes namespace"

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

def help_make_kws(kws):
    new_kws = {}
    message = ""
    for i in kws:
        if i not in formatter_list:
            print i, "=", kws[i]
            s = " {i}={kwsi}".format(i=i, kwsi=str(kws[i]))
            message += s
        else:
            new_kws[i] = kws[i]
    return new_kws, message

# this function extends standart logging module
def _trace(self, msg, *args, **kwargs):
    # Yes, logger takes its '*args' as 'args'.
    new_kws, new_message = help_make_kws(kwargs)
    msg += new_message

    if self.isEnabledFor(TRACE):
        self._log(TRACE, msg, args, **new_kws)

# this function extends standart logging module
def _info(self, msg, *args, **kwargs):
    # Yes, logger takes its '*args' as 'args'.
    new_kws, new_message = help_make_kws(kwargs)
    msg += new_message

    if self.isEnabledFor(logging.INFO):
        self._log(logging.INFO, msg, args, **new_kws)

def _debug(self, msg, *args, **kwargs):
    new_message = ""
    new_kws, new_message = help_make_kws(kwargs)
    msg += new_message

    if self.isEnabledFor(logging.DEBUG):
        self._log(logging.DEBUG, msg, args, **new_kws)

def _warning(self, msg, *args, **kwargs):
    new_message = ""
    new_kws, new_message = help_make_kws(kwargs)

    if self.isEnabledFor(logging.WARNING):
        self._log(logging.WARNING, msg, args, **new_kws)

def _error(self, msg, *args, **kwargs):
    new_message = ""
    new_kws, new_message = help_make_kws(kwargs)

    if self.isEnabledFor(logging.ERROR):
        self._log(logging.ERROR, msg, args, **new_kws)

def _exception(self, msg, *args, **kwargs):
    """
    Convenience method for logging an ERROR with exception information.
    """
    kwargs['exc_info'] = 1
    _error(msg, *args, **kwargs)

def _critical(self, msg, *args, **kwargs):
    new_message = ""
    new_kws, new_message = help_make_kws(kwargs)

    if self.isEnabledFor(logging.CRITICAL):
        self._log(logging.CRITICAL, msg, args, **new_kws)

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


def set_level(name, level):
    assert not isinstance(level, int)
    logging.getLogger(name).setLevel(getattr(logging, level.upper()))


def configure_loglevels(config_string):
    """
    config_string = ':debug,p2p:info,vm.op:trace'
    """
    assert ':' in config_string
    for name_levels in config_string.split(','):
        name, level = name_levels.split(':')
        set_level(name, level)


def setup_stdlib_logging(level, fmt):
    logging.root = logging.RootLogger(level)
    logging.Logger.root = logging.root
    logging.Logger.manager = logging.Manager(logging.Logger.root)
    stream = sys.stderr
    hdlr = logging.StreamHandler(stream)
    fmt = logging.Formatter(fmt, None)
    hdlr.setFormatter(fmt)
    logging.root.addHandler(hdlr)


def configure(config_string='', log_json=False):
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

configure_logging = configure  # for unambigious imports
# setup default config
#configure()

def configure1(config_string='', log_json=False):
    FORMAT = "%(levelname)s:%(module)s %(asctime)-15s %(message)s"
    logging.basicConfig(level=logging.TRACE, format=FORMAT)
    logging.info('It is configure logging function')

configure1()

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
    def __init__(self, name, level=logging.NOTSET):
        super(ethLogger, self).__init__(name, level=level)

    def is_active(self, level_name='trace'):
        #self.setLevel(getattr(logging, level_name.upper()))
        return True


class RootLogger(ethLogger):
    """
    A root logger is not that different to any other logger, except that
    it must have a logging level and there is only one instance of it in
    the hierarchy.
    """
    def __init__(self, level):
        """
        Initialize the logger with the name "root".
        """
        ethLogger.__init__(self, "root", level)

class ethManager(logging.Manager):
    def __init__(self, rootnode):
        self.loggerClass = ethLogger
        super(ethManager, self).__init__(rootnode)

    def getLogger(self, name):
        logging.setLoggerClass(ethLogger)
        return super(ethManager, self).getLogger(name)

root = RootLogger(logging.WARNING)
ethLogger.root = root
ethLogger.manager = ethManager(ethLogger.root)



def getLogger(name=None):
    """
    Return a logger with the specified name, creating it if necessary.

    If no name is specified, return the root logger.
    """

    if name:
        ethlogger = ethLogger.manager.getLogger(name)
        ethlogger.setLevel(logging.TRACE)
        FORMAT = "%(levelname)s:%(module)s %(asctime)-15s %(message)s"
        logging.basicConfig(format=FORMAT)
        ch = logging.StreamHandler()
        ch.setLevel(logging.TRACE)
        formatter = logging.Formatter(FORMAT)
        ch.setFormatter(formatter)
        ethlogger.addHandler(ch)
        return ethlogger
    else:
        return root
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
    logging.basicConfig(level=logging.DEBUG, format="%(module)s: %(message)s")
    logger.setLevel(logging.DEBUG)
    logger.debug(msg)

