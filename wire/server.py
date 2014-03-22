#!/usr/bin/env python
import logging
import sys
import os
import time
import ConfigParser
from processor import Dispatcher, Processor, print_log
from tcp import TcpServer


logging.basicConfig()

def create_config():
    config = ConfigParser.ConfigParser()
    # set some defaults, which will be overwritten by the config file
    config.add_section('server')
    config.set('server', 'host', 'localhost')
    config.set('server', 'port', '30303')
    config.add_section('connect')
    config.set('connect', 'host', '')
    config.set('connect', 'port', '30303')
    config.read([os.path.join(p, '.pyetherum.conf') for p in ('~/', '')])

    if len(sys.argv) > 1:
        config.read(sys.argv[1]) # read optional
        print_log('reading config %s' % sys.argv[1])

    return config


class EtherProcessor(Processor):
    def __init__(self, config, shared):
        Processor.__init__(self)
        self.shared = shared
        self.config = config

    def process(self, session, request):
        print "process", session, request


def main():
    config = create_config()
    host = config.get('server', 'host')
    tcp_port = config.getint('server', 'port')
 
    print_log("Starting pyethereum server on", host)

    # Create hub
    dispatcher = Dispatcher(config)
    shared = dispatcher.shared

    # handle termination signals
    import signal
    def handler(signum = None, frame = None):
        print_log('Signal handler called with signal', signum)
        shared.stop()
    for sig in [signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT]:
        signal.signal(sig, handler)


    # Create and register processors
    server_proc = EtherProcessor(config, shared)
    dispatcher.register('server', server_proc)

    transports = []
    # Create various transports we need
    
    tcp_server = TcpServer(dispatcher, host, tcp_port)
    transports.append(tcp_server)

    for server in transports:
        server.start()


    while not shared.stopped():
        time.sleep(0.1)

    server_proc.join()
    print_log("pyethereum Server stopped")

if __name__ == '__main__':
    main()
