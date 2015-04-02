import os
import pytest
import json
import pyethereum.blocks as blocks
import rlp
from rlp.utils import encode_hex
import pyethereum.utils as utils
from pyethereum.testutils import fixture_to_bytes
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
    for k in ('genesis_rlp_hex', 'genesis_state_root', 'genesis_hash'):
        assert k in genesis_fixture
    return fixture_to_bytes(genesis_fixture)


def test_genesis_state_root(genesis_fixture):
    genesis = blocks.genesis(new_db())
    assert encode_hex(genesis.state_root) == genesis_fixture['genesis_state_root']


def test_genesis_initial_alloc(genesis_fixture):
    genesis = blocks.genesis(new_db())
    for k, v in list(blocks.GENESIS_INITIAL_ALLOC.items()):
        assert genesis.get_balance(k) == v.get("balance", 0) or v.get("wei", 0)


def test_genesis_hash(genesis_fixture):
    genesis = blocks.genesis(new_db())
    assert genesis.hex_hash() == genesis_fixture['genesis_hash']


if __name__ == '__main__':
    print('current genesis:', blocks.genesis(new_db()).hex_hash())
