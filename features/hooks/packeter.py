class PacketerHook(object):
    def before_feature(self, context, feature):
        from pyethereum.packeter import Packeter
        context._hooks['config'].before_feature(context, feature)

        context.packeter = packeter = Packeter()
        packeter.config(context.conf)

hook = PacketerHook()
