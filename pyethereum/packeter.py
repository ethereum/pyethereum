import sys
import signals
import logging
from pyethereum import rlp
from pyethereum.utils import big_endian_to_int as idec
from pyethereum.utils import int_to_big_endian4 as ienc4
from pyethereum.utils import recursive_int_to_big_endian
from pyethereum import blocks
from pyethereum import dispatch

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
    stateless!
    .. note::
        #.  Can only be used after the `config` method is called
    '''
    """
    PROTOCOL_VERSION = 30
    # is the node s Unique Identifier and is the 512-bit hash that serves to
    # identify the node.
    CLIENT_ID = 'Ethereum(py)/0.6.0/%s/Protocol:%d' % (sys.platform,
                                                       PROTOCOL_VERSION)

    NETWORK_ID = 0
    SYNCHRONIZATION_TOKEN = 0x22400891
    CAPABILITIES = 0x01 + 0x02 + 0x04  # node discovery + transaction relaying


    cmd_map = dict(((0x00, 'Hello'),
                   (0x01, 'Disconnect'),
                   (0x02, 'Ping'),
                   (0x03, 'Pong'),
                   (0x10, 'GetPeers'),
                   (0x11, 'Peers'),
                   (0x12, 'Transactions'),
                   (0x13, 'Blocks'),
                   (0x16, 'GetTransactions'),
                   (0x17, 'GetBlockHashes'),
                   (0x18, 'BlockHashes'),
                   (0x19, 'GetBlocks'),
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
        self.CLIENT_ID = self.config.get('network', 'client_id') \
            or self.CLIENT_ID
        self.NODE_ID = self.config.get('network', 'node_id')

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
                'sync token was hex: {0:x}'.format(header)

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

        if (not len(payload)) or (idec(payload[0]) not in cls.cmd_map):
            return False, 'check cmd failed'

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

    def dump_Hello(self, total_difficulty=0, head_hash=blocks.genesis().hash, genesis_hash=blocks.genesis().hash):
        """
        [0x00, PROTOCOL_VERSION, NETWORK_ID, CLIENT_ID, CAPABILITIES,
        LISTEN_PORT, NODE_ID]
        First packet sent over the connection, and sent once by both sides.
        No other messages may be sent until a Hello is received.
        PROTOCOL_VERSION is one of:
            0x00 for PoC-1;
            0x01 for PoC-2;
            0x07 for PoC-3.
            0x08 sent by Ethereum(++)/v0.3.11/brew/Darwin/unknown
        NETWORK_ID should be 0.
        CLIENT_ID Specifies the client software identity, as a human-readable
            string (e.g. "Ethereum(++)/1.0.0").
        LISTEN_PORT specifies the port that the client is listening on
            (on the interface that the present connection traverses).
            If 0 it indicates the client is not listening.
        CAPABILITIES specifies the capabilities of the client as a set of
            flags; presently three bits are used:
            0x01 for peers discovery,
            0x02 for transaction relaying,
            0x04 for block-chain querying.
        NODE_ID is optional and specifies a 512-bit hash, (potentially to be
            used as public key) that identifies this node.

        """
        data = [self.cmd_map_by_name['Hello'],
                self.PROTOCOL_VERSION,
                self.NETWORK_ID,
                self.CLIENT_ID,
                self.CAPABILITIES,
                self.config.getint('network', 'listen_port'),
                self.NODE_ID,
                head_hash, # chain head hash
                total_difficulty, # chain head total difficulty,
                genesis_hash # genesis hash
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
