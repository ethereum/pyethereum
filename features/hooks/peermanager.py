import mock
import utils


class PeerManagerHook(object):
    ''' need @config before @peermanager
    '''
    def before_feature(self, context, feature):
        from pyethereum.packeter import packeter

        context.packeter = packeter
        packeter.configure(context.conf)

    def before_scenario(self, context, scenario):
        from pyethereum.peermanager import PeerManager
        peer_manager = context.peer_manager = PeerManager()
        peer_manager.configure(context.conf)

        def run_side_effect():
            for i in range(3):
                peer_manager.loop_body()

        peer_manager.run = mock.MagicMock()
        peer_manager.run.side_effect = run_side_effect
        peer_manager.start = peer_manager.run

        def start_peer_side_effect(connection, ip, port):
            peer = utils.mock_peer(connection, ip, port)
            return peer

        peer_manager._start_peer = mock.MagicMock()
        peer_manager._start_peer = start_peer_side_effect

        time_sleep_patcher = mock.patch('time.sleep')
        time_sleep_patcher.start()
        context.time_sleep_patcher = time_sleep_patcher

    def after_scenario(self, context, scenario):
        context.time_sleep_patcher.stop()


hook = PeerManagerHook()
