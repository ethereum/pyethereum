import time
import Queue
import socket

import signals
from stoppable import StoppableLoopThread
from packeter import packeter
from utils import big_endian_to_int as idec
from utils import recursive_int_to_big_endian
import rlp
import blocks
from pyethereum.slogging import get_logger
log_net = get_logger('net')
log_p2p = get_logger('p2p')
log_packet = get_logger('p2p.packet')
log_eth = get_logger('eth.wire')


# Maximum number of send hashes GetChain will accept
MAX_GET_CHAIN_ACCEPT_HASHES = 2048
# Maximum number of hashes GetChain will ever send
MAX_GET_CHAIN_SEND_HASHES = 2048
# Maximum number of blocks GetChain will ever ask for
MAX_GET_CHAIN_ASK_BLOCKS = 512
# Maximum number of requested blocks GetChain will accept
MAX_GET_CHAIN_REQUEST_BLOCKS = 512
# Maximum number of blocks Blocks will ever send
MAX_BLOCKS_SEND = MAX_GET_CHAIN_REQUEST_BLOCKS
# Maximum number of blocks Blocks will ever accept
MAX_BLOCKS_ACCEPTED = MAX_BLOCKS_SEND


class Peer(StoppableLoopThread):

    def __init__(self, connection, ip, port):
        super(Peer, self).__init__()
        self._connection = connection

        assert ip.count('.') == 3
        self.ip = ip
        # None if peer was created in response to external connect
        self.port = port
        self.client_version = ''
        self.node_id = ''
        self.capabilities = []  # [('eth',40) , ('shh',12)]

        self.hello_received = False
        self.hello_sent = False
        self.last_valid_packet_received = time.time()
        self.last_asked_for_peers = 0
        self.last_pinged = 0
        self.status_received = False
        self.status_sent = False
        self.status_total_difficulty = None
        self.status_head_hash = None

        self.recv_buffer = ''
        self.response_queue = Queue.Queue()

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
        log_net.info("stopping", peer=self)
        # shut down
        try:
            self._connection.shutdown(socket.SHUT_RDWR)
        except socket.error as e:
            log_net.debug("shutting down failed", peer=self, error=e)
        self._connection.close()

    def send_packet(self, response):
        log_packet.debug('sending >>>', peer=self, cmd=packeter.packet_cmd(response))
        self.response_queue.put(response)

    def _process_send(self):
        '''
        :return: size of processed data
        '''
        # send packet
        try:
            packet = self.response_queue.get(block=False)
        except Queue.Empty:
            return 0
        try:
            self.connection().sendall(packet)
            return len(packet)
        except socket.error as e:
            log_packet.debug('send packet failed', peer=self, error=e)
            self.stop()
            return 0

    def _process_recv(self):
        '''
        :return: size of processed data
        '''
        # receive complete message
        processed_length = 0
        while True:
            try:
                # print 'receiving'
                self.recv_buffer += self.connection().recv(2048)
            except socket.error:  # Timeout
                # print 'timeout'
                break
            # check if we have a complete packet
            length = len(self.recv_buffer)
            # length > packet_header and length > expected packet size
            while len(self.recv_buffer) >= 8 and len(self.recv_buffer) >= packeter.packet_size(self.recv_buffer):
                processed_length += packeter.packet_size(self.recv_buffer)
                self._process_recv_buffer()

        return processed_length

    def _process_recv_buffer(self):
        try:
            cmd, data, self.recv_buffer = packeter.load_cmd(self.recv_buffer)
        except Exception as e:
            self.recv_buffer = ''
            log_packet.debug('could not load cmd', error=e)
            return self.send_Disconnect(reason='Bad protocol')

        # good peer
        self.last_valid_packet_received = time.time()
        log_packet.debug('receive <<<', peer=self, cmd=cmd, len_data=len(data))
        func_name = "_recv_{0}".format(cmd)
        if not hasattr(self, func_name):
            log_packet.debug('unknown cmd', cmd=cmd, peer=self)
            return
        getattr(self, func_name)(data)

    # Handshake
    def has_ethereum_capabilities(self):
        for p, pv in self.capabilities:
            if p == 'eth' and pv == packeter.ETHEREUM_PROTOCOL_VERSION:
                return True

    def send_Hello(self):
        log_p2p.debug('sending Hello', peer=self)
        self.send_packet(packeter.dump_Hello())
        self.hello_sent = True

    def _recv_Hello(self, data):
        # 0x01 Hello: [0x01: P, protocolVersion: P, clientVersion: B, [cap0: B,
        # cap1: B, ...], listenPort: P, id: B_64]
        _decode = (idec, str, list, idec, str)
        try:
            data = [_decode[i](x) for i, x in enumerate(data)]
            network_protocol_version, client_version = data[0], data[1]
            capabilities, listen_port, node_id = data[2], data[3], data[4]
            self.capabilities = [(p, ord(v)) for p, v in capabilities]
        except (IndexError, ValueError) as e:
            log_p2p.debug('could not decode Hello', peer=self, error=e)
            return self.send_Disconnect(reason='Incompatible network protocols')

        assert node_id
        if node_id == packeter.NODE_ID:
            log_p2p.critical('connected myself')
            return self.send_Disconnect(reason='Incompatible network protocols')

        self.capabilities = [(p, ord(v)) for p, v in capabilities]
        log_p2p.debug('received Hello', peer=self, network_protocol_version=network_protocol_version,
                      node_id=node_id.encode('hex')[:8], client_version=client_version, capabilities=self.capabilities)

        if network_protocol_version != packeter.NETWORK_PROTOCOL_VERSION:
            log_p2p.debug('Incompatible network protocols', peer=self,
                          expected=packeter.NETWORK_PROTOCOL_VERSION, received=network_protocol_version)
            return self.send_Disconnect(reason='Incompatible network protocols')

        self.hello_received = True
        self.client_version = client_version
        self.node_id = node_id
        self.port = listen_port  # replace connection port with listen port

        if not self.hello_sent:
            self.send_Hello()
        signals.peer_handshake_success.send(sender=Peer, peer=self)

# Status

    def send_Status(self, head_hash, head_total_difficulty, genesis_hash):
        log_eth.debug('sending status', total_difficulty=head_total_difficulty,
                      head=head_hash.encode('hex'), genesis=genesis_hash.encode('hex'))

        self.send_packet(packeter.dump_Status(head_total_difficulty, head_hash, genesis_hash))
        self.status_sent = True

    def _recv_Status(self, data):
        # [0x10: P, protocolVersion: P, networkID: P, totalDifficulty: P, latestHash: B_32, genesisHash: B_32]
        # check compatibility
        try:
            ethereum_protocol_version, network_id = idec(data[0]), idec(data[1])
            total_difficulty, head_hash, genesis_hash = idec(data[2]), data[3], data[4]
        except IndexError:
            return self.send_Disconnect(reason='Incompatible network protocols')

        log_eth.debug('received Status', peer=self,
                      ethereum_protocol_version=ethereum_protocol_version, total_difficulty=total_difficulty,
                      head=head_hash.encode('hex'), genesis=genesis_hash.encode('hex'))

        if ethereum_protocol_version != packeter.ETHEREUM_PROTOCOL_VERSION:
            return self.send_Disconnect(reason='Incompatible network protocols')

        if network_id != packeter.NETWORK_ID:
            return self.send_Disconnect(reason='Wrong genesis block')

        self.status_received = True
        self.status_head_hash = head_hash
        self.status_total_difficulty = total_difficulty
        signals.peer_status_received.send(sender=Peer, genesis_hash=genesis_hash, peer=self)

# ping pong

    def send_Ping(self):
        self.send_packet(packeter.dump_Ping())
        self.last_pinged = time.time()

    def _recv_Ping(self, data):
        self.send_Pong()

    def send_Pong(self):
        self.send_packet(packeter.dump_Pong())

    def _recv_Pong(self, data):
        pass

# disconnects
    reasons_to_forget = ('Bad protocol',
                         'Incompatible network protocols',
                         'Wrong genesis block')

    def send_Disconnect(self, reason=None):
        log_p2p.debug('sending disconnect', peer=self, readon=reason)
        self.send_packet(packeter.dump_Disconnect(reason=reason))
        # end connection
        time.sleep(2)
        forget = reason in self.reasons_to_forget
        signals.peer_disconnect_requested.send(Peer, peer=self, forget=forget)

    def _recv_Disconnect(self, data):
        if len(data):
            reason = packeter.disconnect_reasons_map_by_id[idec(data[0])]
            forget = reason in self.reasons_to_forget
        else:
            forget = None
            reason = None
        log_p2p.debug('received disconnect', peer=self, reason=None)
        signals.peer_disconnect_requested.send(sender=Peer, peer=self, forget=forget)

# peers

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
            log_p2p.trace('received peer address', peer=self, ip=ip, port=port)
            addresses.append([ip, port, pid])
        signals.peer_addresses_received.send(sender=Peer, addresses=addresses)

# transactions

    def send_Transactions(self, transactions):
        self.send_packet(packeter.dump_Transactions(transactions))

    def _recv_Transactions(self, data):
        log_eth.debug('received transactions', peer=self, num=len(data))
        signals.remote_transactions_received.send(sender=Peer, transactions=data, peer=self)

# blocks

    def send_Blocks(self, blocks):
        assert len(blocks) <= MAX_BLOCKS_SEND
        self.send_packet(packeter.dump_Blocks(blocks))

    def _recv_Blocks(self, data):
        # open('raw_remote_blocks_hex.txt',
        # 'a').write(rlp.encode(data).encode('hex') + '\n') # LOG line
        transient_blocks = [blocks.TransientBlock(rlp.encode(b)) for b in data]  # FIXME
        if len(transient_blocks) > MAX_BLOCKS_ACCEPTED:
            log_eth.debug('peer sending too many blocks', num=len(
                transient_blocks), peer=self, max=MAX_BLOCKS_ACCEPTED)
        signals.remote_blocks_received.send(
            sender=Peer, peer=self, transient_blocks=transient_blocks)

    def send_GetBlocks(self, block_hashes):
        self.send_packet(packeter.dump_GetBlocks(block_hashes))

    def _recv_GetBlocks(self, block_hashes):
        signals.get_blocks_received.send(sender=Peer, block_hashes=block_hashes, peer=self)

# new blocks
    def send_NewBlock(self, block):
        self.send_packet(packeter.dump_NewBlock(block))

    def _recv_NewBlock(self, data):
        """
        NewBlock [+0x07, [blockHeader, transactionList, uncleList], totalDifficulty] 
        Specify a single block that the peer should know about. 
        The composite item in the list (following the message ID) is a block in 
        the format described in the main Ethereum specification.

        totalDifficulty is the total difficulty of the block (aka score).
        """
        total_difficulty = idec(data[1])
        transient_block = blocks.TransientBlock(rlp.encode(data[0]))
        log_eth.debug('NewBlock', block=transient_block)
        signals.new_block_received.send(sender=Peer, peer=self, block=transient_block)

# block hashes
    def send_GetBlockHashes(self, block_hash, max_blocks):
        self.send_packet(packeter.dump_GetBlockHashes(block_hash, max_blocks))

    def _recv_GetBlockHashes(self, data):
        block_hash, count = data[0], idec(data[1])
        signals.get_block_hashes_received.send(
            sender=Peer, block_hash=block_hash, count=count, peer=self)

    def send_BlockHashes(self, block_hashes):
        self.send_packet(packeter.dump_BlockHashes(block_hashes))

    def _recv_BlockHashes(self, block_hashes):
        signals.remote_block_hashes_received.send(
            sender=Peer, block_hashes=block_hashes, peer=self)

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
