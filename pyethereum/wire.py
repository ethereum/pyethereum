import struct
import time
import rlp
from utils import big_endian_to_int as idec
from utils import int_to_big_endian as ienc
import logging

ienc4 = lambda x: struct.pack('>I', x)  # 4 bytes big endian integer
logger = logging.getLogger(__name__)


def list_ienc(lst):
    "recursively big endian encode all integers in a list"
    nlst = []
    for i, e in enumerate(lst):
        if isinstance(e, list):
            nlst.append(list_ienc(e))
        elif isinstance(e, int):
            nlst.append(ienc(e))
        else:
            nlst.append(e)
    return nlst


def lrlp_decode(data):
    "always return a list"
    d = rlp.decode(data)
    if isinstance(d, str):
        d = [d]
    return d


def dump_packet(packet):
    try:
        header = idec(packet[:4])
        payload_len = idec(packet[4:8])
        data = lrlp_decode(packet[8:8 + payload_len])
        cmd = WireProtocol.cmd_map.get(
            idec(data[0]), 'unknown %s' % idec(data[0]))
        return [header, payload_len, cmd] + data[1:]
    except Exception as e:
        return ['DUMP failed', packet, e]


class WireProtocol(object):

    """
    Translates between the network and the local data
    https://github.com/ethereum/wiki/wiki/%5BEnglish%5D-Wire-Protocol
    """

    cmd_map = dict(((0x00, 'Hello'),
                   (0x01, 'Disconnect'),
                   (0x02, 'Ping'),
                   (0x03, 'Pong'),
                   (0x10, 'GetPeers'),
                   (0x11, 'Peers'),
                   (0x12, 'Transactions'),
                   (0x13, 'Blocks'),
                   (0x14, 'GetChain'),
                   (0x15, 'NotInChain'),
                   (0x16, 'GetTransactions')))
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

    SYNCHRONIZATION_TOKEN = 0x22400891

    # as sent by Ethereum(++)/v0.3.11/brew/Darwin/unknown
    PROTOCOL_VERSION = 0x08
    NETWORK_ID = 0
    CLIENT_ID = 'Ethereum(py)/0.0.1'
    CAPABILITIES = 0x01 + 0x02 + 0x04  # node discovery + transaction relaying
    NODE_ID = None

    # NEED NODE_ID in order to work with Ethereum(++)/ FIXME: replace by pubkey
    NODE_ID = 'J\x02U\xfaFs\xfa\xa3\x0f\xc5\xab\xfd<U\x0b\xfd\xbc\r<\x97=5\xf7&F:\xf8\x1cT\xa02\x81\xcf\xff"\xc5\xf5\x96[8\xacc\x01R\x98wW\xa3\x17\x82G\x85I\xc3o|\x84\xcbD6\xbay\xd6\xd9'

    def __init__(self, peermgr, config):
        self.peermgr = peermgr
        self.config = config

    def rcv_packet(self, peer, packet):
        """
        Though TCP provides a connection-oriented medium, Ethereum nodes communicate
        in terms of packets. These packets are formed as a 4-byte synchronisation token
        (0x22400891), a 4-byte "payload size", to be interpreted as a big-endian integer
        and finally an N-byte RLP-serialised data structure, where N is the aforementioned
        "payload size". To be clear, the payload size specifies the number of bytes in the
        packet ''following'' the first 8.
        """

        # check header
        if not idec(packet[:4]) == self.SYNCHRONIZATION_TOKEN:
            logger.warn('check header failed, skipping message, sync token was {0}'
                        .format(idec(packet[:4])))
            return

        # unpack message
        payload_len = idec(packet[4:8])
        # assert 8 + payload_len <= len(packet) # this get's sometimes raised!?
        data = lrlp_decode(packet[8:8 + payload_len])

        # check cmd
        if (not len(data)) or (idec(data[0]) not in self.cmd_map):
            logger.warn('check cmd failed')
            return self.send_Disconnect(peer, reason='Bad protocol')

        # good peer
        peer.last_valid_packet_received = time.time()

        cmd_id = idec(data.pop(0))
        func_name = "rcv_%s" % self.cmd_map[cmd_id]
        if not hasattr(self, func_name):
            logger.warn('unknown cmd \'{0}\''.format(func_name))
            return
            """
            return self.send_Disconnect(
                peer,
                reason='Incompatible network protocols')
            raise NotImplementedError('%s not implmented')
            """
        # check Hello was sent

        # call the correspondig method
        return getattr(self, func_name)(peer, data)

    def send_packet(self, peer, data):
        """
        4-byte synchronisation token, (0x22400891),
        a 4-byte "payload size", to be interpreted as a big-endian integer
        an N-byte RLP-serialised data structure
        """
        payload = rlp.encode(list_ienc(data))
        packet = ienc4(self.SYNCHRONIZATION_TOKEN)
        packet += ienc4(len(payload))
        packet += payload
        peer.send_packet(packet)

    def send_Hello(self, peer):
        # assert we did not sent hello yet
        payload = [0x00,
                   self.PROTOCOL_VERSION,
                   self.NETWORK_ID,
                   self.CLIENT_ID,
                   self.config.getint('network', 'listen_port'),
                   self.CAPABILITIES]
        if self.NODE_ID:
            payload.append(self.NODE_ID)
        self.send_packet(peer, payload)

        peer.hello_sent = True

    def rcv_Hello(self, peer, data):
        """
        [0x00, PROTOCOL_VERSION, NETWORK_ID, CLIENT_ID, CAPABILITIES, LISTEN_PORT, NODE_ID]
        First packet sent over the connection, and sent once by both sides.
        No other messages may be sent until a Hello is received.
        PROTOCOL_VERSION is one of:
            0x00 for PoC-1;
            0x01 for PoC-2;
            0x07 for PoC-3.
            0x08 sent by Ethereum(++)/v0.3.11/brew/Darwin/unknown
        NETWORK_ID should be 0.
        CLIENT_ID Specifies the client software identity, as a human-readable string
                    (e.g. "Ethereum(++)/1.0.0").
        CAPABILITIES specifies the capabilities of the client as a set of flags;
                    presently three bits are used:
                    0x01 for peers discovery, 0x02 for transaction relaying, 0x04 for block-chain querying.
        LISTEN_PORT specifies the port that the client is listening on
                    (on the interface that the present connection traverses).
                    If 0 it indicates the client is not listening.
        NODE_ID is optional and specifies a 512-bit hash, (potentially to be used as public key)
                    that identifies this node.

        [574621841, 116, 'Hello', '\x08', '', 'Ethereum(++)/v0.3.11/brew/Darwin/unknown', '\x07', 'v_', "\xc5\xfe\xc6\xea\xe4TKvz\x9e\xdc\xa7\x01\xf6b?\x7fB\xe7\xfc(#t\xe9}\xafh\xf3Ot'\xe5u\x07\xab\xa3\xe5\x95\x14 |P\xb0C\xa2\xe4jU\xc8z|\x86\xa6ZV!Q6\x82\xebQ$4+"]
        [574621841, 27, 'Hello', '\x08', '\x00', 'Ethereum(py)/0.0.1', 'vb', '\x07']
        """

        # check compatibility
        if idec(data[0]) != self.PROTOCOL_VERSION:
            return self.send_Disconnect(
                peer,
                reason='Incompatible network protocols')

        if idec(data[1]) != self.NETWORK_ID:
            return self.send_Disconnect(peer, reason='Wrong genesis block')

        """
        spec has CAPABILITIES after PORT, CPP client the other way round. emulating the latter
        https://github.com/ethereum/cpp-ethereum/blob/master/libethereum/PeerNetwork.cpp#L144
        """

        # TODO add to known peers list
        peer.hello_received = True
        if len(data) == 6:
            peer.node_id = data[5]

        # reply with hello if not send
        if not peer.hello_sent:
            self.send_Hello(peer)

    def send_Ping(self, peer):
        """
        [0x02]
        Requests an immediate reply of Pong from the peer.
        """
        self.send_packet(peer, [0x02])

    def rcv_Ping(self, peer, data):
        self.send_Pong(peer)

    def send_Pong(self, peer):
        """
        [0x03]
        Reply to peer's Ping packet.
        """
        self.send_packet(peer, [0x03])

    def rcv_Pong(self, peer, data):
        pass

    def send_Disconnect(self, peer, reason=None):
        """
        [0x01, REASON]
        Inform the peer that a disconnection is imminent;
        if received, a peer should disconnect immediately.
        When sending, well-behaved hosts give their peers a fighting chance
        (read: wait 2 seconds) to disconnect to before disconnecting themselves.
        REASON is an optional integer specifying one of a number of reasons
        """
        logger.info(
            'sending {0} disconnect because {1}'.format(repr(peer), reason))
        assert not reason or reason in self.disconnect_reasons_map
        payload = [0x01]
        if reason:
            payload.append(self.disconnect_reasons_map[reason])
        self.send_packet(peer, payload)
        # end connection
        time.sleep(2)
        self.peermgr.remove_peer(peer)

    def rcv_Disconnect(self, peer, data):
        if len(data):
            reason = self.disconnect_reasons_map_by_id[idec(data[0])]
            logger.info('{0} sent disconnect, {1} '.format(repr(peer), reason))
        self.peermgr.remove_peer(peer)

    def rcv_GetPeers(self, peer, data):
        """
        [0x10]
        Request the peer to enumerate some known peers for us to connect to.
        This should include the peer itself.
        """
        self.send_Peers(peer)

    def send_GetPeers(self, peer):
        self.send_packet(peer, [0x10])

    def rcv_Peers(self, peer, data):
        """
        [0x11, [IP1, Port1, Id1], [IP2, Port2, Id2], ... ]
        Specifies a number of known peers. IP is a 4-byte array 'ABCD' that
        should be interpreted as the IP address A.B.C.D. Port is a 2-byte array
        that should be interpreted as a 16-bit big-endian integer.
        Id is the 512-bit hash that acts as the unique identifier of the node.

        IPs look like this: ['6', '\xcc', '\n', ')']
        """
        for ip, port, pid in data:
            assert isinstance(ip, list)
            ip = '.'.join(str(ord(b or '\x00')) for b in ip)
            port = idec(port)
            logger.debug('received peer address: {0}:{1}'.format(ip, port))
            self.peermgr.add_peer_address(ip, port, pid)

    def send_Peers(self, peer):
        data = [0x11]
        for ip, port, pid in self.peermgr.get_known_peer_addresses():
            ip = list((chr(int(x)) for x in ip.split('.')))
            data.append([ip, port, pid])
        if len(data) > 1:
            self.send_packet(peer, data)  # FIXME

    def rcv_Blocks(self, peer, data):
        """
        [0x13, [block_header, transaction_list, uncle_list], ... ]
        Specify (a) block(s) that the peer should know about. The items in the list
        (following the first item, 0x13) are blocks in the format described in the
        main Ethereum specification.
        """
        for e in data:
            header, transaction_list, uncle_list = e
            logger.info('received block:  parent:{0}'.format(header[0].encode('hex')))
