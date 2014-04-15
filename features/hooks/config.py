import mock


class ConfigHook(object):
    def before_feature(self, context, feature):
        context.config = config = mock.MagicMock()

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

hook = ConfigHook()
