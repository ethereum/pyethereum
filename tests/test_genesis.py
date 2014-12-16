import os
import pytest
import json
import pyethereum.blocks as blocks
import pyethereum.rlp as rlp
import pyethereum.utils as utils
from tests.utils import new_db
from pyethereum.slogging import get_logger, configure_logging
logger = get_logger()
configure_logging(':trace')

@pytest.fixture(scope="module")
def genesis_fixture():
    """
    Read genesis block from fixtures.
    """
    genesis_fixture = None
    with open('fixtures/BasicTests/genesishashestest.json', 'r') as f:
        genesis_fixture = json.load(f)
    assert genesis_fixture is not None, "Could not read genesishashtest.json from fixtures. Make sure you did 'git submodule init'!"
    # FIXME: assert that link is uptodate
    for k in ('genesis_rlp_hex', 'genesis_state_root', 'genesis_hash', 'initial_alloc'):
        assert k in genesis_fixture
    return genesis_fixture


def test_genesis_state_root(genesis_fixture):
    genesis = blocks.genesis(new_db())
    assert genesis.state_root.encode('hex') == genesis_fixture['genesis_state_root']

def test_genesis_initial_alloc(genesis_fixture):
    genesis = blocks.genesis(new_db())
    for k, v in blocks.GENESIS_INITIAL_ALLOC.items():
        assert genesis.get_balance(k) == v

def test_genesis_hash(genesis_fixture):
    """
    py current:     7e2c3861f556686d7bc3ce4e93fa0011020868dc769838aca66bcc82010a2c60
    fixtures 15.10.:f68067286ddb7245c2203b18135456de1fc4ed6a24a2d9014195faa7900025bf
    py poc6:        08436a4d33c77e6acf013e586a3333ad152f25d31df8b68749d85046810e1f4b
    fixtures 19.9,: 08436a4d33c77e6acf013e586a3333ad152f25d31df8b68749d85046810e1f4b
    """
    genesis = blocks.genesis(new_db())
    assert genesis.hex_hash() == genesis_fixture['genesis_hash']



if __name__ == '__main__':

    cpp_genesis_rlp_hex = 'f9012ff9012aa00000000000000000000000000000000000000000000000000000000000000000a01dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d49347940000000000000000000000000000000000000000a0c67c70f5d7d3049337d1dcc0503a249881120019a8e7322774dbfe57b463718ca056e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421a056e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421b84000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000830200008080830f4240808080a004994f67dc55b09e814ab7ffc8df3686b4afb2bb53e60eae97ef043fe03fb829c0c0'
    cpp_genesis_rlp = cpp_genesis_rlp_hex.decode('hex')

    poc7_genesis_hash_hex = '955f36d073ccb026b78ab3424c15cf966a7563aa270413859f78702b9e8e22cb'
    cpp_genesis = rlp.decode(cpp_genesis_rlp) 
    cpp_genesis_hash_hex = utils.sha3(rlp.encode(cpp_genesis[0])).encode('hex')
    
    cpp_header = cpp_genesis[0]
    cpp_header_hex = [x.encode('hex') for x in cpp_header]

    py_genesis = rlp.decode(blocks.genesis().serialize())
    py_genesis_hex_hash = blocks.genesis().hex_hash()
    py_header = py_genesis[0]
    py_header_hex = [x.encode('hex') for x in py_header]

    print 'py genesis hash hex', py_genesis_hex_hash
    print 'py state_root', py_header[blocks.block_structure_rev['state_root'][0]].encode('hex')
    print 'py genesis rlp', blocks.genesis().hex_serialize()

    assert len(py_header_hex) == len(cpp_header_hex)
    assert cpp_genesis_hash_hex == poc7_genesis_hash_hex
    for i, e in enumerate(py_header_hex):
        print blocks.block_structure[i][0], repr(e)
        print blocks.block_structure[i][0], repr(cpp_header_hex[i])
        print
        assert e == cpp_header_hex[i]

    assert poc7_genesis_hash_hex == py_genesis_hex_hash
    for i in range(3):
        assert py_genesis[i] == cpp_genesis[i]

    
