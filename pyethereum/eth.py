#!/usr/bin/env python
import os
import sys
import time
import uuid
import signal
from argparse import ArgumentParser

# this must be called before all other import to enable full qualified import
from common import enable_full_qualified_import
enable_full_qualified_import()

#from pyethereum.utils import data_dir
from pyethereum.utils import default_data_dir
from pyethereum.utils import db_path
from pyethereum.utils import sha3
from pyethereum.signals import config_ready
from pyethereum.tcpserver import tcp_server
from pyethereum.peermanager import peer_manager
from pyethereum.apiserver import api_server
from pyethereum.packeter import Packeter
from pyethereum.chainmanager import chain_manager
from pyethereum.db import DB
import pyethereum.slogging
import pyethereum.config as konfig
from . import __version__


pyethereum.slogging.configure()
log = pyethereum.slogging.get_logger()

try:
    import pyethereum.monkeypatch
    log.critical("Loaded your customizations from monkeypatch.py")
except ImportError, e:
    pass


def parse_arguments():
    config = konfig.get_default_config()
    parser = ArgumentParser(version=__version__)
    parser.add_argument(
        "-l", "--listen",
        dest="listen_port",
        help="<port>  Listen on the given port for incoming"
        " connected (default: 30303).")
    parser.add_argument(
        "-a", "--address",
        dest="coinbase",
        help="Set the coinbase (mining payout) address")
    parser.add_argument(
        "-d", "--data_dir",
        dest="data_dir",
        help="<path>  Load database from path (default: %s)" %
        config.get('misc', 'data_dir'))
    parser.add_argument(
        "-r", "--remote",
        dest="remote_host",
        help="<host> Connect to remote host (default: 207.12.89.180)")
    parser.add_argument(
        "-p", "--port",
        dest="remote_port",
        help="<port> Connect to remote port (default: 30303)")
    parser.add_argument(
        "-m", "--mining",
        dest="mining",
        help="<0 - 100> Percent CPU used for mining 0==off (default: 10)")
    parser.add_argument(
        "-L", "--logging",
        dest="logging",
        help="<logger1:LEVEL,logger2:LEVEL> set the console log for interests"
        " logger1, logger2, etc. Empty loggername means 'default'"
        " loggers inherit the log level of their parent (e.g. 'eth.chain' inherits 'eth'"
        " unless their level is explicitly set)"
        " - available loglevels: ['critical', 'warn', 'info', 'debug', 'trace']"
        " - available loggers: %r" % [x for x in pyethereum.slogging.get_logger_names() if x])
    parser.add_argument(
        "-J", "--log_json",
        dest="log_json",
        help="set to 1 to emit logs as json")
    parser.add_argument(
        "-x", "--peers",
        dest="num_peers",
        help="<number> Attempt to connect to given number of peers"
        "(default: 5)")
    parser.add_argument("-C", "--config",
                        dest="config_file",
                        help="read coniguration")

    return parser.parse_args()


def check_chain_version(config):
    key = '__chain_version__'
    chain_version = str(Packeter.ETHEREUM_PROTOCOL_VERSION)
    db = DB(db_path(config.get('misc', 'data_dir')))
    if not key in db:
        db.put(key, chain_version)
    if db.get(key) != chain_version:
        log.critical('db version mismatch', db_version=db.get(
            key), chain_version=chain_version, db_path=db_path)
        time.sleep(5)


def create_config():
    options = parse_arguments()

    # 1) read the default config at "~/.ethereum"
    config = konfig.read_config()

    # 2) read config from file
    cfg_fn = getattr(options, 'config_file')
    if cfg_fn:
        if not os.path.exists(cfg_fn):
            konfig.read_config(cfg_fn)  # creates default
        config.read(cfg_fn)

    # 3) apply cmd line options to config
    for section in config.sections():
        for a, v in config.items(section):
            if getattr(options, a, None) is not None:
                config.set(section, a, getattr(options, a))
    
    return config


def main():
    log.info('starting', version=__version__)

    config = create_config()
    # configure logging
    config_string = config.get('misc', 'logging') or ':INFO'
    pyethereum.slogging.configure(config_string,
                                  log_json=bool(config.getint('misc', 'log_json')))

    # log config
    log.debug("config ready")
    for section in config.sections():
        for a, v in config.items(section):
            log.debug(section, **{a: v})

    config_ready.send(sender=None, config=config)

    # initialize chain
    check_chain_version(config)

    # P2P TCP SERVER
    try:
        tcp_server.start()
    except IOError as e:
        log.error("Could not start TCP server", error=e)
        sys.exit(1)

    # PEER MANAGER THREAD
    peer_manager.start()

    # CHAIN MANAGER THREAD
    chain_manager.start()

    # API SERVER THREAD
    api_server.start()

    # handle termination signals
    def signal_handler(signum=None, frame=None):
        log.info('Signal handler called', signal=signum)
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
        time.sleep(0.001)

    log.info('exiting')
    peer_manager.join()
    log.debug('main thread finished')

if __name__ == '__main__':
    main()
