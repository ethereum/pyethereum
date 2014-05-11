import sys
import os
import pytest
import tempfile
import pyethereum.processblock as processblock
import pyethereum.blocks as blocks
import pyethereum.transactions as transactions
import pyethereum.utils as utils
import pyethereum.rlp as rlp
from pyethereum.db import DB as DB
import pyethereum.chainmanager as chainmanager

tempdir = tempfile.mktemp()


@pytest.fixture(scope="module")
def accounts():
    k = utils.sha3('cow')
    v = utils.privtoaddr(k)
    k2 = utils.sha3('horse')
    v2 = utils.privtoaddr(k2)
    return k, v, k2, v2


@pytest.fixture(scope="module")
def mkgenesis(*args, **kargs):
    "set INITIAL_DIFFICULTY to a value that is quickly minable"
    tmp = blocks.INITIAL_DIFFICULTY
    blocks.INITIAL_DIFFICULTY = 2 ** 16
    g = blocks.genesis(*args, **kargs)
    blocks.INITIAL_DIFFICULTY = tmp
    return g


def mine_next_block(parent, coinbase=None, transactions=[]):
    # advance one block
    m = chainmanager.Miner(parent, coinbase or parent.coinbase)
    for tx in transactions:
        m.add_transaction(tx)
    blk = m.mine(steps=1000 ** 2)
    return blk


@pytest.fixture(scope="module")
def get_transaction():
    k, v, k2, v2 = accounts()
    tx = transactions.Transaction(0, gasprice=0, startgas=10000,
                                  to=v2, value=utils.denoms.finney * 10, data='').sign(k)
    return tx


def set_db(name=''):
    if name:
        utils.data_dir.set(os.path.join(tempdir, name))
    else:
        utils.data_dir.set(tempfile.mktemp())
set_db()


def db_store(blk):
    db = DB(utils.get_db_path())
    db.put(blk.hash, blk.serialize())
    db.commit()
    assert blocks.get_block(blk.hash) == blk


def test_db():
    db = DB(utils.get_db_path())
    assert 'test' not in db


def test_genesis():
    k, v, k2, v2 = accounts()
    set_db()
    blk = blocks.genesis({v: utils.denoms.ether * 1})
    db_store(blk)
    assert blk in set([blk])
    assert blk == blocks.Block.deserialize(blk.serialize())


def test_mine_block():
    k, v, k2, v2 = accounts()
    set_db()
    blk = blocks.genesis({v: utils.denoms.ether * 1})
    db_store(blk)
    blk2 = mine_next_block(blk, coinbase=v)
    db_store(blk2)
    assert blk2.get_balance(v) == blocks.BLOCK_REWARD + blk.get_balance(v)
    assert blk.state.db.db == blk2.state.db.db
    assert blk2.get_parent() == blk


def test_mine_block_with_transaction():
    k, v, k2, v2 = accounts()
    set_db()
    blk = mkgenesis({v: utils.denoms.ether * 1})
    db_store(blk)
    tx = get_transaction()
    blk2 = mine_next_block(blk, coinbase=v, transactions=[tx])
    db_store(blk2)
    assert blocks.get_block(blk2.hash) == blk2
    assert tx.gasprice == 0
    assert blk2.get_balance(
        v) == blocks.BLOCK_REWARD + blk.get_balance(v) - tx.value
    assert blk.state.db.db == blk2.state.db.db
    assert blk2.get_parent() == blk
    assert tx in blk2.get_transactions()
    assert not tx in blk.get_transactions()


def test_block_serialization_same_db():
    k, v, k2, v2 = accounts()
    set_db()
    blk = mkgenesis({v: utils.denoms.ether * 1})
    assert blk.hex_hash() == \
        blocks.Block.deserialize(blk.serialize()).hex_hash()
    db_store(blk)
    blk2 = mine_next_block(blk)
    assert blk.hex_hash() == \
        blocks.Block.deserialize(blk.serialize()).hex_hash()
    assert blk2.hex_hash() == \
        blocks.Block.deserialize(blk2.serialize()).hex_hash()


def test_block_serialization_other_db():
    k, v, k2, v2 = accounts()
    # mine two blocks
    set_db()
    a_blk = mkgenesis()
    db_store(a_blk)
    a_blk2 = mine_next_block(a_blk)
    db_store(a_blk2)

    # receive in other db
    set_db()
    b_blk = mkgenesis()
    assert b_blk == a_blk
    db_store(b_blk)
    b_blk2 = b_blk.deserialize(a_blk2.serialize())
    assert a_blk2.hex_hash() == b_blk2.hex_hash()
    db_store(b_blk2)
    assert a_blk2.hex_hash() == b_blk2.hex_hash()


def test_block_serialization_with_transaction_other_db():
    #k, v, k2, v2 = accounts()
    # mine two blocks
    set_db()
    a_blk = mkgenesis()
    db_store(a_blk)
    tx = get_transaction()
    a_blk2 = mine_next_block(a_blk, transactions=[tx])
    assert tx in a_blk2.get_transactions()
    db_store(a_blk2)
    # receive in other db
    set_db()
    b_blk = mkgenesis()
    assert b_blk == a_blk
    db_store(b_blk)
    b_blk2 = b_blk.deserialize(a_blk2.serialize())
    assert a_blk2.hex_hash() == b_blk2.hex_hash()
    assert tx in b_blk2.get_transactions()
    db_store(b_blk2)
    assert a_blk2.hex_hash() == b_blk2.hex_hash()
    assert tx in b_blk2.get_transactions()


def test_transaction():
    k, v, k2, v2 = accounts()
    set_db()
    blk = mkgenesis({v: utils.denoms.ether * 1})
    tx = get_transaction()
    assert not tx in blk.get_transactions()
    success, res = processblock.apply_tx(blk, tx)
    assert tx in blk.get_transactions()
    assert blk.get_balance(v) == utils.denoms.finney * 990
    assert blk.get_balance(v2) == utils.denoms.finney * 10


def test_transaction_serialization():
    k, v, k2, v2 = accounts()
    tx = get_transaction()
    assert tx in set([tx])
    assert tx.hex_hash() == \
        transactions.Transaction.deserialize(tx.serialize()).hex_hash()
    assert tx.hex_hash() == \
        transactions.Transaction.hex_deserialize(tx.hex_serialize()).hex_hash()
    assert tx in set([tx])
