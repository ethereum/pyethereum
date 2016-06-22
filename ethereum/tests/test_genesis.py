import os
import pytest
import json
import ethereum.blocks as blocks
import ethereum.testutils as testutils
from ethereum.testutils import fixture_to_bytes
import ethereum.utils as utils
from rlp.utils import encode_hex
from ethereum.tests.utils import new_env
from ethereum.slogging import get_logger
logger = get_logger()


@pytest.fixture(scope="module")
def genesis_fixture():
    """
    Read genesis block from fixtures.
    """
    genesis_fixture = None
    fn = os.path.join(testutils.fixture_path, 'BasicTests', 'genesishashestest.json')
    with open(fn, 'r') as f:
        genesis_fixture = json.load(f)
    assert genesis_fixture is not None, "Could not read genesishashtest.json from fixtures. Make sure you did 'git submodule init'!"
    # FIXME: assert that link is uptodate
    for k in ('genesis_rlp_hex', 'genesis_state_root', 'genesis_hash'):
        assert k in genesis_fixture
    return fixture_to_bytes(genesis_fixture)


@pytest.mark.xfail  # code not in sync with genesis fixtures
def test_genesis_state_root(genesis_fixture):
    genesis = blocks.genesis(new_env())
    assert encode_hex(genesis.state_root) == utils.to_string(genesis_fixture['genesis_state_root'])


def test_genesis_initial_alloc(genesis_fixture):
    env = new_env()
    genesis = blocks.genesis(env)
    for k, v in list(env.config['GENESIS_INITIAL_ALLOC'].items()):
        assert genesis.get_balance(k) == v.get("balance", 0) or v.get("wei", 0)


@pytest.mark.xfail  # code not in sync with genesis fixtures
def test_genesis_hash(genesis_fixture):
    genesis = blocks.genesis(new_env())
    assert genesis.hex_hash() == utils.to_string(genesis_fixture['genesis_hash'])


if __name__ == '__main__':
    print('current genesis:', blocks.genesis(new_env()).hex_hash())
