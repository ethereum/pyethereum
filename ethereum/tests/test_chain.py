import time
import pytest
import ethereum.messages as messages
import ethereum.transactions as transactions
import ethereum.meta as meta
from ethereum.transaction_queue import TransactionQueue
import rlp
from ethereum.utils import decode_hex, encode_hex
import ethereum.pow.ethpow as ethpow
import ethereum.utils as utils
from ethereum.pow.chain import Chain
from ethereum.db import EphemDB
from ethereum.tests.utils import new_db
from ethereum.state import State
from ethereum.block import Block
from ethereum.consensus_strategy import get_consensus_strategy
from ethereum.genesis_helpers import mk_basic_state
from ethereum.tools import tester
from ethereum.slogging import get_logger
logger = get_logger()

_db = new_db()

# from ethereum.slogging import LogRecorder, configure_logging, set_level
# config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace,eth.pb.msg:trace,eth.pb.tx:debug'
# configure_logging(config_string=config_string)


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


def mine_on_chain(chain, parent=None, transactions=[],
                  coinbase=None, timestamp=None):
    """Mine the next block on a chain.

    The newly mined block will be considered to be the head of the chain,
    regardless of its total difficulty.

    :param parent: the parent of the block to mine, or `None` to use the
                   current chain head
    :param transactions: a list of transactions to include in the new block
    :param coinbase: optional coinbase to replace ``chain.coinbase``
    """
    txqueue = TransactionQueue()
    for t in transactions:
        txqueue.add_transaction(t)
    parent_timestamp = parent.timestamp if parent else chain.state.timestamp
    hc, _ = meta.make_head_candidate(chain, txqueue, parent,
                                     timestamp or parent_timestamp + 1, coinbase or b'\x00' * 20)
    assert hc.difficulty == 1
    m = ethpow.Miner(hc)
    rounds = 100
    nonce = 0
    while True:
        bin_nonce, mix_hash = m.mine(rounds=rounds, start_nonce=nonce)
        if bin_nonce:
            break
        nonce += rounds

    hc = hc.copy(header=hc.header.copy(
        mixhash=mix_hash,
        nonce=bin_nonce,
    ))

    assert chain.add_block(hc)
    return hc


def mine_next_block(chain, coinbase=None, transactions=[]):
    block = mine_on_chain(chain, coinbase=coinbase, transactions=transactions)
    return block


def test_mining(db):
    chain = Chain({}, difficulty=1)
    assert chain.state.block_number == 0
    assert chain.state.block_difficulty == 1
    for i in range(2):
        blk = mine_next_block(chain)
        assert blk.number == i + 1


@pytest.fixture(scope="module")
def get_transaction(gasprice=0, nonce=0):
    k, v, k2, v2 = accounts()
    tx = transactions.Transaction(
        nonce, gasprice, startgas=100000,
        to=v2, value=utils.denoms.finney * 10, data=b'').sign(k)
    return tx


def test_transfer(db):
    k, v, k2, v2 = accounts()
    chain = Chain({v: {"balance": utils.denoms.ether * 1}}, difficulty=1)
    b_v = chain.state.get_balance(v)
    b_v2 = chain.state.get_balance(v2)
    value = 42
    success = chain.state.transfer_value(v, v2, value)
    assert success
    assert chain.state.get_balance(v) == b_v - value
    assert chain.state.get_balance(v2) == b_v2 + value


def test_failing_transfer(db):
    k, v, k2, v2 = accounts()
    chain = Chain({v: {"balance": utils.denoms.ether * 1}}, difficulty=1)
    b_v = chain.state.get_balance(v)
    b_v2 = chain.state.get_balance(v2)
    value = utils.denoms.ether * 2
    # should fail
    success = chain.state.transfer_value(v, v2, value)
    assert not success
    assert chain.state.get_balance(v) == b_v
    assert chain.state.get_balance(v2) == b_v2


def test_mine_block(db):
    k, v, k2, v2 = accounts()
    chain = Chain({v: {"balance": utils.denoms.ether * 1}}, difficulty=1)
    genesis_hash = chain.state.prev_headers[0].hash
    blk2 = mine_next_block(chain, coinbase=v)
    blk3 = mine_next_block(chain, coinbase=v)
    blk4 = mine_next_block(chain, coinbase=v)
    blk5 = mine_next_block(chain, coinbase=v)
    assert chain.state.get_balance(
        v) == chain.env.config['BLOCK_REWARD'] + chain.mk_poststate_of_blockhash(blk4.hash).get_balance(v)
    assert chain.state.get_balance(
        v) == chain.env.config['BLOCK_REWARD'] * 2 + chain.mk_poststate_of_blockhash(blk3.hash).get_balance(v)
    assert chain.state.get_balance(
        v) == chain.env.config['BLOCK_REWARD'] * 3 + chain.mk_poststate_of_blockhash(blk2.hash).get_balance(v)
    assert chain.state.get_balance(
        v) == chain.env.config['BLOCK_REWARD'] * 4 + chain.mk_poststate_of_blockhash(genesis_hash).get_balance(v)
    assert blk2.prevhash == genesis_hash


def test_block_serialization_with_transaction_empty_genesis(db):
    k, v, k2, v2 = accounts()
    chain = Chain({}, difficulty=1)
    tx = get_transaction(gasprice=10)  # must fail, as there is no balance
    a_blk2 = mine_next_block(chain, transactions=[tx])
    assert tx.hash not in [x.hash for x in a_blk2.transactions]
    assert len(a_blk2.transactions) == 0


def test_mine_block_with_transaction(db):
    k, v, k2, v2 = accounts()
    chain = Chain({v: {"balance": utils.denoms.ether * 1}}, difficulty=1)
    tx = get_transaction()
    blk = mine_next_block(chain, transactions=[tx])
    assert tx.hash in [x.hash for x in blk.transactions]
    assert blk.transactions[0] == tx
    assert len(blk.transactions) == 1
    assert chain.state.get_balance(v) == utils.denoms.finney * 990
    assert chain.state.get_balance(v2) == utils.denoms.finney * 10


def test_mine_block_with_transaction2(db):
    k, v, k2, v2 = accounts()
    chain = Chain({v: {"balance": utils.denoms.ether * 1}}, difficulty=1)
    genesis_hash = chain.state.prev_headers[0].hash
    tx = get_transaction()
    blk2 = mine_next_block(chain, coinbase=v, transactions=[tx])
    assert tx in blk2.transactions
    assert tx in blk2.transactions
    assert chain.get_block(blk2.hash) == blk2
    assert tx.gasprice == 0
    assert chain.state.get_balance(
        v) == chain.env.config['BLOCK_REWARD'] + chain.mk_poststate_of_blockhash(genesis_hash).get_balance(v) - tx.value


def test_mine_block_with_transaction3(db):
    k, v, k2, v2 = accounts()
    chain = Chain({v: {"balance": utils.denoms.ether * 1}}, difficulty=1)
    tx = get_transaction()
    blk = mine_next_block(chain, transactions=[tx])
    assert tx in blk.transactions
    assert chain.state.get_balance(v) == utils.denoms.finney * 990
    assert chain.state.get_balance(v2) == utils.denoms.finney * 10


def test_transaction(db):
    k, v, k2, v2 = accounts()
    chain = Chain({v: {"balance": utils.denoms.ether * 1}}, difficulty=1)
    blk = mine_next_block(chain)
    tx = get_transaction()
    assert tx not in blk.transactions
    messages.apply_transaction(chain.state, tx)
    assert chain.state.get_balance(v) == utils.denoms.finney * 990
    assert chain.state.get_balance(v2) == utils.denoms.finney * 10


def test_transaction_serialization():
    k, v, k2, v2 = accounts()
    tx = get_transaction()
    assert tx in set([tx])
    assert tx.hash == rlp.decode(rlp.encode(tx), transactions.Transaction).hash
    assert tx in set([tx])


def test_invalid_transaction(db):
    k, v, k2, v2 = accounts()
    chain = Chain({v2: {"balance": utils.denoms.ether * 1}}, difficulty=1)
    tx = get_transaction()
    blk = mine_next_block(chain, transactions=[tx])
    assert chain.state.get_balance(v) == 0
    assert chain.state.get_balance(v2) == utils.denoms.ether * 1
    assert tx not in blk.transactions


def test_prevhash(db):
    chain = Chain({}, difficulty=1)
    L1 = mine_on_chain(chain)
    assert chain.state.get_block_hash(0) != b'\x00' * 32
    assert chain.state.get_block_hash(1) != b'\x00' * 32
    assert chain.state.get_block_hash(2) == b'\x00' * 32


def test_genesis_chain(db):
    k, v, k2, v2 = accounts()
    chain = Chain({v: {"balance": utils.denoms.ether * 1}}, difficulty=1)
    blk = mine_on_chain(chain)
    print('blook', blk)

    assert chain.has_block(blk.hash)
    assert blk.hash in chain
    assert chain.get_block(blk.hash) == blk
    assert chain.head == blk
    assert chain.get_children(blk) == []
    assert chain.get_chain() == [blk]
    assert chain.get_block_by_number(1)
    assert not chain.get_block_by_number(2)
    assert chain.get_block_by_number(1) == blk


def test_simple_chain(db):
    k, v, k2, v2 = accounts()
    chain = Chain({v: {"balance": utils.denoms.ether * 1}}, difficulty=1)
    tx = get_transaction()
    blk2 = mine_next_block(chain, transactions=[tx])
    blk3 = mine_next_block(chain)

    assert blk2.hash in chain
    assert blk3.hash in chain
    assert chain.has_block(blk2.hash)
    assert chain.has_block(blk3.hash)
    assert chain.get_block(blk2.hash) == blk2
    assert chain.get_block(blk3.hash) == blk3
    assert chain.head == blk3
    assert chain.get_children(blk2) == [blk3]

    assert chain.get_chain() == [blk2, blk3]

    assert chain.get_block_by_number(1) == blk2
    assert chain.get_block_by_number(2) == blk3
    assert not chain.get_block_by_number(3)
    assert chain.get_tx_position(tx.hash) == (blk2.number, 0)


def test_add_side_chain(db, alt_db):
    """"
    Local: L0, L1, L2
    add
    Remote: R0, R1
    """
    k, v, k2, v2 = accounts()
    # Remote: mine one block
    chainR = Chain({v: {"balance": utils.denoms.ether * 1}}, difficulty=1)
    tx0 = get_transaction(nonce=0)
    R1 = mine_next_block(chainR, transactions=[tx0])
    assert tx0.hash in [x.hash for x in R1.transactions]

    # Local: mine two blocks
    chainL = Chain({v: {"balance": utils.denoms.ether * 1}}, difficulty=1)
    tx0 = get_transaction(nonce=0)
    L1 = mine_next_block(chainL, transactions=[tx0])
    tx1 = get_transaction(nonce=1)
    L2 = mine_next_block(chainL, transactions=[tx1])

    # receive serialized remote blocks, newest first
    rlp_blocks = [rlp.encode(R1)]
    for rlp_block in rlp_blocks:
        block = rlp.decode(rlp_block, Block)
        chainL.add_block(block)

    assert L2.hash in chainL
    assert chainL.head == L2


def test_add_longer_side_chain(db, alt_db):
    """"
    Local: L0, L1, L2
    Remote: R0, R1, R2, R3
    """
    k, v, k2, v2 = accounts()
    # Remote: mine three blocks
    chainR = Chain({v: {"balance": utils.denoms.ether * 1}}, difficulty=1)
    remote_blocks = []
    for i in range(3):
        tx = get_transaction(nonce=i)
        blk = mine_next_block(chainR, transactions=[tx])
        remote_blocks.append(blk)
    # Local: mine two blocks
    chainL = Chain({v: {"balance": utils.denoms.ether * 1}}, difficulty=1)
    tx0 = get_transaction(nonce=0)
    L1 = mine_next_block(chainL, transactions=[tx0])
    tx1 = get_transaction(nonce=1)
    L2 = mine_next_block(chainL, transactions=[tx1])

    # receive serialized remote blocks, newest first
    rlp_blocks = [rlp.encode(x) for x in remote_blocks]
    for rlp_block in rlp_blocks:
        block = rlp.decode(rlp_block, Block)
        chainL.add_block(block)

    assert chainL.head == remote_blocks[-1]


def test_reward_uncles(db):
    """
    B0 B1 B2
    B0 Uncle

    We raise the block's coinbase account by Rb, the block reward,
    and also add uncle and nephew rewards
    """
    k, v, k2, v2 = accounts()
    chain = Chain({}, difficulty=1)
    blk0 = mine_on_chain(chain, coinbase=decode_hex('0' * 40))
    local_coinbase = decode_hex('1' * 40)
    uncle_coinbase = decode_hex('2' * 40)
    # Mine the uncle
    uncle = mine_on_chain(chain, blk0, coinbase=uncle_coinbase)
    assert chain.state.get_balance(
        uncle_coinbase) == 1 * chain.env.config['BLOCK_REWARD']
    # Mine the first block in the "intended main chain"
    blk1 = mine_on_chain(chain, blk0, coinbase=local_coinbase)
    # next block should reward uncles
    blk2 = mine_on_chain(chain, blk1, coinbase=local_coinbase)
    # print [x.hash for x in chain.get_chain()], [blk0.hash, uncle.hash,
    # blk1.hash, blk2.hash]
    assert blk1.hash in chain
    assert uncle.header.hash in [u.hash for u in blk2.uncles]
    assert chain.head == blk2
    assert chain.get_chain() == [blk0, blk1, blk2]
    assert chain.state.get_balance(local_coinbase) == \
        2 * chain.env.config['BLOCK_REWARD'] + \
        chain.env.config['NEPHEW_REWARD']
    assert chain.state.get_balance(
        uncle_coinbase) == chain.env.config['BLOCK_REWARD'] * 7 // 8


def test_genesis_from_state_snapshot():
    """
    Test if Chain could be initilaized from State snapshot
    """
    # Customize a state
    k, v, k2, v2 = accounts()
    alloc = {v: {"balance": utils.denoms.ether * 1}}
    state = mk_basic_state(alloc, None)
    state.block_difficulty = 1

    # Initialize another chain from state.to_snapshot()
    genesis = state.to_snapshot()
    new_chain = Chain(genesis=genesis)
    assert new_chain.state.trie.root_hash == state.trie.root_hash
    assert new_chain.state.block_difficulty == state.block_difficulty
    assert new_chain.head.number == state.block_number


def test_process_time_queue():
    """
    Test Chain.process_time_queue
    """
    # Arrange testing data blk0
    k, v, k2, v2 = accounts()
    chain = Chain({}, difficulty=1)
    blk0 = mine_on_chain(chain, coinbase=decode_hex('0' * 40))
    hash0 = chain.head.hash
    blk1 = mine_on_chain(chain, coinbase=decode_hex('0' * 40))
    hash1 = chain.head.hash

    # Act on chain2
    chain2 = Chain({}, difficulty=1)
    chain2.time_queue.insert(0, blk0)
    assert len(chain2.time_queue) == 1

    # Not reach time threshold, process_time_queue doesn't call add_block
    chain2.process_time_queue(new_time=0)
    assert len(chain2.time_queue) == 1
    assert chain2.head.hash != chain.head.hash

    # Reach time threshold, process_time_queue calls add_block
    chain2.process_time_queue(new_time=time.time() + 10)
    assert len(chain2.time_queue) == 0
    assert chain2.head.hash == hash0

    # If new_time is None, use time.time()
    chain2.time_queue.insert(1, blk1)
    chain2.process_time_queue()
    assert len(chain2.time_queue) == 0
    assert chain2.head.hash == hash1

def test_get_blockhashes_from_hash():
    test_chain = tester.Chain()
    test_chain.mine(5)

    blockhashes = test_chain.chain.get_blockhashes_from_hash(
         test_chain.chain.get_block_by_number(5).hash,
         2,
    )
    assert len(blockhashes) == 2


def test_get_blockhash_by_number():
    test_chain = tester.Chain()
    test_chain.mine(2)

    test_chain.chain.get_blockhash_by_number(2) == test_chain.chain.head.hash


# TODO ##########################################
#
# test for remote block with invalid transaction
# test for multiple transactions from same address received
#    in arbitrary order mined in the same block


# test_db = None
# test_transfer = None
# test_failing_transfer = None
# test_transient_block = None
# test_genesis = None
# test_deserialize = None
# test_deserialize_commit = None
# test_genesis_db = None
# test_mine_block = None
# test_mine_block_with_transaction = None
# test_block_serialization_with_transaction_empty_genesis = None
# test_mine_block_with_transaction = None
# test_block_serialization_same_db = None
# test_block_serialization_other_db = None
# test_block_serialization_with_transaction_other_db = None
# test_transaction = None
# test_transaction_serialization = None
# test_mine_block_with_transaction = None
# test_invalid_transaction = None
# test_prevhash = None
# test_genesis_chain = None
# test_simple_chain = None
# test_add_side_chain = None
# test_add_longer_side_chain = None
# test_reward_uncles = None
