#!/usr/bin/env python
import sys
import time
import signal
import ConfigParser
from optparse import OptionParser
import logging
import logging.config

from common import make_pyethereum_avail
make_pyethereum_avail()

from pyethereum.signals import config_ready
from pyethereum.tcpserver import tcp_server
from pyethereum.peermanager import peer_manager
from pyethereum.chainmanager import chain_manager
from pyethereum.apiserver import api_server

logger = logging.getLogger(__name__)


def create_config():

    config = ConfigParser.ConfigParser()
    # set some defaults, which may be overwritten
    config.add_section('network')
    config.set('network', 'listen_host', '0.0.0.0')
    config.set('network', 'listen_port', '30303')
    config.set('network', 'num_peers', '5')
    config.set('network', 'remote_port', '30303')
    config.set('network', 'remote_host', '')
    config.set('network', 'client_id', 'Ethereum(py)/0.0.1')

    config.add_section('api')
    config.set('api', 'listen_host', '127.0.0.1')
    config.set('api', 'listen_port', '30203')

    config.add_section('misc')
    config.set('misc', 'verbosity', '1')
    config.set('misc', 'config_file', None)
    config.set('misc', 'logging', None)

    config.add_section('wallet')

    # NODE_ID == pubkey, needed in order to work with Ethereum(++)
    config.set('wallet', 'pub_key',
               'J\x02U\xfaFs\xfa\xa3\x0f\xc5\xab\xfd<U\x0b\xfd\xbc\r<\x97=5'
               '\xf7&F:\xf8\x1cT\xa02\x81\xcf\xff"\xc5\xf5\x96[8\xacc\x01R'
               '\x98wW\xa3\x17\x82G\x85I\xc3o|\x84\xcbD6\xbay\xd6\xd9')

    usage = "usage: %prog [options]"
    parser = OptionParser(usage=usage,  version="%prog 0.1a")
    parser.add_option(
        "-l", "--listen",
        dest="listen_port",
        default=config.get('network', 'listen_port'),
        help="<port>  Listen on the given port for incoming"
        " connected (default: 30303).")
    parser.add_option(
        "-r", "--remote",
        dest="remote_host",
        help="<host> Connect to remote host"
        " (try: 54.201.28.117 or 54.204.10.41)")
    parser.add_option(
        "-p", "--port",
        dest="remote_port",
        default=config.get('network', 'remote_port'),
        help="<port> Connect to remote port (default: 30303)"
    )
    parser.add_option(
        "-v", "--verbose",
        dest="verbosity",
        default=config.get('misc', 'verbosity'),
        help="<0 - 3>  Set the log verbosity from 0 to 3 (default: 1)")
    parser.add_option(
        "-L", "--logging",
        dest="logging",
        default=config.get('misc', 'logging'),
        help="<logger1:LEVEL,logger2:LEVEL> set the console log level for"
        " logger1, logger2, etc. Empty loggername means root-logger,"
        " e.g. 'pyethereum.wire:DEBUG,:INFO'. Overrides '-v'")
    parser.add_option(
        "-x", "--peers",
        dest="num_peers",
        default=config.get('network', 'num_peers'),
        help="<number> Attempt to connect to given number of peers"
        "(default: 5)")
    parser.add_option("-C", "--config",
                      dest="config_file",
                      help="read coniguration")

    (options, args) = parser.parse_args()

    # set network options
    for attr in ('listen_port', 'remote_host', 'remote_port', 'num_peers'):
        config.set('network', attr, getattr(
            options, attr) or config.get('network', attr))
    # set misc options
    for attr in ('verbosity', 'config_file'):
        config.set(
            'misc', attr, getattr(options, attr) or config.get('misc', attr))

    if len(args) != 0:
        parser.error("wrong number of arguments")
        sys.exit(1)

    if config.get('misc', 'config_file'):
        config.read(config.get('misc', 'config_file'))

    # configure logging
    loggerlevels = getattr(options, 'logging') or ''
    configure_logging(
        loggerlevels, verbosity=config.getint('misc', 'verbosity'))

    return config


def configure_logging(loggerlevels, verbosity=1):
    logconfig = dict(
        version=1,
        disable_existing_loggers=False,
        formatters=dict(
            debug=dict(
                format='[%(asctime)s] %(name)s %(levelname)s %(threadName)s:'
                ' %(message)s'
            ),
            minimal=dict(
                format='%(message)s'
            ),
        ),
        handlers=dict(
            default={
                'level': 'INFO',
                'class': 'logging.StreamHandler',
                'formatter': 'minimal'
            },
            verbose={
                'level': 'DEBUG',
                'class': 'logging.StreamHandler',
                'formatter': 'debug'
            },
        ),
        loggers=dict()
    )

    for loggerlevel in filter(lambda _: ':' in _, loggerlevels.split(',')):
        name, level = loggerlevel.split(':')
        logconfig['loggers'][name] = dict(
            handlers=['verbose'], level=level, propagate=False)

    if len(logconfig['loggers']) == 0:
        logconfig['loggers'][''] = dict(
            handlers=['default'],
            level={0: 'ERROR', 1: 'WARNING', 2: 'INFO', 3: 'DEBUG'}.get(
                verbosity),
            propagate=True)

    logging.config.dictConfig(logconfig)
    logging.debug("logging set up like that: {0}".format(logconfig))


def main():
    config = create_config()
    config_ready.send(sender=config)

    try:
        tcp_server.start()
    except IOError as e:
        logger.error("Could not start TCP server: \"{0}\"".format(str(e)))
        sys.exit(1)

    peer_manager.start()
    chain_manager.start()
    api_server.start()

    # handle termination signals
    def signal_handler(signum=None, frame=None):
        logger.info('Signal handler called with signal {0}'.format(signum))
        peer_manager.stop()
        chain_manager.stop()
        tcp_server.stop()

    for sig in [signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT, signal.SIGINT]:
        signal.signal(sig, signal_handler)

    # connect peer
    if config.get('network', 'remote_host'):
        peer_manager.connect_peer(
            config.get('network', 'remote_host'),
            config.getint('network', 'remote_port'))

    # loop
    while not peer_manager.stopped():
        time.sleep(0.1)
        if len(peer_manager.get_connected_peer_addresses()) > 2:
            chain_manager.bootstrap_blockchain()

    logger.info('exiting')

    peer_manager.join()

    logger.debug('main thread finished')

if __name__ == '__main__':
    main()
