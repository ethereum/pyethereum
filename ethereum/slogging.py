import structlog
import logging
import sys
import json
import binascii
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


def _trace(self, message, *args, **kws):
    # Yes, logger takes its '*args' as 'args'.
    if self.isEnabledFor(TRACE):
        self._log(TRACE, message, args, **kws)
logging.Logger.trace = _trace
logging.TRACE = TRACE

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
configure()


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
    return sorted(known_loggers, key=lambda x: '' if not x else x)  # initialized at module load get_logger


def get_logger(name=None):
    known_loggers.add(name)
    return structlog.get_logger(name)


# quick debug
def DEBUG(msg, **kargs):
    "temporary logger during development that is always on"
    log = structlog.get_logger('DEBUG')
    log.critical('-' * 20)
    log.critical(msg, **kargs)
