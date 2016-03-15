import sys
import random
import copy
import six
import rlp
import gevent

from devp2p.crypto import (
    sha3,
    privtopub as privtopub_raw,
)
from devp2p.app import BaseApp
from devp2p.protocol import BaseProtocol
from devp2p.service import WiredService
from devp2p.utils import colors, COLOR_END
from devp2p import app_helper

import ethereum.slogging as slogging


slogging.configure(config_string=':debug,p2p.discovery:info')
logger = slogging.get_logger('guardian')

_nonce = 0


#
#  Serializable object
#
class Bet(rlp.Serializable):
    fields = [
        ('message', rlp.sedes.binary),
        ('counter', rlp.sedes.big_endian_int),
    ]

    def __init__(self, message, counter):
        assert isinstance(message, six.binary_type)
        assert isinstance(counter, six.integer_types)
        super(Bet, self).__init__(message, counter)

    @property
    def hash(self):
        return sha3(rlp.encode(self))

    def __repr__(self):
        return '<%s(%s:%s)>' % (self.__class__.__name__, self.message, self.counter)


#
# Protocol
#
class GuardianProtocol(BaseProtocol):
    protocol_id = 1
    network_id = 0
    max_cmd_id = 1  # Actually max id is 0, but 0 is the special value.
    name = 'guardian'
    version = 1

    def __init__(self, peer, service):
        # required by P2PProtocol
        self.config = peer.config
        BaseProtocol.__init__(self, peer, service)

    class bet(BaseProtocol.command):
        """
        message sending a bet and a nonce
        """
        cmd_id = 0

        structure = [
            ('bet', Bet)
        ]

#
#  Service
#
class GuardianService(WiredService):

    # required by BaseService
    name = 'guardianservice'
    #default_config = {
    #    'guardian': {
    #        'num_participants': 1,
    #    }
    #}
    default_config = dict(guardian=dict(num_participants=1))

    # required by WiredService
    wire_protocol = GuardianProtocol

    def __init__(self, app):
        self.config = app.config
        self.address = privtopub_raw(self.config['node']['privkey_hex'].decode('hex'))
        super(GuardianService, self).__init__(app)

    def log(self, text, **kargs):
        node_num = self.config['node_num']
        msg = ' '.join([
            colors[node_num % len(colors)],
            "NODE%d" % node_num,
            text,
            (' %r' % kargs if kargs else ''),
            COLOR_END])
        logger.debug(msg)

    def broadcast(self, obj, origin=None):
        fmap = {Bet: 'bet'}
        self.log('broadcasting', obj=obj)
        bcast = self.app.services.peermanager.broadcast
        bcast(GuardianProtocol, fmap[type(obj)], args=(obj,),
              exclude_peers=[origin.peer] if origin else [])

    def on_wire_protocol_stop(self, proto):
        assert isinstance(proto, self.wire_protocol)
        self.log('----------------------------------')
        self.log('on_wire_protocol_stop', proto=proto)

    def on_wire_protocol_start(self, proto):
        self.log('----------------------------------')
        self.log('on_wire_protocol_start', proto=proto, peers=self.app.services.peermanager.peers)
        assert isinstance(proto, self.wire_protocol)
        # register callbacks
        proto.receive_bet_callbacks.append(self.on_receive_bet)
        self.send_bet('initializing')

    def on_receive_bet(self, proto, bet):
        print "====================got it===================="
        assert isinstance(bet, Bet)
        assert isinstance(proto, self.wire_protocol)
        self.log('----------------------------------')
        self.log('on_receive bet', bet=bet, proto=proto)
        self.send_bet('received: {0}'.format(bet.message))

    counter = 0

    def send_bet(self, message):
        # without this we hit a race condition between our nodes.
        gevent.sleep(random.random())
        bet = Bet(message=message, counter=self.counter)
        self.counter += 1
        self.log('----------------------------------')
        self.log('sending bet', bet=bet)
        self.broadcast(bet)


#
#  App
#
guardian_client_name = "guardianapp"
guardian_version = '0.1'
guardian_client_version = ''.join((
    guardian_version,
    sys.platform,
    'py{:d}.{:d}.{:d}'.format(*sys.version_info[:3]),
))
guardian_client_version_string = '{:s}/v{:s}'.format(
    guardian_client_name,
    guardian_client_version,
)

guardian_default_config = copy.deepcopy(BaseApp.default_config)
guardian_default_config.update({
    'client_version_string': guardian_client_version_string,
    'post_app_start_callback': None,
})


class GuardianApp(BaseApp):
    client_name = guardian_client_name
    version = guardian_version
    client_version = guardian_client_version
    client_version_string = guardian_client_version_string

    default_config = guardian_default_config


def test_networking():
    app_helper.run(GuardianApp, GuardianService)
    import ipdb; ipdb.set_trace()
