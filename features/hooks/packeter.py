class PacketerHook(object):
    def before_feature(self, context, feature):
        from pyethereum.wireprotocol import Packeter
        config = {'network': 'client_id'}
        context.packeter = Packeter(config)

hook = PacketerHook()
