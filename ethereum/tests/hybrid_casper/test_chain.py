import pytest
from ethereum.tools import tester
from ethereum.tests.utils import new_db
from ethereum.db import EphemDB
from ethereum.hybrid_casper import casper_utils
from ethereum.slogging import get_logger
from ethereum.tests.hybrid_casper.testing_lang import TestLangHybrid
log = get_logger('test.chain')
logger = get_logger()

_db = new_db()

# from ethereum.slogging import configure_logging
# config_string = ':info,eth.chain:debug,test.chain:info'
# configure_logging(config_string=config_string)

EPOCH_LENGTH = 25
SLASH_DELAY = 864
ALLOC = {a: {'balance': 500*10**19} for a in tester.accounts[:10]}
k0, k1, k2, k3, k4, k5, k6, k7, k8, k9 = tester.keys[:10]
a0, a1, a2, a3, a4, a5, a6, a7, a8, a9 = tester.accounts[:10]


@pytest.fixture(scope='function')
def db():
    return EphemDB()
alt_db = db

def init_chain_and_casper():
    genesis = casper_utils.make_casper_genesis(ALLOC, EPOCH_LENGTH, 100, 0.02, 0.002)
    t = tester.Chain(genesis=genesis)
    casper = tester.ABIContract(t, casper_utils.casper_abi, t.chain.config['CASPER_ADDRESS'])
    return t, casper

def init_multi_validator_chain_and_casper(validator_keys):
    t, casper = init_chain_and_casper()
    mine_epochs(t, 1)
    for k in validator_keys:
        casper_utils.induct_validator(t, casper, k, 200 * 10**18)
        t.mine()
    mine_epochs(t, 2)
    assert casper.get_dynasty() == 3
    return t, casper

# Mines blocks required for number_of_epochs epoch changes, plus an offset of 2 blocks
def mine_epochs(t, number_of_epochs):
    distance_to_next_epoch = (EPOCH_LENGTH - t.head_state.block_number) % EPOCH_LENGTH
    number_of_blocks = distance_to_next_epoch + EPOCH_LENGTH*(number_of_epochs-1) + 2
    return t.mine(number_of_blocks=number_of_blocks)

def test_mining(db):
    t, casper = init_chain_and_casper()
    assert t.chain.state.block_number == 0
    assert t.chain.state.block_difficulty == 1
    for i in range(2):
        t.mine()
        assert t.chain.state.block_number == i + 1

def test_mining_block_rewards(db):
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

def test_simple_chain(db):
    t, casper = init_chain_and_casper()
    t.tx(k0, a1, 20, gasprice=0)
    blk2 = t.mine()
    blk3 = t.mine()
    assert blk2.hash in t.chain
    assert blk3.hash in t.chain
    assert t.chain.has_block(blk2.hash)
    assert t.chain.has_block(blk3.hash)
    assert t.chain.get_block(blk2.hash) == blk2
    assert t.chain.get_block(blk3.hash) == blk3
    assert t.chain.head == blk3
    assert t.chain.get_children(blk2) == [blk3]
    assert t.chain.get_chain() == [blk2, blk3]
    assert t.chain.get_block_by_number(1) == blk2
    assert t.chain.get_block_by_number(2) == blk3
    assert not t.chain.get_block_by_number(3)

def test_head_change_for_longer_pow_chain(db):
    """" [L & R are blocks]
    Local: L0, L1
    add
    Remote: R0, R1, R2
    """
    t, casper = init_chain_and_casper()
    t.mine()
    root_hash = t.chain.head_hash
    L = t.mine(2)
    assert t.chain.head_hash == L.hash
    t.change_head(root_hash)
    R = t.mine(2)
    # Test that we just need one more block before the head switches
    assert t.chain.head_hash == L.hash
    R = t.mine(1)
    assert t.chain.head_hash == R.hash

def test_head_change_for_more_commits(db):
    """ This tests that the chain does not change head unless there are more commits on the alternative fork """
    test_string = 'B J0 J1 J2 J3 B B S0 B P0 P1 P2 P3 B1 C0 C1 B1 S1 R0 B B H1 P0 P1 P2 P3 B1 C0 C1 B1 H1 C2 B1 S2 H2'
    test = TestLangHybrid(test_string, 15, 100, 0.02, 0.002)
    test.parse()

def test_double_prepare_slash(db):
    """ This tests that the chain does not change head unless there are more commits on the alternative fork """
    test_string = 'B J0 B B S0 B P0 B1 C0 B1 R0 B P0 B1 C0 B1 X0 B J1 J2 B B P1 P2 B1 C1 C2 B P1 P2 B1 C1 C2 B1'
    test = TestLangHybrid(test_string, 15, 100, 0.02, 0.002)
    test.parse()

def test_commit_consistency_slash_with_violating_prepare(db):
    """ This tests that the chain does not change head unless there are more commits on the alternative fork """
    test_string = 'B J0 B B S0 B P0 B1 C0 B1 R0 B B B P0 B1 C0 B1 X0 B1'
    test = TestLangHybrid(test_string, 15, 100, 0.02, 0.002)
    test.parse()

def test_commit_consistency_slash_with_violating_commit(db):
    """ This tests that the chain does not change head unless there are more commits on the alternative fork """
    test_string = 'B J0 B B S0 B B B P0 B1 R0 B P0 B1 C0 B1 X0 B1'
    test = TestLangHybrid(test_string, 15, 100, 0.02, 0.002)
    test.parse()

def test_long_range_forks(db):
    """ This tests that the chain is efficient even when forks are very long range """
    test_string = 'B J0 J1 J2 B B S0 B B B B B B B B P0 P1 P2 B1 C0 B1 R0 B B B B B B B B B B P0 P1 P2 B1 C0 C1 C2 B P0 P1 P2 B1 C0 C1 B1 S1 H1'
    test = TestLangHybrid(test_string, 15, 100, 0.02, 0.002)
    test.parse()
