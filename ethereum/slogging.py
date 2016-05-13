import logging
import json
import textwrap
from logging import StreamHandler, Formatter, FileHandler
from ethereum.utils import bcolors, isnumeric


DEFAULT_LOGLEVEL = 'INFO'

JSON_FORMAT = '%(message)s'

PRINT_FORMAT = '%(levelname)s:%(name)s\t%(message)s'
FILE_PREFIX = '%(asctime)s'

TRACE = 5

known_loggers = set()

log_listeners = []


def _inject_into_logger(name, code, namespace=None):
    # This is a hack to fool the logging module into reporting correct source files.
    # It determines the actual source of a logging call by inspecting the stack frame's
    # source file. So we use this `eval(compile())` construct to "inject" our additional
    # methods into the logging module.
    if namespace is None:
        namespace = {}
    eval(
        compile(
            code,
            logging._srcfile,
            'exec'
        ),
        namespace
    )
    setattr(logging.Logger, name, namespace[name])


# Add `trace()` level to Logger
_inject_into_logger(
    'trace',
    textwrap.dedent(
        """\
        def trace(self, msg, *args, **kwargs):
            if self.isEnabledFor(TRACE):
                self._log(TRACE, msg, args, **kwargs)
        """
    ),
    {'TRACE': TRACE}
)
logging.TRACE = TRACE
logging.addLevelName(TRACE, "TRACE")


# Add `DEV()` shortcut to loggers
_inject_into_logger(
    'DEV',
    textwrap.dedent(
        """\
        def DEV(self, msg, *args, **kwargs):
            '''Shortcut to output highlighted log text'''
            kwargs['highlight'] = True
            self.critical(msg, *args, **kwargs)
        """
    )
)


class LogRecorder(object):

    """
    temporarily records all logs, w/o level filtering
    use only once!
    """
    max_capacity = 1000 * 1000  # check we are not forgotten or abused

    def __init__(self, disable_other_handlers=False, log_config=None):
        self._records = []
        log_listeners.append(self._add_log_record)
        self._saved_config = None
        if log_config:
            self._saved_config = get_configuration()
            configure(log_config)
        self._saved_handlers = []
        if disable_other_handlers:
            self._saved_handlers = rootLogger.handlers[:]
            rootLogger.handlers = []

    def pop_records(self):
        # only returns records on the first call
        r = self._records[:]
        self._records = []
        try:
            log_listeners.remove(self._add_log_record)
        except ValueError:
            pass
        if self._saved_config:
            configure(**self._saved_config)
            self._saved_config = None
        if self._saved_handlers:
            rootLogger.handlers = self._saved_handlers[:]
            self._saved_handlers = []
        return r

    def _add_log_record(self, msg):
        self._records.append(msg)
        assert len(self._records) < self.max_capacity


def get_configuration():
    """
    get a configuration (snapshot) that can be used to call configure
    snapshot = get_configuration()
    configure(**snapshot)
    """
    root = getLogger()
    name_levels = [('', logging.getLevelName(root.level))]
    name_levels.extend(
        (name, logging.getLevelName(logger.level))
        for name, logger
        in root.manager.loggerDict.items()
        if hasattr(logger, 'level')
    )

    config_string = ','.join('%s:%s' % x for x in name_levels)

    return dict(config_string=config_string, log_json=SLogger.manager.log_json)


def get_logger_names():
    return sorted(known_loggers, key=lambda x: '' if not x else x)


class BoundLogger(object):

    def __init__(self, logger, context):
        self.logger = logger
        self.context = context

    def bind(self, **kwargs):
        return BoundLogger(self, kwargs)

    def _proxy(self, method_name, *args, **kwargs):
        context = self.context.copy()
        context.update(kwargs)
        return getattr(self.logger, method_name)(*args, **context)

    trace = lambda self, *args, **kwargs: self._proxy('trace', *args, **kwargs)
    debug = lambda self, *args, **kwargs: self._proxy('debug', *args, **kwargs)
    info = lambda self, *args, **kwargs: self._proxy('info', *args, **kwargs)
    warn = warning = lambda self, *args, **kwargs: self._proxy('warning', *args, **kwargs)
    error = lambda self, *args, **kwargs: self._proxy('error', *args, **kwargs)
    exception = lambda self, *args, **kwargs: self._proxy('exception', *args, **kwargs)
    fatal = critical = lambda self, *args, **kwargs: self._proxy('critical', *args, **kwargs)


class SLogger(logging.Logger):

    def __init__(self, name, level=DEFAULT_LOGLEVEL):
        self.warn = self.warning
        super(SLogger, self).__init__(name, level=level)

    @property
    def log_json(self):
        return SLogger.manager.log_json

    def is_active(self, level_name='trace'):
        return self.isEnabledFor(logging._checkLevel(level_name.upper()))

    def format_message(self, msg, kwargs, highlight, level):
        if getattr(self, 'log_json', False):
            message = dict()
            message['event'] = '{}.{}'.format(self.name, msg.lower().replace(' ', '_'))
            message['level'] = logging.getLevelName(level)
            try:
                message.update({
                    k: v if isnumeric(v) or isinstance(v, (float, complex, list, str, dict)) else repr(v)
                    for k, v in kwargs.items()
                })
                msg = json.dumps(message)
            except UnicodeDecodeError:
                message.update({
                    k: v if isnumeric(v) or isinstance(v, (float, complex)) else repr(v)
                    for k, v in kwargs.items()
                })
                msg = json.dumps(message)
        else:
            msg = "{}{} {}{}".format(
                bcolors.WARNING if highlight else "",
                msg,
                " ".join("{}={!s}".format(k, v) for k, v in kwargs.items()),
                bcolors.ENDC if highlight else ""
            )
        return msg

    def bind(self, **kwargs):
        return BoundLogger(self, kwargs)

    def _log(self, level, msg, args, **kwargs):
        exc_info = kwargs.pop('exc_info', None)
        extra = kwargs.pop('extra', {})
        highlight = kwargs.pop('highlight', False)
        extra['kwargs'] = kwargs
        extra['original_msg'] = msg
        msg = self.format_message(msg, kwargs, highlight, level)
        super(SLogger, self)._log(level, msg, args, exc_info, extra)


class RootLogger(SLogger):

    """
    A root logger is not that different to any other logger, except that
    it must have a logging level and there is only one instance of it in
    the hierarchy.
    """

    def __init__(self, level):
        """
        Initialize the logger with the name "root".
        """
        super(RootLogger, self).__init__("root", level)

    def handle(self, record):
        if log_listeners:
            rec_dict = getattr(record, 'kwargs', {}).copy()
            rec_dict['event'] = getattr(record, 'original_msg', "")
            for listener in log_listeners:
                listener(rec_dict)
        super(RootLogger, self).handle(record)


class SManager(logging.Manager):

    def __init__(self, rootnode):
        self.loggerClass = SLogger
        self.log_json = False
        super(SManager, self).__init__(rootnode)

    def getLogger(self, name):
        logging.setLoggerClass(SLogger)
        return super(SManager, self).getLogger(name)

rootLogger = RootLogger(DEFAULT_LOGLEVEL)
SLogger.root = rootLogger
SLogger.manager = SManager(SLogger.root)


def getLogger(name=None):
    """
    Return a logger with the specified name, creating it if necessary.

    If no name is specified, return the root logger.
    """

    if name:
        logger = SLogger.manager.getLogger(name)
        return logger
    else:
        return rootLogger


def configure(config_string=None, log_json=False, log_file=None):
    if not config_string:
        config_string = ":{}".format(DEFAULT_LOGLEVEL)

    if log_json:
        SLogger.manager.log_json = True
        log_format = JSON_FORMAT
    else:
        SLogger.manager.log_json = False
        log_format = PRINT_FORMAT

    if len(rootLogger.handlers) == 0:
        handler = StreamHandler()
        formatter = Formatter(log_format)
        handler.setFormatter(formatter)
        rootLogger.addHandler(handler)
    if log_file:
        if not any(isinstance(hndlr, FileHandler) for hndlr in rootLogger.handlers):
            handler = FileHandler(log_file)
            formatter = Formatter("{} {}".format(FILE_PREFIX, log_format))
            handler.setFormatter(formatter)
            rootLogger.addHandler(handler)

    # Reset logging levels before applying new config below
    for name, logger in SLogger.manager.loggerDict.items():
        if hasattr(logger, 'setLevel'):
            # Guard against `logging.PlaceHolder` instances
            logger.setLevel(logging.NOTSET)
            logger.propagate = True

    for name_levels in config_string.split(','):
        name, _, level = name_levels.partition(':')
        logger = getLogger(name)
        logger.setLevel(level.upper())

configure_logging = configure


def set_level(name, level):
    assert not isinstance(level, int)
    logger = getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))


def get_logger(name=None):
    known_loggers.add(name)
    return getLogger(name)


def DEBUG(msg, *args, **kwargs):
    """temporary logger during development that is always on"""
    logger = getLogger("DEBUG")
    if len(logger.handlers) == 0:
        logger.addHandler(StreamHandler())
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    logger.DEV(msg, *args, **kwargs)
