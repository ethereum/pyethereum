import time
import Queue
import socket
import logging

import signals
from stoppable import StoppableLoopThread
from packeter import packeter
from utils import big_endian_to_int as idec, recursive_int_to_big_endian
import rlp


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
        if length:
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
        peer_protocol_version = idec(data[0])

        logger.debug('received Hello protocol_version:{0:#04x}'.format(
                     peer_protocol_version))

        if peer_protocol_version != packeter.PROTOCOL_VERSION:
            return self.send_Disconnect(
                reason='Incompatible network protocols'
                'expected:{0:#04x} received:{1:#04x}'.format(
                    packeter.PROTOCOL_VERSION, peer_protocol_version))

        if idec(data[1]) != packeter.NETWORK_ID:
            return self.send_Disconnect(reason='Wrong genesis block')

        # TODO add to known peers list
        self.hello_received = True
        if len(data) == 6:
            self.node_id = data[5]

        # reply with hello if not send
        if not self.hello_sent:
            self.send_Hello()

    def send_Ping(self):
        self.send_packet(packeter.dump_Ping())
        self.last_pinged = time.time()

    def _recv_Ping(self, data):
        self.send_Pong()

    def send_Pong(self):
        self.send_packet(packeter.dump_Pong())

    def _recv_Pong(self, data):
        self.send_GetTransactions()  # FIXME

    def send_Disconnect(self, reason=None):
        logger.info('disconnecting {0}, reason: {1}'.format(
            str(self), reason or ''))
        self.send_packet(packeter.dump_Disconnect())
        # end connection
        time.sleep(2)
        signals.disconnect_requested.send(self)

    def _recv_Disconnect(self, data):
        if len(data):
            reason = packeter.disconnect_reasons_map_by_id[idec(data[0])]
            logger.info('{0} sent disconnect, {1} '.format(repr(self), reason))
        signals.disconnect_requested.send(sender=self)

    def send_GetPeers(self):
        self.send_packet(packeter.dump_GetPeers())

    def _recv_GetPeers(self, data):
        signals.request_data_async('peers', self.send_Peers, data)

    def send_Peers(self, peers):
        packet = packeter.dump_Peers(peers)
        if packet:
            self.send_packet(packet)

    def _recv_Peers(self, data):
        for ip, port, pid in data:
            assert isinstance(ip, list)
            ip = '.'.join(str(ord(b or '\x00')) for b in ip)
            port = idec(port)
            logger.debug('received peer address: {0}:{1}'.format(ip, port))
            signals.new_peer_received.send(sender=self, peer=[ip, port, pid])

    def send_GetTransactions(self):
        logger.info('asking for transactions')
        self.send_packet(packeter.dump_GetTransactions())

    def _recv_GetTransactions(self, data):
        logger.info('asking for transactions')
        signals.request_data_async('transactions', self.send_Transactions)

    def send_Transactions(self, transactions):
        self.send_packet(packeter.dump_Transactions(transactions))

    def _recv_Transactions(self, data):
        logger.info('received transactions', len(data), self)
        signals.new_transactions_received.send(sender=self, transactions=data)

    def send_Blocks(self, blocks):
        self.send_packet(packeter.dump_Blocks(blocks))

    def _recv_Blocks(self, data):
        signals.new_blocks_received.send(sender=self, blocks=data)

    def send_GetChain(self, parents=[], count=1):
        self.send_packet(packeter.dump_GetChain(parents, count))

    def _recv_GetChain(self, data):
        signals.request_data_async('blocks', self.send_Blocks, data)

    def send_NotInChain(self, block_hash):
        self.send_packet(packeter.dump_NotInChain(block_hash))

    def _recv_NotInChain(self, data):
        pass

    def loop_body(self):
        send_size = self._process_send()
        recv_size = self._process_recv()
        # pause
        if not (send_size or recv_size):
            time.sleep(0.1)
