import time
import socket
import logging
import traceback
import sys

from dispatch import receiver

from common import StoppableLoopThread
import signals
from peer import Peer

logger = logging.getLogger(__name__)


class PeerManager(StoppableLoopThread):

    max_silence = 5  # how long before pinging a peer
    max_ping_wait = 1.  # how long to wait before disconenctiong after ping
    max_ask_for_peers_elapsed = 30  # how long before asking for peers

    def __init__(self):
        super(PeerManager, self).__init__()
        self.connected_peers = set()
        self._known_peers = set()  # (host, port, node_id)
        self.local_address = ()  # host, port

    def configure(self, config):
        self.config = config

    def stop(self):
        with self.lock:
            if not self._stopped:
                for peer in self.connected_peers:
                    peer.stop()
        super(PeerManager, self).stop()

    def get_peer_by_id(self, peer_id):
        for peer in self.connected_peers:
            if peer_id == peer.id():
                return peer
        return None

    def add_known_peer_address(self, ip, port, node_id):
        ipn = (ip, port, node_id)
        with self.lock:
            if ipn not in self._known_peers:
                self._known_peers.add(ipn)

    def get_known_peer_addresses(self):
        return set(self._known_peers).union(
            self.get_connected_peer_addresses())

    def get_connected_peer_addresses(self):
        "get peers, we connected and have a port"
        return set((p.ip, p.port, p.node_id) for p in self.connected_peers
                   if p.port)

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
        peer = self.add_peer(sock, ip, port)

        # Send Hello
        peer.send_Hello()
        peer.send_GetPeers()
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
                peer.send_GetPeers()

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
                self._known_peers.remove((ip, port, node_id))
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
                peer.send_Ping()

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
                    peer.send_GetPeers()
                    peer.last_asked_for_peers = now

    def loop_body(self):
        self.manage_connections()
        time.sleep(10)

    def add_peer(self, connection, host, port):
        # FIXME: should check existance first
        connection.settimeout(.1)
        try:
            peer = Peer(connection, host, port)
            peer.start()
            with self.lock:
                self.connected_peers.add(peer)
            logger.debug(
                "new TCP connection {0} {1}:{2}"
                .format(connection, host, port))
        except BaseException as e:
            logger.error(
                "cannot start TCP session \"{0}\" {1}:{2} "
                .format(str(e), host, port))
            traceback.print_exc(file=sys.stdout)
            connection.close()
            time.sleep(0.1)
        return peer

peer_manager = PeerManager()


@receiver(signals.config_ready)
def config_peermanager(sender, **kwargs):
    peer_manager.configure(sender)


@receiver(signals.connection_accepted)
def connection_accepted_handler(sender, connection, host, port, **kwargs):
    peer_manager.add_peer(connection, host, port)


@receiver(signals.peers_data_requested)
def peers_data_requested_handler(sender, data, **kwargs):
    peers = peer_manager.get_known_peer_addresses()
    signals.peers_data_ready.send(None, requester=sender, ready_data=peers)


@receiver(signals.disconnect_requested)
def disconnect_requested_handler(sender, **kwargs):
    peer = sender
    peer_manager.remove_peer(peer)


@receiver(signals.new_peer_received)
def new_peer_received_handler(sender, peer, **kwargs):
    ''' peer should be (ip, port, node_id)
    '''
    peer_manager.add_known_peer_address(*peer)
