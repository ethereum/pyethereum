import mock
import socket


def mock_peer(connection, ip, port):
    from pyethereum.peer import Peer
    peer = Peer(connection, ip, port)

    def side_effect():
        for i in range(3):
            peer.loop_body()

    peer.run = mock.MagicMock()
    peer.run.side_effect = side_effect
    peer.start = peer.run
    return peer


def mock_connection():
    return mock.MagicMock(spec=socket.socket)


def mock_connection_recv(connection):
    received_packets = []

    def add_recv_packet(packet):
        received_packets.append(packet)

        def genarator(bufsize):
            for packet in received_packets:
                for i in range(0, len(packet), bufsize):
                    yield packet[i: i + bufsize]
                yield None

        status = dict()

        def side_effect(bufsize):
            if 'genarator' not in status:
                status.update(genarator=genarator(bufsize))

            try:
                buf = status['genarator'].next()
            except:
                buf = None

            if not buf:
                raise socket.error('time out')
            return buf

        connection.recv.side_effect = side_effect

    connection.recv = mock.MagicMock()
    add_recv_packet('')

    return (add_recv_packet, received_packets)


def mock_connection_send(connection):
    sent_packets = []

    def side_effect(packet):
        sent_packets.append(packet)
        return len(packet)

    connection.send = mock.MagicMock(side_effect=side_effect)
    return sent_packets
