class PacketerHook(object):
    def before_feature(self, context, feature):
        from pyethereum.packeter import Packeter
        context.packeter = packeter = Packeter()
        packeter.configure(context.conf)

hook = PacketerHook()
