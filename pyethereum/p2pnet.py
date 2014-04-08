import time
import Queue
import socket
import threading
import logging
from wire import WireProtocol, load_packet


logger = logging.getLogger(__name__)


class Peer(threading.Thread):

    def __init__(self, wire, connection, ip, port=None):
        threading.Thread.__init__(self)
        self.wire = wire
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
        self.last_asked_for_peers = 0
        self.last_pinged = 0

    def __repr__(self):
        return "<Peer(%s:%r)>" % (self.ip, self.port)

    def id(self):
        return hash(repr(self))

    def connection(self):
        if self.stopped():
            raise IOError("Connection was stopped")
        else:
            return self._connection

    def stop(self):
        logger.debug('disconnected: {0}'.format(repr(self)))
        with self.lock:
            if self._stopped:
                return
            self._stopped = True

        # shut down
        try:
            self._connection.shutdown(socket.SHUT_RDWR)
        except IOError as e:
            logger.debug(
                "shutting down failed {0} \"{1}\"".format(repr(self), str(e)))
        self._connection.close()

    def stopped(self):
        with self.lock:
            return self._stopped

    def send_packet(self, response):
        self.response_queue.put(response)

    def _process_send(self):
        '''
        :return: size of processed data
        '''
        # send packet
        try:
            packet = self.response_queue.get(timeout=.1)
        except Queue.Empty:
            packet = ''

        size = len(packet)

        while packet:
            logger.debug('{0}: send packet {1}'.format(
                repr(self), str(load_packet(packet))[:60]))
            try:
                n = self.connection().send(packet)
                packet = packet[n:]
            except IOError as e:
                logger.debug(
                    '{0}: send packet failed, {1}'
                    .format(repr(self), str(e)))
                self.stop()
                break
        return size

    def _process_recv(self):
        '''
        :return: size of processed data
        '''
        packet = ""
        while True:
            try:
                chunk = self.connection().recv(2048)
            except IOError:
                chunk = ''
            if not chunk:
                break
            packet += chunk

        if packet:
            logger.debug('{0}: received packet {1}'.format(
                repr(self), str(load_packet(packet))[:60]))
            self.wire.rcv_packet(self, packet)
        return len(packet)

    def run(self):
        while not self.stopped():
            send_size = self._process_send()
            recv_size = self._process_recv()
            # pause
            if not (send_size or recv_size):
                time.sleep(0.1)


class PeerManager(threading.Thread):

    max_silence = 5  # how long before pinging a peer
    max_ping_wait = 1.  # how long to wait before disconenctiong after ping
    max_ask_for_peers_elapsed = 30  # how long before asking for peers

    def __init__(self, config):
        threading.Thread.__init__(self)
        self.config = config
        self.connected_peers = set()
        self._seen_peers = set()  # (host, port, node_id)
        self._stopped = False
        self.local_address = ()  # host, port
        self.lock = threading.Lock()
        self.wire = WireProtocol(self, config)

    def get_peer_by_id(self, peer_id):
        for peer in self.connected_peers:
            if peer_id == peer.id():
                return peer
        return None

    def add_peer_address(self, ip, port, node_id):
        ipn = (ip, port, node_id)
        with self.lock:
            if ipn not in self._seen_peers:
                self._seen_peers.add(ipn)

    def get_known_peer_addresses(self):
        # fixme add self
        return set(self._seen_peers).union(self.get_connected_peer_addresses())

    def get_connected_peer_addresses(self):
        "get peers, we connected and have a port"
        return set((p.ip, p.port, p.node_id) for p in self.connected_peers
                   if p.port)

    def stop(self):
        with self.lock:
            if not self._stopped:
                for peer in self.connected_peers:
                    peer.stop()
            self._stopped = True

    def stopped(self):
        with self.lock:
            return self._stopped

    def add_peer(self, peer):
        with self.lock:
            self.connected_peers.add(peer)

    def remove_peer(self, peer):
        peer.stop()
        with self.lock:
            self.connected_peers.remove(peer)
        # connect new peers if there are no candidates

    def connect_peer(self, host, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1)
        logger.debug('connecting {0}:{1}'.format(host, port))
        try:
            sock.connect((host, port))
        except Exception as e:
            logger.debug(
                'Conencting {0}:{1} failed, {2}'.format(host, port, str(e)))
            return False
        sock.settimeout(.1)
        ip, port = sock.getpeername()
        logger.debug('connected {0}:{1}'.format(ip, port))
        peer = Peer(self.wire, sock, ip, port)
        self.add_peer(peer)
        peer.start()

        # Send Hello
        peer.wire.send_Hello(peer)
        peer.wire.send_GetPeers(peer)
        return True

    def _peer_candidates(self):
        candidates = self.get_known_peer_addresses().difference(
            self.get_connected_peer_addresses())
        candidates = [
            ipn for ipn in candidates if not ipn[:2] == self.local_address]
        return candidates

    def _poll_more_candidates(self):
        for peer in list(self.connected_peers):
            with peer.lock:
                peer.wire.send_GetPeers(peer)

    def _connect_peers(self):
        num_peers = self.config.getint('network', 'num_peers')
        candidates = self._peer_candidates()
        if len(self.connected_peers) < num_peers:
            logger.debug('not enough peers: {0}'.format(
                len(self.connected_peers)))
            logger.debug('num candidates: {0}'.format(len(candidates)))
            if len(candidates):
                ip, port, node_id = candidates.pop()
                self.connect_peer(ip, port)
                # don't use this node again in case of connect error > remove
                self._seen_peers.remove((ip, port, node_id))
            else:
                self._poll_more_candidates()

    def _check_alive(self, peer):
        now = time.time()
        dt_ping = now - peer.last_pinged
        dt_seen = now - peer.last_valid_packet_received
        # if ping was sent and not returned within last second
        if dt_ping < dt_seen and dt_ping > self.max_ping_wait:
            logger.debug(
                '{0} last ping: {1} last seen: {2}'
                .format(peer, dt_ping, dt_seen))
            logger.debug(
                '{0} did not respond to ping, disconnecting {1}:{2}'
                .format(peer, peer.ip, peer.port))
            self.remove_peer(peer)
        elif min(dt_seen, dt_ping) > self.max_silence:
            # ping silent peer
            logger.debug('pinging silent peer {0}'.format(peer))

            with peer.lock:
                peer.wire.send_Ping(peer)
                peer.last_pinged = now

    def manage_connections(self):
        self._connect_peers()

        for peer in list(self.connected_peers):
            if peer.stopped():
                self.remove_peer(peer)
                continue

            self._check_alive(peer)

            now = time.time()

            # ask for peers
            if now - peer.last_asked_for_peers >\
                    self.max_ask_for_peers_elapsed:
                with peer.lock:
                    peer.wire.send_GetPeers(peer)
                    peer.last_asked_for_peers = now

    def run(self):
        while not self.stopped():
            self.manage_connections()
            self.wire.process_chainmanager_queue()
            time.sleep(0.1)
