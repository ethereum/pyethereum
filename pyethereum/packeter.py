import sys
import signals
import logging
from pyethereum import rlp
from pyethereum.utils import big_endian_to_int as idec
from pyethereum.utils import int_to_big_endian4 as ienc4
from pyethereum.utils import recursive_int_to_big_endian
from pyethereum.utils import sha3
from pyethereum import dispatch
from . import __version__

logger = logging.getLogger(__name__)


def lrlp_decode(data):
    "always return a list"
    d = rlp.decode(data)
    if isinstance(d, str):
        d = [d]
    return d


def load_packet(packet):
    return Packeter.load_packet(packet)


class Packeter(object):
    """
    Translates between the network and the local data
    https://github.com/ethereum/wiki/wiki/%5BEnglish%5D-Wire-Protocol
    https://github.com/ethereum/cpp-ethereum/wiki/%C3%90%CE%9EVP2P-Networking

    """
    NETWORK_PROTOCOL_VERSION = 0
    ETHEREUM_PROTOCOL_VERSION = 33  # IF CHANGED, DO: git tag 0.6.<ETHEREUM_PROTOCOL_VERSION>
    CLIENT_VERSION = 'Ethereum(py)/%s/%s' % (sys.platform, __version__)
    #the node s Unique Identifier and is the 512-bit hash that serves to identify the node.
    NODE_ID = sha3('')  # set in config
    NETWORK_ID = 0
    SYNCHRONIZATION_TOKEN = 0x22400891
    CAPABILITIES = ['eth']  # + ['shh']  ethereum protocol  whisper protocol

    cmd_map = dict(((0x00, 'Hello'),
                   (0x01, 'Disconnect'),
                   (0x02, 'Ping'),
                   (0x03, 'Pong'),
                   (0x04, 'GetPeers'),
                   (0x05, 'Peers'),
                   (0x10, 'Status'),
                   (0x11, 'GetTransactions'),
                   (0x12, 'Transactions'),
                   (0x13, 'GetBlockHashes'),
                   (0x14, 'BlockHashes'),
                   (0x15, 'GetBlocks'),
                   (0x16, 'Blocks'),
                   ))
    cmd_map_by_name = dict((v, k) for k, v in cmd_map.items())

    disconnect_reasons_map = dict((
        ('Disconnect requested', 0x00),
        ('TCP sub-system error', 0x01),
        ('Bad protocol', 0x02),
        ('Useless peer', 0x03),
        ('Too many peers', 0x04),
        ('Already connected', 0x05),
        ('Wrong genesis block', 0x06),
        ('Incompatible network protocols', 0x07),
        ('Client quitting', 0x08)))
    disconnect_reasons_map_by_id = \
        dict((v, k) for k, v in disconnect_reasons_map.items())


    def __init__(self):
        pass

    def configure(self, config):
        self.config = config
        self.CLIENT_VERSION = self.config.get('network', 'client_version') \
            or self.CLIENT_VERSION
        self.NODE_ID = self.config.get('network', 'node_id')

    @classmethod
    def packet_size(cls, packet):
        return idec(packet[4:8]) + 8

    @classmethod
    def packet_cmd(cls, packet):
<<<<<<< HEAD
        return Packeter.cmd_map.get(idec(rlp.descend(packet[8:200], 0)))
=======
        try:
            v = idec(rlp.descend(packet[8:200],0))
        except rlp.DecodingError:
            v = -1
        return Packeter.cmd_map.get(v, 'invalid')
>>>>>>> a63372fb7a908fd9f7d9a4848b54cfdbe5c21773

    @classmethod
    def load_packet(cls, packet):
        '''
        Though TCP provides a connection-oriented medium, Ethereum nodes
        communicate in terms of packets. These packets are formed as a 4-byte
        synchronisation token (0x22400891), a 4-byte "payload size", to be
        interpreted as a big-endian integer and finally an N-byte
        RLP-serialised data structure, where N is the aforementioned
        "payload size". To be clear, the payload size specifies the number of
        bytes in the packet ''following'' the first 8.

        :return: (success, result), where result should be None when fail,
        and (header, payload_len, cmd, data) when success
        '''
        header = idec(packet[:4])
        if header != cls.SYNCHRONIZATION_TOKEN:
            return False, 'check header failed, skipping message,'\
                'sync token was hex: %s' % hex(header)

        try:
            payload_len = idec(packet[4:8])
        except Exception as e:
            return False, str(e)

        if len(packet) < payload_len + 8:
            return False, 'Packet is broken'

        try:
            payload = lrlp_decode(packet[8:8 + payload_len])
        except Exception as e:
            return False, str(e)

        #logger.debug('load packet, cmd:%d %r', idec(payload[0]), Packeter.cmd_map.get(idec(payload[0]),'unknown'))
        if (not len(payload)) or (idec(payload[0]) not in cls.cmd_map):
            return False, 'check cmd %r failed' % idec(payload[0])

        cmd = Packeter.cmd_map.get(idec(payload[0]))
        remain = packet[8 + payload_len:]
        return True, (header, payload_len, cmd, payload[1:], remain)

    def load_cmd(self, packet):
        success, res = self.load_packet(packet)
        if not success:
            raise Exception(res)
        _, _, cmd, data, remain = res
        return cmd, data, remain

    @classmethod
    def dump_packet(cls, data):
        """
        4-byte synchronisation token, (0x22400891),
        a 4-byte "payload size", to be interpreted as a big-endian integer
        an N-byte RLP-serialised data structure
        """
        payload = rlp.encode(recursive_int_to_big_endian(data))

        packet = ienc4(cls.SYNCHRONIZATION_TOKEN)
        packet += ienc4(len(payload))
        packet += payload
        return packet

    def dump_Hello(self):
        """
        0x01 Hello: [0x01: P, protocolVersion: P, clientVersion: B, [cap0: B, cap1: B, ...], listenPort: P, id: B_64]

        protocolVersion: The underlying network protocol. 0
        clientVersion: The underlying client. A user-readable string.
        capN: A peer-network capability code, readable ASCII and 3 letters. Currently only "eth" and "shh" are known.
        listenPort: The port on which the peer is listening for an incoming connection.
        id: The identity and public key of the peer.
        """
        data = [self.cmd_map_by_name['Hello'],
                self.NETWORK_PROTOCOL_VERSION,
                self.CLIENT_VERSION,
                self.CAPABILITIES,
                self.config.getint('network', 'listen_port'),
                self.NODE_ID
                ]
        return self.dump_packet(data)

    def dump_Ping(self):
        data = [self.cmd_map_by_name['Ping']]
        return self.dump_packet(data)

    def dump_Pong(self):
        data = [self.cmd_map_by_name['Pong']]
        return self.dump_packet(data)

    def dump_Disconnect(self, reason=None):
        data = [self.cmd_map_by_name['Disconnect']]
        if reason:
            data.append(self.disconnect_reasons_map[reason])
        return self.dump_packet(data)

    def dump_GetPeers(self):
        data = [self.cmd_map_by_name['GetPeers']]
        return self.dump_packet(data)

    def dump_Peers(self, peers):
        '''
        :param peers: a sequence of (ip, port, pid)
        :return: None if no peers
        '''
        data = [self.cmd_map_by_name['Peers']]
        for ip, port, pid in peers:
            assert ip.count('.') == 3
            ip = ''.join(chr(int(x)) for x in ip.split('.'))
            data.append([ip, port, pid])
        return self.dump_packet(data)


    def dump_Status(self, total_difficulty, head_hash, genesis_hash):
        """
        0x10 Status: [0x10: P, protocolVersion: P, networkID: P, totalDifficulty: P, latestHash: B_32, genesisHash: B_32]

        protocolVersion: The version of the Ethereum protocol this peer implements. 30 at present.
        networkID: The network version of Ethereum for this peer. 0 for the official testnet.
        totalDifficulty: Total Difficulty of the best chain. Integer, as found in block header.
        latestHash: The hash of the block with the highest validated total difficulty.
        GenesisHash: The hash of the Genesis block.
        """
        data = [self.cmd_map_by_name['Status'],
                self.ETHEREUM_PROTOCOL_VERSION,
                self.NETWORK_ID,
                total_difficulty,  # chain head total difficulty,
                head_hash,  # chain head hash
                genesis_hash  # genesis hash
                ]
        return self.dump_packet(data)


    def dump_Transactions(self, transactions):
        data = [self.cmd_map_by_name['Transactions']] + transactions
        return self.dump_packet(data)

    def dump_GetTransactions(self):
        """
        [0x12, [nonce, receiving_address, value, ... ], ... ]
        Specify (a) transaction(s) that the peer should make sure is included
        on its transaction queue. The items in the list (following the first
        item 0x12) are transactions in the format described in the main
        Ethereum specification.
        """
        data = [self.cmd_map_by_name['GetTransactions']]
        return self.dump_packet(data)

    def dump_Blocks(self, blocks):
        blocks_as_lists = [rlp.decode(b.serialize()) for b in blocks]
        # FIXME, can we have a method to append rlp encoded data
        data = [self.cmd_map_by_name['Blocks']] + blocks_as_lists
        return self.dump_packet(data)


    def dump_GetBlockHashes(self, block_hash, max_blocks):
        """
        [0x17, [ hash : B_32, maxBlocks: P ]]
        Requests a BlockHashes message of at most maxBlocks entries, of block hashes from
        the blockchain, starting at the parent of block hash. Does not require the peer
        to give maxBlocks hashes - they could give somewhat fewer.
        """
        data = [self.cmd_map_by_name['GetBlockHashes'], block_hash, max_blocks]
        return self.dump_packet(data)


    def dump_BlockHashes(self, block_hashes):
        """
        [0x18, [ hash_0: B_32, hash_1: B_32, .... ]]
        Gives a series of hashes of blocks (each the child of the next). This implies that
        the blocks are ordered from youngest to oldest.
        """
        data = [self.cmd_map_by_name['BlockHashes']] + block_hashes
        return self.dump_packet(data)


    def dump_GetBlocks(self, block_hashes):
        """
        [0x19,[ hash_0: B_32, hash_1: B_32, .... ]]
        Requests a Blocks message detailing a number of blocks to be sent, each referred to
        by a hash. Note: Don't expect that the peer necessarily give you all these blocks
        in a single message - you might have to re-request them.
        """
        data = [self.cmd_map_by_name['GetBlocks']] + block_hashes
        return self.dump_packet(data)


packeter = Packeter()


@dispatch.receiver(signals.config_ready)
def config_packeter(sender, config, **kwargs):
    packeter.configure(config)
