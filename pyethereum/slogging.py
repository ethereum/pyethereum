import structlog
import logging
import sys
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

class KeyValueRenderer(structlog.processors.KeyValueRenderer):
    """
    Render `event_dict` as a list of ``Key=repr(Value)`` pairs.
    Prefix with event
    """
    def __call__(self, _, __, event_dict):
        msg = event_dict.pop('event','')
        kvs = ' '.join(k + '=' + repr(v) for k, v in self._ordered_items(event_dict))
        return "'%s':\t%s" % (msg, kvs)


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
        return self._logger.isEnabledFor(structlog.stdlib._nameToLevel[level_name])


structlog.stdlib.TRACE = TRACE = 5
structlog.stdlib._nameToLevel['trace'] = TRACE
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
        for l in self.listeners:
            l(event_dict)
        return event_dict

log_listeners = LogListeners()


### configure #####################

DEFAULT_LOGLEVEL = logging.INFO
JSON_FORMAT='%(message)s'
PRINT_FORMAT='%(levelname)-8s %(name)-12s %(message)s'

def configure_loglevels(config_string):
    """
    config_string = ':debug,p2p:info,vm.op:trace'
    """
    assert ':' in config_string
    for name_levels in config_string.split(','):
        name, level = name_levels.split(':')
        logging.getLogger(name).setLevel(getattr(logging, level.upper()))


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
    processors=[
        log_listeners, # before level filtering
        structlog.stdlib.filter_by_level,
        structlog.processors.StackInfoRenderer()
        ]
    if log_json:
        processors.append(structlog.processors.JSONRenderer(sort_keys=True))
    else:
        processors.extend([
            structlog.processors.ExceptionPrettyPrinter(file=None),
            KeyValueRenderer(sort_keys=True, key_order=None)
        ])
    structlog.configure(
        processors = processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=BoundLoggerTrace,
        cache_logger_on_first_use=True, # later calls on configure() dont have any effect on already cached loggers
        )
    # configure standard logging
    if log_json:
        format=JSON_FORMAT
    else:
        format=PRINT_FORMAT
    setup_stdlib_logging(DEFAULT_LOGLEVEL, format)
    if config_string:
        configure_loglevels(config_string)

### helpers

def get_logger_names():
    return sorted(logging.Logger.manager.loggerDict.keys())

def get_logger(name=None):
    return structlog.get_logger(name)


####### quick debug

def DEBUG(msg, **kargs):
    "temporary logger during development that is always on"
    log = structlog.get_logger('DEBUG')
    log.critical('-'*20)
    log.critical(msg, **kargs)
