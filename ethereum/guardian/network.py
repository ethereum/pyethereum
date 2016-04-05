import sys
import copy
import rlp
from rlp.sedes import (
    big_endian_int,
    binary,
    CountableList,
)

from devp2p.crypto import (
    privtopub as privtopub_raw,
)
from devp2p.app import BaseApp
from devp2p.protocol import BaseProtocol
from devp2p.service import WiredService
from devp2p.utils import (
    colors,
    COLOR_END,
)

import ethereum.slogging as slogging


#slogging.configure(config_string=':debug,p2p.discovery:info')
slogging.configure(config_string=':warning,p2p.discovery:info')
logger = slogging.get_logger('guardian')


NM_LIST = 0
NM_BLOCK = 1
NM_BET = 2
NM_BET_REQUEST = 3
NM_TRANSACTION = 4
NM_GETBLOCK = 5
NM_GETBLOCKS = 6
NM_BLOCKS = 7


class NetworkMessage(rlp.Serializable):
    """
    Used by validators to
    """
    fields = [
        ('typ', big_endian_int),
        ('args', CountableList(binary))
    ]

    def __init__(self, typ, args):
        self.typ = typ
        self.args = args


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

    class network_message(BaseProtocol.command):
        """
        A guardian network message
        """
        cmd_id = 0

        structure = [
            ('network_message', NetworkMessage)
        ]


#
#  Service
#
class GuardianService(WiredService):
    # required by BaseService
    name = 'guardianservice'
    default_config = {
        'guardianservice': {
            'num_participants': 1,
        }
    }

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
        self.log('broadcasting', obj=obj)
        bcast = self.app.services.peermanager.broadcast
        bcast(
            GuardianProtocol,
            'network_message',
            args=(obj,),
            exclude_peers=[origin.peer] if origin else []
        )

    def on_wire_protocol_stop(self, proto):
        assert isinstance(proto, self.wire_protocol)
        self.log('----------------------------------')
        self.log('on_wire_protocol_stop', proto=proto)

    def on_wire_protocol_start(self, proto):
        self.log('----------------------------------')
        self.log('on_wire_protocol_start', proto=proto, peers=self.app.services.peermanager.peers)
        assert isinstance(proto, self.wire_protocol)
        proto.receive_network_message_callbacks.append(
            self.on_receive_network_message
        )

    def on_receive_network_message(self, proto, network_message):
        assert isinstance(network_message, NetworkMessage)
        assert isinstance(proto, self.wire_protocol)
        self.log('----------------------------------')
        self.log('on_receive network_message', network_message=network_message, proto=proto)
        agent = self.app.services.guardianservice.config['guardianservice']['agent']
        lookup_fn = self.app.services.guardianservice.config['guardianservice']['lookup_fn']
        other_agent_id = lookup_fn(proto.peer.remote_pubkey)
        agent.on_receive(rlp.encode(network_message), other_agent_id)


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
