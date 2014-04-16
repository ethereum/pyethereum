import mock


class PeerHook(object):
    def before_feature(self, context, feature):
        from pyethereum.packeter import packeter
        import socket

        context.packeter = packeter
        packeter.configure(context.conf)
        context._connection = mock.MagicMock(spec=socket.socket)

    def mock_peer(self, context):
        from pyethereum.peer import Peer
        context.peer = Peer(context._connection, '127.0.0.1', 1234)
        peer = context.peer

        def side_effect():
            for i in range(3):
                peer.loop_body()

        peer.run = mock.MagicMock()
        peer.run.side_effect = side_effect

    def mock_connection_recv(self, context):
        received_packets = []

        def add_recv_packet(packet):
            received_packets.append(packet)

            def genarator(bufsize):
                for packet in received_packets:
                    for i in range(0, len(packet), bufsize):
                        yield packet[i: i + bufsize]
                    yield ''

            status = dict()

            def side_effect(bufsize):
                if 'genarator' not in status:
                    status.update(genarator=genarator(bufsize))

                try:
                    return status['genarator'].next()
                except:
                    return ''

            context._connection.recv.side_effect = side_effect

        context._connection.recv = mock.MagicMock()
        context.add_recv_packet = add_recv_packet
        context.add_recv_packet('')
        context.received_packets = received_packets

    def mock_connection_send(self, context):
        context.sent_packets = []

        def side_effect(packet):
            context.sent_packets.append(packet)
            return len(packet)

        context._connection.send = mock.MagicMock(side_effect=side_effect)

    def before_scenario(self, context, scenario):
        self.mock_peer(context)
        self.mock_connection_recv(context)
        self.mock_connection_send(context)

        time_sleep_patcher = mock.patch('time.sleep')
        time_sleep_patcher.start()
        context.time_sleep_patcher = time_sleep_patcher

    def after_scenario(self, context, scenario):
        context.time_sleep_patcher.stop()


hook = PeerHook()
