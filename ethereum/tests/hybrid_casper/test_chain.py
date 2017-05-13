import pytest
from ethereum import utils
from ethereum.tools import tester2
from ethereum.tests.utils import new_db
from ethereum.db import EphemDB
from ethereum.hybrid_casper import casper_utils
# from ethereum.hybrid_casper.casper_utils import mk_prepare, mk_commit, mk_status_flicker
from ethereum.slogging import get_logger
logger = get_logger()

_db = new_db()

# from ethereum.slogging import configure_logging
# config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace,eth.pb.msg:trace,eth.pb.tx:debug'
# configure_logging(config_string=config_string)

EPOCH_LENGTH = 23
SLASH_DELAY = 864
ALLOC = {a: {'balance': 5*10**19} for a in tester2.accounts[:10]}
k0, k1, k2, k3, k4, k5, k6, k7, k8, k9 = tester2.keys[:10]
a0, a1, a2, a3, a4, a5, a6, a7, a8, a9 = tester2.accounts[:10]


@pytest.fixture(scope='function')
def db():
    return EphemDB()
alt_db = db


@pytest.fixture(scope="module")
def accounts():
    k = utils.sha3(b'cow')
    v = utils.privtoaddr(k)
    k2 = utils.sha3(b'horse')
    v2 = utils.privtoaddr(k2)
    return k, v, k2, v2


def init_chain_and_casper():
    genesis = casper_utils.make_casper_genesis(k0, ALLOC, EPOCH_LENGTH, SLASH_DELAY)
    casper_address = utils.mk_contract_address(a0, genesis.get_nonce(a0) - 1)
    t = tester2.Chain(genesis=genesis)
    casper = tester2.ABIContract(t, casper_utils.casper_abi, casper_address)
    casper.initiate()
    t.mine()
    return t, casper

# Helper function for gettting blockhashes by epoch, based on the current chain
def epoch_blockhash(t, epoch):
    if epoch == 0:
        return b'\x00' * 32
    return t.head_state.prev_headers[epoch*EPOCH_LENGTH * -1 - 1].hash

# Mines blocks required for number_of_epochs epoch changes, plus an offset of 2 blocks
def mine_epochs(t, number_of_epochs):
    distance_to_next_epoch = (EPOCH_LENGTH - t.head_state.block_number) % EPOCH_LENGTH
    number_of_blocks = distance_to_next_epoch + EPOCH_LENGTH*(number_of_epochs-1) + 2
    t.mine(number_of_blocks=number_of_blocks)

def test_mining(db):
    t, casper = init_chain_and_casper()
    assert t.chain.state.block_number == 1
    assert t.chain.state.block_difficulty == 1
    for i in range(2):
        t.mine()
        assert t.chain.state.block_number == i + 2

def test_mine_block(db):
    t, casper = init_chain_and_casper()
    genesis = t.mine(coinbase=a1)
    blk2 = t.mine(coinbase=a1)
    blk3 = t.mine(coinbase=a1)
    blk4 = t.mine(coinbase=a1)
    t.mine(coinbase=a1)
    assert t.chain.state.get_balance(a1) == t.chain.env.config['BLOCK_REWARD'] + t.chain.mk_poststate_of_blockhash(blk4.hash).get_balance(a1)
    assert t.chain.state.get_balance(a1) == t.chain.env.config['BLOCK_REWARD'] * 2 + t.chain.mk_poststate_of_blockhash(blk3.hash).get_balance(a1)
    assert t.chain.state.get_balance(a1) == t.chain.env.config['BLOCK_REWARD'] * 3 + t.chain.mk_poststate_of_blockhash(blk2.hash).get_balance(a1)
    assert t.chain.state.get_balance(a1) == t.chain.env.config['BLOCK_REWARD'] * 4 + t.chain.mk_poststate_of_blockhash(genesis.hash).get_balance(a1)
    assert blk2.prevhash == genesis.hash
