import uuid
import mock
import tempfile

from pyethereum.utils import sha3


class ConfigHook(object):
    def before_feature(self, context, feature):
        '''
        .. note::

            `context.conf` is used instead of `context.config` because `config`
            is used internally in `context` by *behave*

        '''
        context.conf = conf = mock.MagicMock()
        node_id = sha3(str(uuid.uuid1())).encode('hex')
        tempdir = tempfile.mkdtemp()

        def get_side_effect(section, option):
            if section == 'network' and option == 'client_id':
                return 'client id'

            if section == 'network' and option == 'node_id':
                return node_id

            if section == 'wallet' and option == 'coinbase':
                return '0'*40

            if section == 'misc' and option == 'data_dir':
                return tempdir

        def getint_side_effect(section, option):
            if section == 'network' and option == 'listen_port':
                return 1234

            if section == 'network' and option == 'num_peers':
                return 10

        conf.get.side_effect = get_side_effect
        conf.getint.side_effect = getint_side_effect

hook = ConfigHook()
