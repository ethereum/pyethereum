import os
import pytest
import pyethereum.rlp as rlp
import pyethereum.trie as trie
import pyethereum.utils as utils
import pyethereum.packeter as packeter
import pyethereum.peer as peer
import pyethereum.signals as signals
import pyethereum.peermanager as peermanager
from pyethereum.db import DB as DB
from pyethereum.config import get_default_config
from tests.utils import new_db
from pyethereum import __version__

idec = utils.big_endian_to_int


from pyethereum.slogging import get_logger, configure_logging
logger = get_logger()
configure_logging(':trace')


class Connection(object):

    def __init__(self, remote_buffer=[], local_buffer=[]):
        self.remote_buffer = remote_buffer
        self.local_buffer = local_buffer

    def send(self, data):
        self.remote_buffer += list(data)
        return len(data)

    def recv(self, length):
        res = self.look(length)
        for i in range(min(length, len(self.local_buffer))): self.local_buffer.pop(0)
        return res

    def look(self, length):
         return ''.join(self.local_buffer[:length])

    def get_remote_connection(self):
        return Connection(self.local_buffer, self.remote_buffer)

    def shutdown(self, *args):
        logger.debug('%r shutdown %r' %(self, args))

    def close(self, *args):
        logger.debug('%r close %r' %(self, args))


class Peer(peer.Peer):

    def send_Disconnect(self, reason=None):
        logger.info('%r sending disconnect: %r' % (self, reason))
        self.send_packet(packeter.Packeter().dump_Disconnect(reason=reason))

    def _receive_Disconnect(self, reason=None):
        logger.debug('%r received Disconnect %r' %(self, reason))
        raise Exception('%r received Disconnect')

    def recv(self):
        self.recv_buffer += self.connection().recv(2048)
        self._process_recv_buffer()


def test_connection():
    l = Connection()
    r = l.get_remote_connection()
    l.send('ltest')
    r.send('rtest')
    assert l.look(2000) == 'rtest'
    assert r.look(2000) == 'ltest'
    assert l.recv(1) == 'r'
    assert l.recv(2000) == 'test'
    assert l.recv(2000) == ''
    assert r.recv(1) == 'l'
    assert r.recv(2000) == 'test'
    assert r.recv(2000) == ''
    assert l.look(2000) == ''
    assert r.look(2000) == ''
    l.send('l')
    l.send('test')
    assert r.recv(2000) == 'ltest'



@pytest.fixture(scope="module")
def get_peers():
    cnxA = Connection()
    cnxB = cnxA.get_remote_connection()
    peerA = Peer(connection=cnxA, ip='0.0.0.1', port=1)
    peerB = Peer(connection=cnxB, ip='0.0.0.2', port=2)
    signals.config_ready.send(sender=None, config=get_default_config())
    return peerA, peerB

@pytest.fixture(scope="module")
def get_packeter():
    p = packeter.Packeter()
    p.configure(get_default_config())
    return p

def test_status():
    p = get_packeter()
    total_difficulty = 1000
    head_hash = utils.sha3('head')
    genesis_hash = utils.sha3('genesis')
    msg = p.dump_Status(total_difficulty, head_hash, genesis_hash)
    success, res = p.load_packet(msg)
    assert success
    _, _, cmd, data, remain = res
    assert cmd == 'Status'
    assert idec(data[0]) == packeter.Packeter.ETHEREUM_PROTOCOL_VERSION
    assert idec(data[1]) == packeter.Packeter.NETWORK_ID
    assert idec(data[2]) == total_difficulty
    assert data[3] == head_hash
    assert data[4] == genesis_hash
    return

def test_hallo():
    peerA, peerB = get_peers()
    peerA.send_Hello()
    peerB.recv()

def test_version():
    # see documentation in _version.py on how to update
    if __version__.count('.') >= 2:
        assert str(packeter.Packeter.ETHEREUM_PROTOCOL_VERSION) in __version__
