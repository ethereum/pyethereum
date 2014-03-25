#!/usr/bin/env python
import sys
import os
import time
import signal
import Queue
import ConfigParser
from optparse import OptionParser
import socket
import threading
import traceback
from itertools import imap
from wire import WireProtocol, dump_packet


def plog(*args):
    ts = time.strftime("[%d/%m/%Y-%H:%M:%S]")
    sys.stderr.write(ts + " " + " ".join(imap(str, args)) + "\n")
    sys.stderr.flush()


class Peer(threading.Thread):

    def __init__(self, peer_manager, connection, ip, port=None):
        threading.Thread.__init__(self)
        self.peer_manager = peer_manager
        self.protocol = WireProtocol(
            self.peer_manager,
            self.peer_manager.config)
        self._stopped = False
        self.lock = threading.Lock()
        self._connection = connection

        assert ip.count('.') == 3
        self.ip = ip
        # None if peer was created in response to external connect
        self.port = port
        self.node_id = ''
        self.response_queue = Queue.Queue()
        self.hello_received = False
        self.hello_sent = False
        self.last_valid_packet_received = time.time()
        self.last_pinged = 0

    def connection(self):
        if self.stopped():
            raise IOError("Connection was stopped")
        else:
            return self._connection

    def stop(self):
        with self.lock:
            if self._stopped:
                return
            self._stopped = True
        self.shutdown()

    def stopped(self):
        with self.lock:
            return self._stopped

    def shutdown(self):
        try:
            self._connection.shutdown(socket.SHUT_RDWR)
        except IOError as e:
            plog(self, "problem shutting down", self.ip, self.port, e)
        self._connection.close()

    def send_packet(self, response):
        self.response_queue.put(response)

    def receive(self):
        data = ""
        while True:
            try:
                chunk = self.connection().recv(2048)
            except IOError:
                chunk = ''
            if not chunk:
                break
            data += chunk
        return data

    def run(self):
        while not self.stopped():

            # send packet
            try:
                spacket = self.response_queue.get(timeout=.1)
            except Queue.Empty:
                spacket = None
            while spacket:
                plog(self, 'send packet', str(dump_packet(spacket))[:60], )
                try:
                    n = self.connection().send(spacket)
                    spacket = spacket[n:]
                except IOError as e:
                    plog(self, 'failed', e)
                    self.stop()
                    break

            # receive packet
            rpacket = self.receive()
            if rpacket:
                plog(self, 'received packet', str(dump_packet(rpacket))[:60], '...')
                self.protocol.rcv_packet(self, rpacket)

            # pause
            if not (rpacket or spacket):
                time.sleep(0.1)


class PeerManager(threading.Thread):

    max_silence = 5  # how long before pinging a peer
    max_ping_wait = 1.  # how long to wait before disconenctiong after ping

    def __init__(self, config):
        threading.Thread.__init__(self)
        self.config = config
        self._connected_peers = set()
        self._seen_peers = set()  # (host, port, node_id)
        self._stopped = False
        self.local_address = ()  # host, port
        self.lock = threading.Lock()

    def add_peer_address(self, ip, port, node_id):
        ipn = (ip, port, node_id)
        with self.lock:
            if not ipn in self._seen_peers:
                self._seen_peers.add(ipn)

    def get_known_peer_addresses(self):
        # fixme add self
        return set(self._seen_peers).union(self.get_connected_peer_addresses())

    def get_connected_peer_addresses(self):
        "get peers, we connected and have a port"
        return set((p.ip, p.port, p.node_id) for p in self._connected_peers if p.port)

    def stop(self):
        with self.lock:
            if not self._stopped:
                for peer in self._connected_peers:
                    peer.stop()
            self._stopped = True

    def stopped(self):
        with self.lock:
            return self._stopped

    def add_peer(self, peer):
        with self.lock:
            self._connected_peers.add(peer)

    def remove_peer(self, peer):
        peer.stop()
        with self.lock:
            self._connected_peers.remove(peer)

    def connect_peer(self, host, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1)
        plog(self, 'connecting', host, port)
        try:
            sock.connect((host, port))
        except Exception as e:
            plog(self, 'failed', e)
            return False
        sock.settimeout(.1)
        ip, port = sock.getpeername()
        plog(self, 'connected', ip, port)
        peer = Peer(self, sock, ip, port)
        self.add_peer(peer)
        peer.start()

        # Send Hello
        peer.protocol.send_Hello(peer)
        return True

    def manage_connections(self):
        num_peers = self.config.getint('network', 'num_peers')
        if len(self._connected_peers) < num_peers:
            candidates = self.get_known_peer_addresses().difference(
                self.get_connected_peer_addresses())
            #plog(self, 'not enough peers', len(self._connected_peers))
            #plog(self, 'num candidates:', len(candidates))
            #plog([ipn[:2] for ipn in candidates])
            # filter local port from candidates
            candidates = [
                ipn for ipn in candidates if not ipn[:2] == self.local_address]
            #plog( self.local_address, [ipn[:2] for ipn in candidates])
            if len(candidates):
                ip, port, node_id = candidates.pop()
                self.connect_peer(ip, port)
                # don't use this node again in case of connect error > remove
                self._seen_peers.remove((ip, port, node_id))

        for peer in list(self._connected_peers):
            if peer.stopped():
                self.remove_peer(peer)
                continue

            now = time.time()
            dt_ping = now - peer.last_pinged
            dt_seen = now - peer.last_valid_packet_received

            # if ping was sent and not returned within last second
            if dt_ping < dt_seen and dt_ping > self.max_ping_wait:
                plog(self, peer, 'last ping:', dt_ping, "last seen", dt_seen)
                plog(
                    self, peer, 'did not respond to ping, disconnecting', peer.ip, peer.port)
                self.remove_peer(peer)
            elif min(dt_seen, dt_ping) > self.max_silence:
                plog(self, peer, 'pinging silent peer')


                plog(self, '# connected peers %d/%d' % (len(self._connected_peers), num_peers))
                plog(self, '# candidates:', len(self.get_known_peer_addresses()))

                with peer.lock:
                    peer.protocol.send_Ping(peer)
                    peer.last_pinged = now

        # report every n seconds
        if False:
            plog(self, 'num peers', len(self._connected_peers))
            plog(self, 'seen peers', len(self._seen_peers))

    def run(self):
        while not self.stopped():
            self.manage_connections()
            time.sleep(0.1)


class TcpServer(threading.Thread):

    def __init__(self, peer_manager, host, port):
        self.peer_manager = peer_manager
        threading.Thread.__init__(self)
        self.daemon = True
        self.host = host
        self.port = port
        self.lock = threading.Lock()

        # start server
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        sock.listen(5)
        self.sock = sock
        self.ip, self.port = sock.getsockname()
        plog(self, "TCP server started", self.ip, self.port)

    def run(self):
        while not self.peer_manager.stopped():
            plog(self, 'in run loop')
            try:

                connection, (host, port) = self.sock.accept()
            except IOError as e:
                traceback.print_exc(file=sys.stdout)
                time.sleep(0.1)
                continue

            connection.settimeout(.1)
            try:
                peer = Peer(self.peer_manager, connection, host, None)
                self.peer_manager.add_peer(peer)
                peer.start()
                plog(self, "new TCP connection", connection, host, port)
            except BaseException as e:
                plog(self, "cannot start TCP session", str(e), host, port)
                traceback.print_exc(file=sys.stdout)
                connection.close()
                time.sleep(0.1)


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

    # peer manager
    peer_manager = PeerManager(config=config)

    # start tcp server
    try:
        tcp_server = TcpServer(peer_manager,
                               config.get('network', 'listen_host'),
                               config.getint('network', 'listen_port'))
    except IOError as e:
        plog("Could not start TCP server", e)
        sys.exit(1)

    peer_manager.local_address = (tcp_server.ip, tcp_server.port)
    tcp_server.start()
    peer_manager.start()

    # handle termination signals
    def signal_handler(signum=None, frame=None):
        plog('Signal handler called with signal', signum)
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

    plog('extiting')
    # tcp_server.join() # does not work!
    peer_manager.join()

if __name__ == '__main__':
    main()
