import mock


class WireProtocolHook(object):
    def before_feature(self, context, feature):
        from pyethereum.wireprotocol import WireProtocol
        from pyethereum.peermanager import Peer, PeerManager
        config = mock.MagicMock()

        def get_side_effect(section, option):
            if section == 'network' and option == 'client_id':
                return 'client id'

            if section == 'wallet' and option == 'pub_key':
                return 'this pub key'

        def getint_side_effect(section, option):
            if section == 'network' and option == 'listen_port':
                return 1234

        config.get.side_effect = get_side_effect
        config.getint.side_effect = getint_side_effect

        context.peer_manager = peer_manager = mock.MagicMock(spec=PeerManager)
        context.wireprotocol = WireProtocol(peer_manager, config)
        context.packeter = context.wireprotocol.packeter

        context.peer = peer = mock.MagicMock(spec=Peer)
        peer.hello_sent = False
        peer.hello_received = False

    def before_scenario(self, context, scenario):
        context.peer.reset_mock()
        context.peer_manager.reset_mock()

hook = WireProtocolHook()
