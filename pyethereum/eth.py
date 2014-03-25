#!/usr/bin/env python
import sys
import time
import signal
import ConfigParser
from optparse import OptionParser
import logging
from p2pnet import TcpServer
from p2pnet import PeerManager

logger = logging.getLogger(__name__)

def create_config():

    config = ConfigParser.ConfigParser()
    # set some defaults, which may be overwritten
    config.add_section('network')
    config.set('network', 'listen_host', 'localhost')
    config.set('network', 'listen_port', '30303')
    config.set('network', 'num_peers', '5')
    config.set('network', 'remote_port', '30303')
    config.set('network', 'remote_host', '')

    config.add_section('misc')
    config.set('misc', 'verbosity', '1')
    config.set('misc', 'config_file', None)

    usage = "usage: %prog [options]"
    parser = OptionParser(usage=usage,  version="%prog 0.1a")
    parser.add_option("-l", "--listen",
                      dest="listen_port",
                      default=config.get('network', 'listen_port'),
                      help="<port>  Listen on the given port for incoming connected (default: 30303)."
                      )
    parser.add_option("-r", "--remote",
                      dest="remote_host",
                      help="<host> Connect to remote host"
                      )
    parser.add_option("-p", "--port",
                      dest="remote_port",
                      default=config.get('network', 'remote_port'),
                      help="<port> Connect to remote port (default: 30303)"
                      )
    parser.add_option("-v", "--verbose",
                      dest="verbosity",
                      default=config.get('misc', 'verbosity'),
                      help="<0 - 9>  Set the log verbosity from 0 to 9 (default: 1)")
    parser.add_option("-x", "--peers",
                      dest="num_peers",
                      default=config.get('network', 'num_peers'),
                      help="<number>  Attempt to connect to given number of peers (default: 5)")
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

    return config


def main():
    config = create_config()

    # Setup logging according to config:
    log_level = config.getint('misc', 'verbosity')
    if log_level == 2:
        logging.basicConfig(format='%(message)s', level=logging.WARN)
    elif log_level > 2:
        logging.basicConfig(
            format='[%(asctime)s] %(name)s %(levelname)s %(threadName)s: %(message)s', level=logging.DEBUG)
    else:
        logging.basicConfig(format='%(message)s', level=logging.INFO)

    # peer manager
    peer_manager = PeerManager(config=config)

    # start tcp server
    try:
        tcp_server = TcpServer(peer_manager,
                               config.get('network', 'listen_host'),
                               config.getint('network', 'listen_port'))
    except IOError as e:
        logger.error("Could not start TCP server: \"{0}\"".format(str(e)))
        sys.exit(1)

    peer_manager.local_address = (tcp_server.ip, tcp_server.port)
    tcp_server.start()
    peer_manager.start()

    # handle termination signals
    def signal_handler(signum=None, frame=None):
        logger.info('Signal handler called with signal {0}'.format(signum))
        peer_manager.stop()
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

    logger.info('extiting')
    # tcp_server.join() # does not work!
    peer_manager.join()

if __name__ == '__main__':
    main()