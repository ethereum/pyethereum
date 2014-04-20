import mock
import utils


class PeerHook(object):
    ''' need @config before @peer
    '''
    def before_feature(self, context, feature):
        from pyethereum.packeter import packeter

        context.packeter = packeter
        packeter.configure(context.conf)
        context._connection = utils.mock_connection()

    def before_scenario(self, context, scenario):
        context.peer = utils.mock_peer(context._connection, '127.0.0.1', 1234)
        context.add_recv_packet, context.received_packets = \
            utils.mock_connection_recv(context._connection)
        context.sent_packets = utils.mock_connection_send(context._connection)

        time_sleep_patcher = mock.patch('time.sleep')
        time_sleep_patcher.start()
        context.time_sleep_patcher = time_sleep_patcher

    def after_scenario(self, context, scenario):
        context.time_sleep_patcher.stop()


hook = PeerHook()
