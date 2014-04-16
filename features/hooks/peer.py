import mock


class PeerHook(object):
    def before_feature(self, context, feature):
        from pyethereum.peer import Peer
        from pyethereum.packeter import packeter
        import socket

        context.packeter = packeter
        packeter.configure(context.conf)
        context._connection = connection = mock.MagicMock(spec=socket.socket)
        context.peer = Peer(connection, '127.0.0.1', 1234)

    def before_scenario(self, context, scenario):
        peer = context.peer

        def side_effect():
            for i in range(2):
                peer.loop_body()

        peer.run = mock.MagicMock()
        peer.run.side_effect = side_effect

        connection = context._connection

        def set_recv_packet(packet):
            progress = dict(index=0)

            def side_effect(bufsize):
                i = progress['index']
                if (i >= len(packet)):
                    return ''
                buf = packet[i: i + bufsize]
                progress['index'] = i + bufsize
                return buf

            connection.recv.side_effect = side_effect

        connection.recv = mock.MagicMock()
        context.set_recv_packet = set_recv_packet
        context.set_recv_packet('')

        sent_packets = []

        def get_sent_packet():
            return sent_packets

        def side_effect(packet):
            sent_packets.append(packet)
            return len(packet)

        connection.send = mock.MagicMock(side_effect=side_effect)
        context.get_sent_packet = get_sent_packet

        time_sleep_patcher = mock.patch('time.sleep')
        time_sleep_patcher.start()
        context.time_sleep_patcher = time_sleep_patcher

    def after_scenario(self, context, scenario):
        context.time_sleep_patcher.stop()


hook = PeerHook()
