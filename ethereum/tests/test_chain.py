import pytest
import ethereum.processblock as processblock
import ethereum.blocks as blocks
import ethereum.transactions as transactions
import rlp
from rlp.utils import decode_hex, encode_hex
import ethereum.miner as miner
import ethereum.utils as utils
from ethereum.chain import Chain
import ethereum.ethash_utils as ethash_utils
from ethereum.db import EphemDB
from ethereum.tests.utils import new_db

from ethereum.slogging import get_logger, configure_logging
logger = get_logger()
configure_logging('eth.vm:trace,eth.vm.memory:info')

db = EphemDB()

blocks.peck_cache(db, b'\x00' * 32, ethash_utils.get_cache_size(0))


@pytest.fixture(scope="module")
def accounts():
    k = utils.sha3(b'cow')
    v = decode_hex(utils.privtoaddr(k))
    k2 = utils.sha3(b'horse')
    v2 = decode_hex(utils.privtoaddr(k2))
    return k, v, k2, v2


@pytest.fixture(scope="module")
def mkgenesis(initial_alloc={}):
    return blocks.genesis(db, initial_alloc, difficulty=1)


def mkquickgenesis(initial_alloc={}, db=db):
    "set INITIAL_DIFFICULTY to a value that is quickly minable"
    return blocks.genesis(db, initial_alloc, difficulty=1)


def mine_next_block(parent, uncles=[], coinbase=None, transactions=[]):
    m = miner.Miner(parent, uncles, coinbase or parent.coinbase)
    for t in transactions:
        m.add_transaction(t)
    b = m.mine()
    assert b.header.check_pow()
    return b


@pytest.fixture(scope="module")
def get_transaction(gasprice=0, nonce=0):
    k, v, k2, v2 = accounts()
    tx = transactions.Transaction(
        nonce, gasprice, startgas=100000,
        to=v2, value=utils.denoms.finney * 10, data='').sign(k)
    return tx


def store_block(blk):
    blk.db.put(blk.hash, rlp.encode(blk))
    assert blocks.get_block(blk.db, blk.hash) == blk


def test_db():
    db = new_db()
    a, b = db, db
    assert a == b
    assert a.uncommitted == b.uncommitted
    a.put(b'a', b'b')
    b.get(b'a') == b'b'
    assert a.uncommitted == b.uncommitted
    a.commit()
    assert a.uncommitted == b.uncommitted
    assert b'test' not in db
    db = new_db()
    assert a != db


def test_transfer():
    db = new_db()
    k, v, k2, v2 = accounts()
    blk = blocks.genesis(db, {v: {"balance": utils.denoms.ether * 1}})
    b_v = blk.get_balance(v)
    b_v2 = blk.get_balance(v2)
    value = 42
    success = blk.transfer_value(v, v2, value)
    assert success
    assert blk.get_balance(v) == b_v - value
    assert blk.get_balance(v2) == b_v2 + value


def test_failing_transfer():
    db = new_db()
    k, v, k2, v2 = accounts()
    blk = blocks.genesis(db, {v: {"balance": utils.denoms.ether * 1}})
    b_v = blk.get_balance(v)
    b_v2 = blk.get_balance(v2)
    value = utils.denoms.ether * 2
    # should fail
    success = blk.transfer_value(v, v2, value)
    assert not success
    assert blk.get_balance(v) == b_v
    assert blk.get_balance(v2) == b_v2


def test_transient_block():
    db = new_db()
    blk = blocks.genesis(db)
    tb_blk = rlp.decode(rlp.encode(blk), blocks.TransientBlock)
    assert blk.hash == tb_blk.hash
    assert blk.number == tb_blk.number


def test_genesis():
    k, v, k2, v2 = accounts()
    db = new_db()
    blk = blocks.genesis(db, {v: {"balance": utils.denoms.ether * 1}})
    sr = blk.state_root
    assert blk.state.db.db == db.db
    db.put(blk.hash, rlp.encode(blk))
    blk.state.db.commit()
    assert sr in db
    db.commit()
    assert sr in db
    blk2 = blocks.genesis(db, {v: {"balance": utils.denoms.ether * 1}})
    blk3 = blocks.genesis(db)
    assert blk == blk2
    assert blk != blk3
    db = new_db()
    blk2 = blocks.genesis(db, {v: {"balance": utils.denoms.ether * 1}})
    blk3 = blocks.genesis(db)
    assert blk == blk2
    assert blk != blk3


def test_deserialize():
    k, v, k2, v2 = accounts()
    db = new_db()
    blk = blocks.genesis(db)
    db.put(blk.hash, rlp.encode(blk))
    assert blk == blocks.get_block(db, blk.hash)


def test_deserialize_commit():
    k, v, k2, v2 = accounts()
    db = new_db()
    blk = blocks.genesis(db)
    db.put(blk.hash, rlp.encode(blk))
    db.commit()
    assert blk == blocks.get_block(db, blk.hash)


def test_genesis_db():
    k, v, k2, v2 = accounts()
    db = new_db()
    blk = blocks.genesis(db, {v: {"balance": utils.denoms.ether * 1}})
    store_block(blk)
    blk2 = blocks.genesis(db, {v: {"balance": utils.denoms.ether * 1}})
    blk3 = blocks.genesis(db)
    assert blk == blk2
    assert blk != blk3
    db = new_db()
    blk2 = blocks.genesis(db, {v: {"balance": utils.denoms.ether * 1}})
    blk3 = blocks.genesis(db)
    assert blk == blk2
    assert blk != blk3


def test_mine_block():
    k, v, k2, v2 = accounts()
    blk = mkquickgenesis({v: {"balance": utils.denoms.ether * 1}})
    store_block(blk)
    blk2 = mine_next_block(blk, coinbase=v)
    store_block(blk2)
    assert blk2.get_balance(v) == blocks.BLOCK_REWARD + blk.get_balance(v)
    assert blk.state.db.db == blk2.state.db.db
    assert blk2.get_parent() == blk


def test_mine_block_with_transaction():
    k, v, k2, v2 = accounts()
    # mine two blocks
    a_blk = mkquickgenesis({v: {"balance": utils.denoms.ether * 1}})
    store_block(a_blk)
    tx = get_transaction()
    a_blk2 = mine_next_block(a_blk, transactions=[tx])
    assert tx in a_blk2.get_transactions()


def test_block_serialization_with_transaction_empty_genesis():
    k, v, k2, v2 = accounts()
    a_blk = mkquickgenesis({})
    store_block(a_blk)
    tx = get_transaction(gasprice=10)  # must fail, as there is no balance
    a_blk2 = mine_next_block(a_blk, transactions=[tx])
    assert tx not in a_blk2.get_transactions()


def test_mine_block_with_transaction():
    k, v, k2, v2 = accounts()
    blk = mkquickgenesis({v: {"balance": utils.denoms.ether * 1}})
    store_block(blk)
    tx = get_transaction()
    blk2 = mine_next_block(blk, coinbase=v, transactions=[tx])
    assert tx in blk2.get_transactions()
    store_block(blk2)
    assert tx in blk2.get_transactions()
    assert blocks.get_block(blk2.hash) == blk2
    assert tx.gasprice == 0
    assert blk2.get_balance(
        v) == blocks.BLOCK_REWARD + blk.get_balance(v) - tx.value
    assert blk.state.db.db == blk2.state.db.db
    assert blk2.get_parent() == blk
    assert tx in blk2.get_transactions()
    assert tx not in blk.get_transactions()


def test_block_serialization_same_db():
    k, v, k2, v2 = accounts()
    blk = mkquickgenesis({v: {"balance": utils.denoms.ether * 1}})
    db = blk.db
    assert blk.hash == rlp.decode(rlp.encode(blk), blocks.Block, db=db).hash
    store_block(blk)
    blk2 = mine_next_block(blk)
    assert blk.hash == rlp.decode(rlp.encode(blk), blocks.Block, db=db).hash
    assert blk2.hash == rlp.decode(rlp.encode(blk2), blocks.Block, db=db).hash


def test_block_serialization_other_db():
    k, v, k2, v2 = accounts()
    # mine two blocks
    a_blk = mkquickgenesis()
    store_block(a_blk)
    a_blk2 = mine_next_block(a_blk)
    store_block(a_blk2)

    # receive in other db
    b_blk = mkquickgenesis()
    assert b_blk == a_blk
    store_block(b_blk)
    b_blk2 = rlp.decode(rlp.encode(a_blk2), blocks.Block, db=b_blk.db)
    assert a_blk2.hash == b_blk2.hash
    store_block(b_blk2)
    assert a_blk2.hash == b_blk2.hash


def test_block_serialization_with_transaction_other_db():

    hx = lambda x: encode_hex(x)

    k, v, k2, v2 = accounts()
    # mine two blocks
    a_blk = mkquickgenesis({v: {"balance": utils.denoms.ether * 1}})
    store_block(a_blk)
    tx = get_transaction()
    logger.debug('a: state_root before tx %r' % hx(a_blk.state_root))
    logger.debug('a: state:\n%s' % utils.dump_state(a_blk.state))
    a_blk2 = mine_next_block(a_blk, transactions=[tx])
    logger.debug('a: state_root after tx %r' % hx(a_blk2.state_root))
    logger.debug('a: state:\n%s' % utils.dump_state(a_blk2.state))
    assert tx in a_blk2.get_transactions()
    store_block(a_blk2)
    assert tx in a_blk2.get_transactions()
    logger.debug('preparing receiving chain ---------------------')
    # receive in other db
    b_blk = mkquickgenesis({v: {"balance": utils.denoms.ether * 1}})
    store_block(b_blk)

    assert b_blk.number == 0
    assert b_blk == a_blk
    logger.debug('b: state_root before tx %r' % hx(b_blk.state_root))
    logger.debug('starting deserialization of remote block w/ tx')
    b_blk2 = rlp.decode(rlp.encode(a_blk2), blocks.Block, db=b_blk.db)
    logger.debug('b: state_root after %r' % hx(b_blk2.state_root))

    assert a_blk2.hash == b_blk2.hash

    assert tx in b_blk2.get_transactions()
    store_block(b_blk2)
    assert a_blk2.hash == b_blk2.hash
    assert tx in b_blk2.get_transactions()


def test_transaction():
    k, v, k2, v2 = accounts()
    db = new_db()
    blk = mkquickgenesis({v: {"balance": utils.denoms.ether * 1}})
    store_block(blk)
    blk = mine_next_block(blk)
    tx = get_transaction()
    assert tx not in blk.get_transactions()
    success, res = processblock.apply_transaction(blk, tx)
    assert tx in blk.get_transactions()
    assert blk.get_balance(v) == utils.denoms.finney * 990
    assert blk.get_balance(v2) == utils.denoms.finney * 10


def test_transaction_serialization():
    k, v, k2, v2 = accounts()
    tx = get_transaction()
    assert tx in set([tx])
    assert tx.hash == rlp.decode(rlp.encode(tx), transactions.Transaction).hash
    assert tx in set([tx])


def test_mine_block_with_transaction():
    k, v, k2, v2 = accounts()
    db = new_db()
    blk = mkquickgenesis({v: {"balance": utils.denoms.ether * 1}})
    store_block(blk)
    tx = get_transaction()
    blk = mine_next_block(blk, transactions=[tx])
    assert tx in blk.get_transactions()
    assert blk.get_balance(v) == utils.denoms.finney * 990
    assert blk.get_balance(v2) == utils.denoms.finney * 10


def test_invalid_transaction():
    k, v, k2, v2 = accounts()
    db = new_db()
    blk = mkquickgenesis({v2: {"balance": utils.denoms.ether * 1}})
    store_block(blk)
    tx = get_transaction()
    blk = mine_next_block(blk, transactions=[tx])
    assert blk.get_balance(v) == 0
    assert blk.get_balance(v2) == utils.denoms.ether * 1
    assert tx not in blk.get_transactions()


def test_prevhash():
    chain = Chain(db, mkquickgenesis({}))
    L1 = mine_next_block(chain.head)
    L1.get_ancestor_list(2)


def test_genesis_chain():
    k, v, k2, v2 = accounts()
    blk = mkquickgenesis({v: {"balance": utils.denoms.ether * 1}})
    chain = Chain(db=blk.db, genesis=blk)

    assert chain.has_block(blk.hash)
    assert blk.hash in chain
    assert chain.get(blk.hash) == blk
    assert chain.head == blk
    assert chain.get_children(blk) == []
    assert chain.get_uncles(blk) == []
    assert chain.get_chain() == [blk]
    assert chain.get_chain(blk.hash) == [blk]
    assert chain.get_descendants(blk, count=10) == []
    assert chain.index.has_block_by_number(0)
    assert not chain.index.has_block_by_number(1)
    assert chain.index.get_block_by_number(0) == blk.hash
    with pytest.raises(KeyError):
        chain.index.get_block_by_number(1)


def test_simple_chain():
    k, v, k2, v2 = accounts()
    blk = mkquickgenesis({v: {"balance": utils.denoms.ether * 1}})
    store_block(blk)
    chain = Chain(db=blk.db, genesis=blk)
    tx = get_transaction()
    blk2 = mine_next_block(blk, transactions=[tx])
    store_block(blk2)
    chain.add_block(blk2)

    assert blk.hash in chain
    assert blk2.hash in chain
    assert chain.has_block(blk2.hash)
    assert chain.get(blk2.hash) == blk2
    assert chain.head == blk2
    assert chain.get_children(blk) == [blk2]
    assert chain.get_uncles(blk2) == []

    assert chain.get_chain() == [blk2, blk]
    assert chain.get_chain(count=0) == []
    assert chain.get_chain(count=1) == [blk2]
    assert chain.get_chain(count=2) == [blk2, blk]
    assert chain.get_chain(count=100) == [blk2, blk]
    assert chain.get_chain(blk.hash) == [blk]
    assert chain.get_chain(blk.hash, 0) == []
    assert chain.get_chain(blk2.hash) == [blk2, blk]
    assert chain.get_chain(blk2.hash, 1) == [blk2]
    assert chain.get_descendants(blk, count=10) == [blk2]
    assert chain.get_descendants(blk, count=1) == [blk2]
    assert chain.get_descendants(blk, count=0) == []

    assert chain.index.has_block_by_number(1)
    assert not chain.index.has_block_by_number(2)
    assert chain.index.get_block_by_number(1) == blk2.hash
    with pytest.raises(KeyError):
        chain.index.get_block_by_number(2)
    assert chain.index.get_transaction(tx.hash) == (tx, blk2, 0)


@pytest.mark.xfail
def test_add_side_chain():
    """"
    Local: L0, L1, L2
    add
    Remote: R0, R1
    """
    k, v, k2, v2 = accounts()
    # Remote: mine one block
    R0 = mkquickgenesis({v: {"balance": utils.denoms.ether * 1}})
    store_block(R0)
    tx0 = get_transaction(nonce=0)
    R1 = mine_next_block(R0, transactions=[tx0])
    store_block(R1)
    assert tx0.hash in [x.hash for x in R1.get_transactions()]

    # Local: mine two blocks
    L0 = mkquickgenesis({v: {"balance": utils.denoms.ether * 1}})
    chain = Chain(db=L0.db, genesis=L0)
    tx0 = get_transaction(nonce=0)
    L1 = mine_next_block(L0, transactions=[tx0])
    chain.add_block(L1)
    tx1 = get_transaction(nonce=1)
    L2 = mine_next_block(L1, transactions=[tx1])
    chain.add_block(L2)

    # receive serialized remote blocks, newest first
    transient_blocks = [rlp.decode(rlp.encode(R0), blocks.TransientBlock),
                        rlp.decode(rlp.encode(R1), blocks.TransientBlock)]
    chain.receive_chain(transient_blocks=transient_blocks)
    assert L2.hash in chain


@pytest.mark.xfail
def test_add_longer_side_chain():
    """"
    Local: L0, L1, L2
    Remote: R0, R1, R2, R3
    """
    k, v, k2, v2 = accounts()
    # Remote: mine one block
    blk = mkquickgenesis({v: {"balance": utils.denoms.ether * 1}})
    store_block(blk)
    remote_blocks = [blk]
    for i in range(3):
        tx = get_transaction(nonce=i)
        blk = mine_next_block(remote_blocks[-1], transactions=[tx])
        store_block(blk)
        remote_blocks.append(blk)
    # Local: mine two blocks
    e = EphemDB()
    L0 = mkquickgenesis({v: {"balance": utils.denoms.ether * 1}}, db=e)
    chain = Chain(db=L0.db, genesis=L0)
    tx0 = get_transaction(nonce=0)
    L1 = mine_next_block(L0, transactions=[tx0])
    chain.add_block(L1)
    tx1 = get_transaction(nonce=1)
    L2 = mine_next_block(L1, transactions=[tx1])
    chain.add_block(L2)

    # receive serialized remote blocks, newest first
    transient_blocks = [rlp.decode(rlp.encode(b), blocks.TransientBlock)
                        for b in remote_blocks]
    chain.receive_chain(transient_blocks=transient_blocks)
    assert chain.head == remote_blocks[-1]


def test_reward_uncles():
    """
    B0 B1 B2
    B0 Uncle

    We raise the block's coinbase account by Rb, the block reward,
    and also add uncle and nephew rewards
    """
    k, v, k2, v2 = accounts()
    blk0 = mkquickgenesis()
    local_coinbase = decode_hex('1' * 40)
    uncle_coinbase = decode_hex('2' * 40)
    chain = Chain(db=blk0.db, genesis=blk0)
    blk1 = mine_next_block(blk0, coinbase=local_coinbase)
    chain.add_block(blk1)
    assert blk1.get_balance(local_coinbase) == 1 * blocks.BLOCK_REWARD
    uncle = mine_next_block(blk0, coinbase=uncle_coinbase)
    chain.add_block(uncle)
    assert uncle.hash in chain
    assert chain.head.get_balance(local_coinbase) == 1 * blocks.BLOCK_REWARD
    assert chain.head.get_balance(uncle_coinbase) == 0
    # next block should reward uncles
    blk2 = mine_next_block(blk1, uncles=[uncle.header], coinbase=local_coinbase)
    chain.add_block(blk2)
    assert blk2.get_parent().prevhash == uncle.prevhash
    assert blk2 == chain.head
    assert chain.head.get_balance(local_coinbase) == \
        2 * blocks.BLOCK_REWARD + blocks.NEPHEW_REWARD
    assert chain.head.get_balance(uncle_coinbase) == blocks.BLOCK_REWARD * 7 / 8


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
