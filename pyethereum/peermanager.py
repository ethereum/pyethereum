import time
import socket
import logging
import json
import os

from dispatch import receiver

from stoppable import StoppableLoopThread
import rlp
import signals
from peer import Peer

logger = logging.getLogger(__name__)

def is_valid_ip(ip): # FIXME, IPV6
    return ip.count('.') == 3


class PeerManager(StoppableLoopThread):

    max_silence = 10  # how long before pinging a peer
    max_ping_wait = 15  # how long to wait before disconenctiong after ping
    max_ask_for_peers_elapsed = 30  # how long before asking for peers

    def __init__(self):
        super(PeerManager, self).__init__()
        self.connected_peers = set()
        self._known_peers = set()  # (ip, port, node_id)
        self.local_ip = '0.0.0.0'
        self.local_port = 0
        self.local_node_id = ''

    def configure(self, config):
        self.config = config
        self.local_node_id = config.get('network', 'node_id')
        self.local_ip = config.get('network', 'listen_host')
        assert is_valid_ip(self.local_ip)
        self.local_port = config.getint('network', 'listen_port')

    def stop(self):
        with self.lock:
            if not self._stopped:
                for peer in self.connected_peers:
                    peer.stop()
        super(PeerManager, self).stop()

    def load_saved_peers(self):
        path = os.path.join(self.config.get('misc', 'data_dir'), 'peers.json')
        if os.path.exists(path):
            peers = set((ip, port, "") for ip, port in json.load(open(path)))
            self._known_peers.update(peers)

    def save_peers(self):
        path = os.path.join(self.config.get('misc', 'data_dir'), 'peers.json')
        json.dump([[i, p] for i, p, n in self._known_peers], open(path, 'w'))

    def add_known_peer_address(self, ip, port, node_id):
        assert is_valid_ip(ip)
        if not ip or not port or not node_id:
            return
        ipn = (ip, port, node_id)
        if node_id not in (self.local_node_id, ""):
            with self.lock:
                if ipn not in self._known_peers:
                    # remove and readd if peer was loaded (without node id)
                    if (ip, port, "") in self._known_peers:
                        self._known_peers.remove((ip, port, ""))
                    self._known_peers.add(ipn)

    def remove_known_peer_address(self, ip, port, node_id):
        self._known_peers.remove((ip, port, node_id))

    def get_known_peer_addresses(self):
        return set(self._known_peers).union(
            self.get_connected_peer_addresses())

    def get_connected_peer_addresses(self):
        "get peers, we connected and have a port"
        return set((p.ip, p.port, p.node_id) for p in self.connected_peers
                   if p.hello_received)

    def remove_peer(self, peer):
        if not peer.stopped():
            peer.stop()
        with self.lock:
            self.connected_peers.remove(peer)
        # connect new peers if there are no candidates

    def _create_peer_sock(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1)
        return sock

    def connect_peer(self, host, port):
        '''
        :param host:  domain notation or IP
        '''
        sock = self._create_peer_sock()
        logger.debug('connecting {0}:{1}'.format(host, port))
        try:
            sock.connect((host, port))
        except Exception as e:
            logger.debug('Connecting %s:%d failed, %s', host, port, e)
            return None
        ip, port = sock.getpeername()
        logger.debug('connected {0}:{1}'.format(ip, port))
        peer = self.add_peer(sock, ip, port)

        # Send Hello
        peer.send_Hello()
        return peer

    def get_peer_candidates(self):
        candidates = self.get_known_peer_addresses().difference(
            self.get_connected_peer_addresses())
        candidates = [
            ipn for ipn in candidates if ipn[2] != self.local_node_id]
        return candidates

    def _check_alive(self, peer):
        if peer.stopped():
            self.remove_peer(peer)
            return

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

    def _connect_peers(self):
        num_peers = self.config.getint('network', 'num_peers')
        candidates = self.get_peer_candidates()
        if len(self.connected_peers) < num_peers:
            logger.debug('not enough peers: {0}'.format(
                len(self.connected_peers)))
            logger.debug('num candidates: {0}'.format(len(candidates)))
            if len(candidates):
                ip, port, node_id = candidates.pop()
                self.connect_peer(ip, port)
                # don't use this node again in case of connect error > remove
                self.remove_known_peer_address(ip, port, node_id)
            else:
                for peer in list(self.connected_peers):
                    with peer.lock:
                        peer.send_GetPeers()

    def loop_body(self):
        "check peer health every 10 seconds"
        for peer in list(self.connected_peers):
            self._check_alive(peer)
        self._connect_peers()

        if len(self._known_peers) == 0:
            self.load_saved_peers()

        for i in range(100):
            if not self.stopped():
                time.sleep(.1)

    def _start_peer(self, connection, ip, port):
        peer = Peer(connection, ip, port)
        peer.start()
        return peer

    def add_peer(self, connection, ip, port):
        # check existance first
        for peer in self.connected_peers:
            if (ip, port) == (peer.ip, peer.port):
                return peer
        connection.settimeout(1)
        peer = self._start_peer(connection, ip, port)
        with self.lock:
            self.connected_peers.add(peer)
        return peer

peer_manager = PeerManager()


@receiver(signals.config_ready)
def config_peermanager(sender, config, **kwargs):
    peer_manager.configure(config)


@receiver(signals.peer_connection_accepted)
def connection_accepted_handler(sender, connection, ip, port, **kwargs):
    peer_manager.add_peer(connection, ip, port)


@receiver(signals.send_local_blocks)
def send_blocks_handler(sender, blocks=[], **kwargs):
    for peer in peer_manager.connected_peers:
        peer.send_Blocks(blocks)


@receiver(signals.getpeers_received)
def getaddress_received_handler(sender, peer, **kwargs):
    with peer_manager.lock:
        peers = peer_manager.get_known_peer_addresses()
        assert is_valid_ip(peer_manager.local_ip)
        peers.add((peer_manager.local_ip,
                  peer_manager.local_port,
                  peer_manager.local_node_id))
    peer.send_Peers(peers)


@receiver(signals.peer_disconnect_requested)
def disconnect_requested_handler(sender, peer, forget=False, **kwargs):
    peer_manager.remove_peer(peer)
    if forget:
        ipn = (peer.ip, peer.port, peer.node_id)
        if ipn in peer_manager._known_peers:
            peer_manager.remove_known_peer_address(*ipn)
            peer_manager.save_peers()


@receiver(signals.peer_addresses_received)
def peer_addresses_received_handler(sender, addresses, **kwargs):
    ''' addresses should be (ip, port, node_id)
    '''
    for ip, port, node_id in addresses:
        peer_manager.add_known_peer_address(ip, port, node_id)
    peer_manager.save_peers()


@receiver(signals.send_local_transactions)
def send_transactions(sender, transactions=[], **kwargs):
    transactions = [rlp.decode(t.serialize()) for t in transactions]
    for peer in peer_manager.connected_peers:
        peer.send_Transactions(transactions)


@receiver(signals.remote_chain_requested)
def request_remote_chain(sender, parents=[], count=1, **kwargs):
    for peer in peer_manager.connected_peers:
        peer.send_GetChain(parents, count)


@receiver(signals.peer_handshake_success)
def new_peer_connected(sender, peer, **kwargs):
    logger.debug("received new_peer_connected")
    peer_manager.add_known_peer_address(peer.ip, peer.port, peer.node_id)
