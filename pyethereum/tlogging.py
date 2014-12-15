
import sys
import json
import time

"""
Requirements:

users want to filter log messages by
severity (e.g. warn, info, debug, trace)
and / or
topic (e.g. p2p, vm)

topical logs may cross module boundaries

lazy logging (i.e. lazy evaluation of expensive log messages)

logs should be consumable by software
"""

#HOWTO: log levels defined by groups


log_level_names = ('critical', 'error', 'warn', 'info', 'debug', 'trace')
log_levels = dict((n, i) for i, n in enumerate(log_level_names))


class LogGroup(object):

    """
    combines multiple logging (to e.g. a topic)
    LogGroups can be nested
    """

    is_active = 0

    def __init__(self, name, *logger_or_groups):
        assert isinstance(name, (str, unicode))
        self.name = name
        self.loggers = []
        self.listeners = []
        for l in logger_or_groups:
            self.add_logger(l)

    def activate(self):
        for l in self.list():
            l.is_active += 1  # loggers can be in multiple groups

    def deactivate(self):
        for l in self.list():
            l.is_active = max(0, l.is_active - 1)

    def add_logger(self, logger_or_group):
        assert isinstance(logger_or_group, (LogGroup, Logger))
        logger_or_group.add_listener(self.log_cb)
        self.loggers.append(logger_or_group)

    def remove_logger(self, logger_or_group):
        assert isinstance(logger_or_group, (LogGroup, Logger))
        logger_or_group.remove_listener(self.log_cb)
        self.loggers.remove(logger_or_group)

    def add_listener(self, cb):
        self.listeners.append(cb)

    def remove_listener(self, cb):
        self.listeners.remove(cb)

    def log_cb(self, logger, name, data):
        for cb in self.listeners:
            cb(logger, name, data)

    def list(self, level=log_level_names[-1]):
        "list all included loggers"
        loggers = []
        for l in self.loggers:
            if isinstance(l, LogGroup):
                loggers.extend(l.list())
            else:
                loggers.append(l)
        return [l for l in loggers if log_levels[l.level] <= log_levels[level]]


class LogManager(object):

    writer = None

    def __init__(self):
        self.loggers = []
        self.groups = []

    def items(self):
        return dict([(l.name, l) for l in self.loggers] + [(g.name, g) for g in self.groups])

    def create(self, name, level='warn'):
        assert name not in self.items().keys()
        l = Logger(name, level)
        self.loggers.append(l)
        return l

    def list(self, level=log_level_names[-1]):
        return [l for l in self.loggers if log_levels[l.level] <= log_levels[level]]

    def group(self, name, *loggers):
        assert name not in self.items().keys()
        g = LogGroup(name, *loggers)
        self.groups.append(g)
        return g

    def list_groups(self):
        return self.groups[:]

    def get(self, name):
        print name
        try:
            return [i for n, i in self.items().items() if n == name][0]
        except IndexError:
            raise KeyError(name)


class LazyLog(object):

    "use for expensive log formattings, func is only called when receiving logger is_active"

    def __init__(self, name, func):
        self.name = name
        self.func = func


class BaseFormatter(object):

    def format(self, logger, event_name, data):
        if isinstance(data, dict):
            items = data.items()
            if logger.kargs_sorting:
                order = dict((k, i) for i, k in enumerate(logger.kargs_sorting))
                items = sorted(items, key=lambda x: order.get(x[0], 1000))
            msg = ", ".join("%s=%s" % (k, v) for k, v in items)
        elif isinstance(data, list):
            msg = ", ".join(map(str, data))
        else:
            msg = str(data)
        return "[%s]\t%s: %s" % (logger.name, event_name.ljust(15), msg)




class tJSONEncoder(json.JSONEncoder):

    def default(self, obj):
        from pyethereum.peer import Peer # FIXME
        if isinstance(obj, Peer):
            return (obj.ip, obj.port)
        #   return repr(obj)
        # Let the base class default method raise the TypeError
        #return json.JSONEncoder.default(self, obj)
        return repr(obj)

class JSONFormatter(object):

    def format(self, logger, event_name, data):
        return tJSONEncoder().encode({logger.name: {event_name: data}, 'ts':time.time()})

class LogWriter(object):

    last = -1

    def __init__(self, formatter, out_fh=sys.stdout):
        self.loggers = []
        self.formatter = formatter
        self.out_fh = out_fh

    def clear(self):
        "removes all loggers"
        for l in self.loggers[:]:
            self.remove_logger(l)

    __del__ = clear

    def add_logger(self, logger_or_group):
        assert isinstance(logger_or_group, (LogGroup, Logger))
        logger_or_group.add_listener(self.log_cb)
        self.loggers.append(logger_or_group)

    def remove_logger(self, logger_or_group):
        assert isinstance(logger_or_group, (LogGroup, Logger))
        logger_or_group.remove_listener(self.log_cb)
        self.loggers.remove(logger_or_group)

    def log_cb(self, logger, event_name, data):
        _ = repr((event_name, data))
        if _ == self.last:
            return # skip same msg if we get it from multiple groups
        self.last = _
        self.out_fh.write(self.formatter.format(logger, event_name, data) + '\n')


class Logger(object):

    listeners = []  # register callbacks here
    kargs_sorting = []  # sort order for formaters
    is_active = 0

    def __init__(self, name, level='warn'):
        self.name = name
        assert level in log_levels.keys(), (level, log_levels.keys())
        self.level = level
        self.listeners = []
        self.kargs_sorting = []

    def __repr__(self):
        return '<Logger(%s, level=%s)' % (self.name, self.level)

    def add_listener(self, cb):
        self.listeners.append(cb)

    def remove_listener(self, cb):
        self.listeners.remove(cb)

    def log(self, name_or_lazylog, *args, **kargs):
        if not self.is_active:
            return
        if isinstance(name_or_lazylog, LazyLog):
            kargs = name_or_lazylog.func()
            event_name = name_or_lazylog.name
        else:
            event_name = name_or_lazylog
        for l in self.listeners:
            l(self, event_name, args or kargs)

    __call__ = log


def configure_logging(logger_names):
    assert isinstance(logger_names, list)
    g = LogGroup('user')
    for name in logger_names:
        g.add_logger(logging.get(name.lower().strip()))
    g.activate()  # can only activate known loggers
    logging.writer.clear()
    logging.writer.add_logger(g)

# default config
logging = LogManager()
logging.writer = LogWriter(BaseFormatter())
logging.writer = LogWriter(JSONFormatter())

log_error = logging.create('error', level='error')
log_info = logging.create('info', level='info')
log_debug = logging.create('debug', level='debug')

# specific logger
log_net_info = logging.create('net_info', level='info')
log_net_debug = logging.create('net_debug', level='debug')
log_packet = logging.create('packet', level='debug')
log_eth = logging.create('wireeth', level='debug')
log_p2p = logging.create('wirep2p', level='debug')
log_packeter = logging.create('packeter', level='debug')
log_synchronizer = logging.create('sync', level='debug')
log_db = logging.create('db', level='debug')
log_miner = logging.create('miner', level='debug')
log_chain_warn = logging.create('chain_warn', level='warn')
log_chain_info = logging.create('chain', level='info')
log_chain_debug = logging.create('chain_debug', level='debug')
log_vm_exit = logging.create('vm_exit', level='debug')
log_vm_op = logging.create('vm_op', level='debug')
log_log = logging.create('log', level='info')
log_tx = logging.create('tx', level='debug')
log_msg = logging.create('msg', level='debug')
log_state = logging.create('state', level='debug')
log_block = logging.create('block', level='debug')
log_state_delta = logging.create('state_delta', level='debug')

log_pb = logging.group('pb', log_tx, log_msg, log_state, log_block)
log_vm = logging.group('vm', log_vm_op, log_vm_exit, log_log)

# default logger
log_basics = logging.group('default', *logging.list(level='info'))

# all logger
log_all = logging.group('all', *logging.list())


# configure log groups here

def all_loggers():
    return logging.items().keys()

if __name__ == '__main__':

    # LogManager keeps track of the logging
    logging = LogManager()

    # create logging for topics (many is good!)
    log_a = logging.create('log_a', level='critical')
    log_b = logging.create('log_b', level='info')
    log_c = logging.create('log_c', level='debug')
    log_d = logging.create('log_d', level='trace')

    # log manager should know about them
    assert log_a in logging.list()

    # logs can be filtered by maximum level
    print 'logging included in level "info"'
    print logging.list(level="info")

    # combine multiple logging in a group
    #
    log_ab = logging.group('log_ab', log_a, log_b)

    # groups can be nested
    #
    log_abc = logging.group('log_abc', log_ab, log_c)

    # loggers need to be activated
    #
    log_abc.activate()

    # groups can list their logging
    #
    assert len(log_abc.list()) == 3
    assert log_abc.list(level='critical')[0] == log_a

    # log manager can list all groups
    assert len(logging.list_groups()) == 2

    # decide on a formatter
    #
    log_formatter = BaseFormatter()

    # create a writer
    #
    log_writer = LogWriter(log_formatter)

    # and add logging
    #
    log_writer.add_logger(log_abc)

    # basic logging
    #
    log_a.log('event', a=1, b=2, c={'aa': 11})

    # object __call__ provides a shortcut
    #
    log_a('event', call_used=True)
    log_c('event c', c=1)

    # lazy evaluation possible, only triggered if logger is_active
    #
    def lazy_cb():
        log_a.log('lazy evaluated', lazy=True)
        return dict(b=2)

    log_b(LazyLog('late evaluated', lazy_cb))

    # log_d was not actived
    #
    log_d('not logged', d=1)

    def not_called():
        raise Exception('not called if there is no listener')
    log_d(LazyLog('not evaluated', not_called))

    if log_d.is_active:
        raise Exception('never called')

    # we can also log strings and lists
    #
    log_a('list', range(10))
    log_a('string', 'test string')

    # logs can be added to multiple writers
    # here using the JSON formatter and writing to StringIO
    import StringIO
    fh = StringIO.StringIO()
    sio_writer = LogWriter(JSONFormatter(), out_fh=fh)
    log_all = logging.group('all', *logging.list())
    log_all.activate()
    sio_writer.add_logger(log_all)
    log_a('json list', range(10))
    log_a('json event', a=1, b=2, c={'aa': 11})
    fh.seek(0)
    print fh.read()
