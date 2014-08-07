import time
import Queue
import socket
import logging

import signals
from stoppable import StoppableLoopThread
from packeter import packeter
from utils import big_endian_to_int as idec
from utils import recursive_int_to_big_endian
import rlp
import blocks


MAX_GET_CHAIN_ACCEPT_HASHES = 2048 # Maximum number of send hashes GetChain will accept
MAX_GET_CHAIN_SEND_HASHES = 2048 # Maximum number of hashes GetChain will ever send
MAX_GET_CHAIN_ASK_BLOCKS = 512 # Maximum number of blocks GetChain will ever ask for
MAX_GET_CHAIN_REQUEST_BLOCKS = 512 # Maximum number of requested blocks GetChain will accept
MAX_BLOCKS_SEND = MAX_GET_CHAIN_REQUEST_BLOCKS # Maximum number of blocks Blocks will ever send
MAX_BLOCKS_ACCEPTED = MAX_BLOCKS_SEND # Maximum number of blocks Blocks will ever accept


logger = logging.getLogger(__name__)


class Peer(StoppableLoopThread):

    def __init__(self, connection, ip, port):
        super(Peer, self).__init__()
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

        self.recv_buffer = ''

        # connect signals

    def __repr__(self):
        return "<Peer(%s:%r)>" % (self.ip, self.port)

    def __str__(self):
        return "[{0}: {1}]".format(self.ip, self.port)

    def connection(self):
        if self.stopped():
            raise IOError("Connection was stopped")
        else:
            return self._connection

    def stop(self):
        super(Peer, self).stop()

        # shut down
        try:
            self._connection.shutdown(socket.SHUT_RDWR)
        except socket.error as e:
            logger.debug(
                "shutting down failed {0} \"{1}\"".format(repr(self), str(e)))
        self._connection.close()

    def send_packet(self, response):
        logger.debug('sending packet to {0} >>> {1}'.format(
            self, response.encode('hex')))
        self.response_queue.put(response)

    def _process_send(self):
        '''
        :return: size of processed data
        '''
        # send packet
        try:
            packet = self.response_queue.get(block=False)
        except Queue.Empty:
            packet = ''

        while packet:
            try:
                n = self.connection().send(packet)
                packet = packet[n:]
            except socket.error as e:
                logger.debug(
                    '{0}: send packet failed, {1}'
                    .format(self, str(e)))
                self.stop()
                break

        if packet:
            return len(packet)
        else:
            return 0

    def _process_recv(self):
        '''
        :return: size of processed data
        '''
        while True:
            try:
                self.recv_buffer += self.connection().recv(2048)
            except socket.error:
                break
        length = len(self.recv_buffer)
        while self.recv_buffer:
            self._process_recv_buffer()
        return length

    def _process_recv_buffer(self):
        try:
            cmd, data, self.recv_buffer = packeter.load_cmd(self.recv_buffer)
        except Exception as e:
            self.recv_buffer = ''
            logger.warn(e)
            return self.send_Disconnect(reason='Bad protocol')

        # good peer
        self.last_valid_packet_received = time.time()

        logger.debug('receive from {0} <<< cmd: {1}: data: {2}'.format(
            self, cmd,
            rlp.encode(recursive_int_to_big_endian(data)).encode('hex')
        ))

        func_name = "_recv_{0}".format(cmd)
        if not hasattr(self, func_name):
            logger.warn('unknown cmd \'{0}\''.format(func_name))
            return

        getattr(self, func_name)(data)

    def send_Hello(self):
        self.send_packet(packeter.dump_Hello())
        self.hello_sent = True

    def _recv_Hello(self, data):
        # check compatibility
        client_id, peer_protocol_version = data[2], idec(data[0])
        logger.debug('received Hello %s V:%r',client_id, peer_protocol_version)

        if peer_protocol_version != packeter.PROTOCOL_VERSION:
            return self.send_Disconnect(
                reason='Incompatible network protocols')

        if idec(data[1]) != packeter.NETWORK_ID:
            return self.send_Disconnect(reason='Wrong genesis block')

        # add to known peers list in handshake signal
        self.hello_received = True
        if len(data) == 6:
            self.node_id = data[5]
            self.port = idec(data[3]) # replace connection port with listen port

        # reply with hello if not send
        if not self.hello_sent:
            self.send_Hello()

        signals.peer_handshake_success.send(sender=Peer, peer=self)

    def send_Ping(self):
        self.send_packet(packeter.dump_Ping())
        self.last_pinged = time.time()

    def _recv_Ping(self, data):
        self.send_Pong()

    def send_Pong(self):
        self.send_packet(packeter.dump_Pong())

    def _recv_Pong(self, data):
        pass

    reasons_to_forget = ('Bad protocol',
                        'Incompatible network protocols',
                        'Wrong genesis block')

    def send_Disconnect(self, reason=None):
        logger.info('disconnecting {0}, reason: {1}'.format(
            str(self), reason or ''))
        self.send_packet(packeter.dump_Disconnect(reason=reason))
        # end connection
        time.sleep(2)
        forget = reason in self.reasons_to_forget
        signals.peer_disconnect_requested.send(Peer, peer=self, forget=forget)

    def _recv_Disconnect(self, data):
        if len(data):
            reason = packeter.disconnect_reasons_map_by_id[idec(data[0])]
            logger.info('{0} sent disconnect, {1} '.format(repr(self), reason))
            forget = reason in self.reasons_to_forget
        else:
            forget = None
        signals.peer_disconnect_requested.send(
                sender=Peer, peer=self, forget=forget)

    def send_GetPeers(self):
        self.send_packet(packeter.dump_GetPeers())

    def _recv_GetPeers(self, data):
        signals.getpeers_received.send(sender=Peer, peer=self)

    def send_Peers(self, peers):
        if peers:
            packet = packeter.dump_Peers(peers)
            self.send_packet(packet)

    def _recv_Peers(self, data):
        addresses = []
        for ip, port, pid in data:
            assert len(ip) == 4
            ip = '.'.join(str(ord(b)) for b in ip)
            port = idec(port)
            logger.debug('received peer address: {0}:{1}'.format(ip, port))
            addresses.append([ip, port, pid])
        signals.peer_addresses_received.send(sender=Peer, addresses=addresses)

    def send_GetTransactions(self):
        logger.info('asking for transactions')
        self.send_packet(packeter.dump_GetTransactions())

    def _recv_GetTransactions(self, data):
        logger.info('asking for transactions')
        signals.gettransactions_received.send(sender=Peer, peer=self)

    def send_Transactions(self, transactions):
        self.send_packet(packeter.dump_Transactions(transactions))

    def _recv_Transactions(self, data):
        logger.info('received transactions #%d', len(data))
        signals.remote_transactions_received.send(
            sender=Peer, transactions=data)

    def send_Blocks(self, blocks):
        assert len(blocks) <= MAX_BLOCKS_SEND
        self.send_packet(packeter.dump_Blocks(blocks))

    def _recv_Blocks(self, data):
        # open('raw_remote_blocks_hex.txt', 'a').write(rlp.encode(data).encode('hex') + '\n') # LOG line
        transient_blocks = [blocks.TransientBlock(rlp.encode(b)) for b in data] # FIXME
        if len(transient_blocks) > MAX_BLOCKS_ACCEPTED:
            logger.warn('Peer sending too many blocks %d', len(transient_blocks))
        signals.remote_blocks_received.send(
            sender=Peer, peer=self, transient_blocks=transient_blocks)

    def send_GetChain(self, parents=[], count=1):
        assert len(parents) <= MAX_GET_CHAIN_SEND_HASHES
        assert count <= MAX_GET_CHAIN_ASK_BLOCKS
        self.send_packet(packeter.dump_GetChain(parents, count))

    def _recv_GetChain(self, data):
        """
        [0x14, Parent1, Parent2, ..., ParentN, Count]
        Request the peer to send Count (to be interpreted as an integer) blocks
        in the current canonical block chain that are children of Parent1
        (to be interpreted as a SHA3 block hash). If Parent1 is not present in
        the block chain, it should instead act as if the request were for
        Parent2 &c. through to ParentN. If the designated parent is the present
        block chain head, an empty reply should be sent. If none of the parents
        are in the current canonical block chain, then NotInChain should be
        sent along with ParentN (i.e. the last Parent in the parents list).
        If no parents are passed, then reply need not be made.
        """
        block_hashes = data[:-1]
        count = idec(data[-1])

        if count > MAX_GET_CHAIN_REQUEST_BLOCKS:
            logger.warn('GetChain: Peer asking for too many blocks %d', count)

        if len(block_hashes) > MAX_GET_CHAIN_ACCEPT_HASHES:
            logger.warn('GetChain: Peer sending too many block hashes %d', len(block_hashes))

        signals.local_chain_requested.send(
            sender=Peer, peer=self, block_hashes=block_hashes, count=count)

    def send_NotInChain(self, block_hash):
        self.send_packet(packeter.dump_NotInChain(block_hash))

    def _recv_NotInChain(self, data):
        pass

    def loop_body(self):
        try:
            send_size = self._process_send()
            recv_size = self._process_recv()
        except IOError:
            self.stop()
            return
        # pause
        if not (send_size or recv_size):
            time.sleep(0.01)
