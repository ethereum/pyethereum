import mock


class PacketerHook(object):
    def before_feature(self, context, feature):
        from pyethereum.wireprotocol import Packeter
        config = mock.Mock()

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
        context.packeter = Packeter(config)

hook = PacketerHook()
