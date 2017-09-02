import pytest
from ethereum import utils
from ethereum.tools import tester
from ethereum.tests.utils import new_db
from ethereum.db import EphemDB
from ethereum.hybrid_casper import casper_utils
from ethereum.hybrid_casper.casper_utils import mk_prepare, mk_commit
from ethereum.slogging import get_logger
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

# Helper function for gettting blockhashes by epoch, based on the current chain
def epoch_blockhash(t, epoch):
    if epoch == 0:
        return b'\x00' * 32
    return t.head_state.prev_headers[epoch*EPOCH_LENGTH * -1 - 1].hash

# Mines blocks required for number_of_epochs epoch changes, plus an offset of 2 blocks
def mine_epochs(t, number_of_epochs):
    distance_to_next_epoch = (EPOCH_LENGTH - t.head_state.block_number) % EPOCH_LENGTH
    number_of_blocks = distance_to_next_epoch + EPOCH_LENGTH*(number_of_epochs-1) + 2
    return t.mine(number_of_blocks=number_of_blocks)

def get_recommended_casper_msg_contents(casper, validator_indexes):
    prev_commit_epochs = dict()
    for i in validator_indexes:
        prev_commit_epochs[i] = casper.get_validators__prev_commit_epoch(i)
    return \
        casper.get_current_epoch(), casper.get_recommended_ancestry_hash(), \
        casper.get_recommended_source_epoch(), casper.get_recommended_source_ancestry_hash(), prev_commit_epochs

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
    """" [L & R are checkpoints. Ex: L3_5 is local chain, 5th epoch, with 4 stake weight]
    Local: L3_5, L4_2
    add
    Remote: R3_5, R5_2  CHANGE_HEAD
    """
    keys = tester.keys[:5]
    validator_indexes = list(range(0, 5))
    t, casper = init_multi_validator_chain_and_casper(keys)
    # L3_5: Prepare and commit all
    _e, _a, _se, _sa, _pce = get_recommended_casper_msg_contents(casper, validator_indexes)
    for i, k in enumerate(keys):
        casper.prepare(mk_prepare(i, _e, _a, _se, _sa, k))
        t.mine()
    for i, k in enumerate(keys):
        casper.commit(mk_commit(i, _e, _a, _pce[i], k))
        t.mine()
    root_hash = t.mine().hash
    # L4_1: Prepare all, commit 2
    mine_epochs(t, 1)
    _e, _a, _se, _sa, _pce = get_recommended_casper_msg_contents(casper, validator_indexes)
    for i, k in enumerate(keys):
        casper.prepare(mk_prepare(i, _e, _a, _se, _sa, k))
        t.mine()
    casper.commit(mk_commit(0, _e, _a, _pce[0], keys[0]))
    casper.commit(mk_commit(1, _e, _a, _pce[1], keys[1]))
    L = t.mine()
    assert t.chain.head_hash == L.hash
    t.change_head(root_hash)
    # R5_1: Prepare all except v0, commit 1 -- Head will not change even with longer PoW chain
    mine_epochs(t, 2)
    _e, _a, _se, _sa, _pce = get_recommended_casper_msg_contents(casper, validator_indexes)
    for i, k in enumerate(keys[1:], 1):
        casper.prepare(mk_prepare(i, _e, _a, _se, _sa, k))
        t.mine()
    casper.commit(mk_commit(1, _e, _a, _pce[1], keys[1]))
    t.mine()
    assert t.chain.head_hash == L.hash
    casper.commit(mk_commit(2, _e, _a, _pce[2], keys[2]))
    R = t.mine()
    assert t.chain.head_hash == R.hash
    # The head switched to R becasue it has 7 commits as opposed to 6

def test_head_change_to_longest_known_checkpoint_chain(db):
    """"
    Test that when we change to a new checkpoint, we use the longest chain known that
    derives from that checkpoint

    Chain0: 3A_5, 4A_2,                 HEAD_CHANGE
    add
    Chain1:             5B_2,           HEAD_CHANGE
    add
    Chain2:       4A_2,                 HEAD_CHANGE
    """
    keys = tester.keys[:5]
    validator_indexes = list(range(0, 5))
    t, casper = init_multi_validator_chain_and_casper(keys)
    # 3A_5: Prepare and commit all
    _e, _a, _se, _sa, _pce = get_recommended_casper_msg_contents(casper, validator_indexes)
    for i, k in enumerate(keys):
        casper.prepare(mk_prepare(i, _e, _a, _se, _sa, k))
        t.mine()
    for i, k in enumerate(keys):
        casper.commit(mk_commit(i, _e, _a, _pce[i], k))
        t.mine()
    root_hash = t.mine().hash
    # 4A_2: Prepare all, commit 2
    mine_epochs(t, 1)
    _e, _a, _se, _sa, _pce = get_recommended_casper_msg_contents(casper, validator_indexes)
    for i, k in enumerate(keys):
        casper.prepare(mk_prepare(i, _e, _a, _se, _sa, k))
        t.mine()
    casper.commit(mk_commit(0, _e, _a, _pce[0], keys[0]))
    casper.commit(mk_commit(1, _e, _a, _pce[1], keys[1]))
    chain0_4A_1 = t.mine()
    # Mine 5 more blocks to create a longer chain
    chain0_4A_1_longest = t.mine(5)
    assert t.chain.head_hash == chain0_4A_1_longest.hash
    t.change_head(root_hash)
    # 5B_2: Prepare all except v0, commit 2 -- Head will change
    mine_epochs(t, 2)
    _e, _a, _se, _sa, _pce = get_recommended_casper_msg_contents(casper, validator_indexes)
    for i, k in enumerate(keys[1:], 1):
        casper.prepare(mk_prepare(i, _e, _a, _se, _sa, k))
        t.mine()
    casper.commit(mk_commit(1, _e, _a, _pce[1], keys[1]))
    t.mine()
    assert t.chain.head_hash == chain0_4A_1_longest.hash
    casper.commit(mk_commit(2, _e, _a, _pce[2], keys[2]))
    chain1_5B_2 = t.mine()
    # Make sure the head switches to chain1 becasue it has 7 commits as opposed to 6
    assert t.chain.head_hash == chain1_5B_2.hash
    # Now add a commit to chain0_4A_1, but make sure it's not the longest PoW chain
    t.change_head(chain0_4A_1.hash)
    _e, _a, _se, _sa, _pce = get_recommended_casper_msg_contents(casper, validator_indexes)
    casper.commit(mk_commit(3, _e, _a, _pce[3], keys[3]))
    chain0_4A_2 = t.mine()
    casper.commit(mk_commit(4, _e, _a, _pce[4], keys[4]))
    chain0_4A_2 = t.mine()
    # Check to see that the head is in fact the longest PoW chain, not this fork with the recent commit
    assert t.chain.head_hash != chain0_4A_2.hash
    assert t.chain.head_hash == chain0_4A_1_longest.hash


def t2est_head_change_for_more_commits_on_different_forks(db):
    """" [L & R are checkpoints. Ex: L3_5 is local chain, 5th epoch, with 4 stake weight]
    Local: L3_5, L4_1
    add
    Remote: R3_5, R5_1
    add
    Remote Fork: R3_5, RF5_1
    """
    keys = tester.keys[:5]
    t, casper = init_multi_validator_chain_and_casper(keys)
    epoch_1_anchash = utils.sha3(epoch_blockhash(t, 1) + epoch_blockhash(t, 0))
    epoch_2_anchash = utils.sha3(epoch_blockhash(t, 2) + epoch_1_anchash)
    # L3_5: Prepare and commit all
    for i, k in enumerate(keys):
        casper.prepare(mk_prepare(i, 3, epoch_2_anchash, 2, epoch_2_anchash, k))
        t.mine()
    for i, k in enumerate(keys):
        casper.commit(mk_commit(i, 3, epoch_blockhash(t, 3), 2 if i == 0 else 0, k))
        t.mine()
    epoch_3_anchash = utils.sha3(epoch_blockhash(t, 3) + epoch_2_anchash)
    root_hash = t.mine().hash
    # L4_1: Prepare all, commit 1
    mine_epochs(t, 1)
    for i, k in enumerate(keys):
        casper.prepare(mk_prepare(i, 4, epoch_3_anchash, 3, epoch_3_anchash, k))
        t.mine()
    casper.commit(mk_commit(0, 4, epoch_blockhash(t, 4), 3, keys[0]))
    L = t.mine()
    assert t.chain.head_hash == L.hash
    t.change_head(root_hash)
    # R5_1: Prepare all except v0, commit 1 -- Head will not change even with longer PoW chain
    mine_epochs(t, 2)
    for i, k in enumerate(keys[1:], 1):
        casper.prepare(mk_prepare(i, 5, epoch_3_anchash, 3, epoch_3_anchash, k))
        fork_hash = t.mine().hash
    casper.commit(mk_commit(1, 5, epoch_blockhash(t, 5), 3, keys[1]))
    t.mine()
    assert t.chain.head_hash == L.hash
    # RF5_1: Commit 1 -- Head will change because of extra commit; however not all commits will be present in state
    t.change_head(fork_hash)
    casper.commit(mk_commit(2, 5, epoch_blockhash(t, 5), 3, keys[2]))
    RF = t.mine(2)
    assert t.chain.head_hash == RF.hash

def t2est_head_change_for_more_commits_on_parent_fork(db):
    """"
    Test that all commits from parent checkpoints are counted, even if they exist
    on different forks.

    Chain0: 3A_5, 4A_1, 5A_1            HEAD_CHANGE
    add
    Chain1:       4A_1                  NO_CHANGE
    add
    Chain2: 3A_5,             7A_2      NO_CHANGE
    add
    Chain3:                   7A_1      HEAD_CHANGE
    """
    keys = tester.keys[:5]
    t, casper = init_multi_validator_chain_and_casper(keys)
    epoch_1_anchash = utils.sha3(epoch_blockhash(t, 1) + epoch_blockhash(t, 0))
    epoch_2_anchash = utils.sha3(epoch_blockhash(t, 2) + epoch_1_anchash)
    # 3A_5: Prepare and commit all
    for i, k in enumerate(keys):
        casper.prepare(mk_prepare(i, 3, epoch_2_anchash, 2, epoch_2_anchash, k))
        t.mine()
    for i, k in enumerate(keys):
        casper.commit(mk_commit(i, 3, epoch_blockhash(t, 3), 2 if i == 0 else 0, k))
        t.mine()
    epoch_3_anchash = utils.sha3(epoch_blockhash(t, 3) + epoch_2_anchash)
    root_hash = t.mine().hash
    # 4A_1: Prepare all, commit 1
    mine_epochs(t, 1)
    for i, k in enumerate(keys):
        casper.prepare(mk_prepare(i, 4, epoch_3_anchash, 3, epoch_3_anchash, k))
        t.mine()
    casper.commit(mk_commit(0, 4, epoch_blockhash(t, 4), 3, keys[0]))
    epoch_4_anchash = utils.sha3(epoch_blockhash(t, 4) + epoch_3_anchash)
    chain0_4A = t.mine()
    # 5A_1: Prepare all, commit 1
    mine_epochs(t, 1)
    for i, k in enumerate(keys):
        casper.prepare(mk_prepare(i, 5, epoch_4_anchash, 4, epoch_4_anchash, k))
        t.mine()
    casper.commit(mk_commit(0, 5, epoch_blockhash(t, 5), 4, keys[0]))
    chain0 = t.mine()
    assert t.chain.head_hash == chain0.hash
    # Chain1: On a different fork, add another commit for 4A
    t.change_head(chain0_4A.hash)
    casper.commit(mk_commit(1, 4, epoch_blockhash(t, 4), 3, keys[1]))
    t.mine()
    assert t.chain.head_hash == chain0.hash
    # Chain2: Build a new fork which will eventually be chosen after recieving 3 commits
    t.change_head(root_hash)
    # 7A_2: Prepare all except v0, commit 2 -- Head will not change because of 4A_2
    mine_epochs(t, 4)
    for i, k in enumerate(keys[1:], 1):
        casper.prepare(mk_prepare(i, 7, epoch_3_anchash, 3, epoch_3_anchash, k))
        t.mine().hash
    chain2_7A = t.mine()
    casper.commit(mk_commit(1, 7, epoch_blockhash(t, 7), 3, keys[1]))
    t.mine()
    casper.commit(mk_commit(2, 7, epoch_blockhash(t, 7), 3, keys[2]))
    chain2_longest = t.mine()
    assert t.chain.head_hash == chain0.hash
    # 7A_1: Add one more commit on a fork which will now be enough to change the head
    t.change_head(chain2_7A.hash)
    casper.commit(mk_commit(3, 7, epoch_blockhash(t, 7), 3, keys[3]))
    t.mine(number_of_blocks=2)
    # We now choose the longest chain considering all known commits, which happens to be chain2
    assert t.chain.head_hash == chain2_longest.hash
    chain3 = t.mine()
    # We just mined one more block, and so we now switch to chain3
    assert t.chain.head_hash == chain3.hash
