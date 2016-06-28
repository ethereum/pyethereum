import pytest

from ethereum.slogging import get_logger, configure_logging
from ethereum.transactions import Transaction, TransactionPool
from ethereum import utils
from ethereum.chain import Chain
from test_chain import mkquickgenesis, accounts, store_block, get_transaction, mine_next_block
from test_chain import db  # db-fixture

log = get_logger('test_tx_pool')

configure_logging(':DEBUG')


def test_pool_implementation():
    blocks = 3
    tx_per_block = 5
    pool = TransactionPool()
    addr = 'a' * 40
    for block in range(1, blocks + 1):
        for nonce in range(1, tx_per_block + 1):
            pool_nonce = pool.get_highest_nonce(addr)
            if pool_nonce and pool_nonce > nonce:
                nonce = pool_nonce + 1
            assert nonce > 0
            tx = Transaction(nonce=nonce, gasprice=1000, startgas=3000000, to='', value=10 + nonce, data='')
            tx.sender = addr
            pool.pool_transaction(tx)

    assert len(pool.pool) == blocks * tx_per_block
    with pytest.raises(ValueError):
        pool.pool_transaction(Transaction(
            nonce=5000, gasprice=1000, startgas=3000000, to='', value=10, data=''))

    assert pool.get_highest_nonce(addr) == blocks * tx_per_block, "highest nonce not correct"
    first = pool.pop_transaction()
    assert first.nonce == 1, "nonce ordering not working"
    pool.pool_transaction(first)
    for i in range(1, blocks * tx_per_block + 1):
        assert pool.pop_transaction().nonce == i
    assert pool.pop_transaction() is None, "pop not working"
    assert pool.get_highest_nonce(addr) is None


def test_too_much_gas_per_tx_dont_go_to_pool(db):
    initial_alloc = utils.denoms.ether * 10000
    k, v, k2, v2 = accounts()
    blk = mkquickgenesis({v: {'balance': initial_alloc}, v2: {"balance": initial_alloc}}, db=db)
    assert blk.number == 0
    store_block(blk)
    c = Chain(env=blk.env, genesis=blk)
    txs = [get_transaction(startgas=9999999, nonce=nonce) for nonce in range(0, 5)]
    blk = mine_next_block(blk, transactions=txs, chain=c)
    assert blk.number == 1
    store_block(blk)
    assert blk.number == 1
    assert blk.get_balance(v) == initial_alloc
    assert blk.get_balance(v2) == initial_alloc
    assert txs[0] not in blk.get_transactions()
    assert txs[-1] not in blk.get_transactions()
    assert c.transaction_pool is not None
    assert blk.number == 1
    blk = mine_next_block(blk, chain=c)
    store_block(blk)
    assert blk.number == 2
    assert c.transaction_pool.pop_transaction() is None
    assert blk.get_nonce(v) == 0
    assert blk.get_nonce(v2) == 0


def test_clean(db):
    initial_alloc = utils.denoms.ether * 10000
    k, v, k2, v2 = accounts()
    blk = mkquickgenesis({v: {'balance': initial_alloc}, v2: {"balance": initial_alloc}}, db=db)
    assert blk.number == 0
    store_block(blk)
    c = Chain(env=blk.env, genesis=blk)
    txs = [get_transaction(nonce=nonce) for nonce in range(1)]
    blk = mine_next_block(blk, transactions=txs, chain=c)
    assert blk.number == 1
    store_block(blk)
    assert blk.number == 1
    assert len(blk.get_transactions()) == 1, blk.get_transactions()


def test_second_tx_over_blockgaslimit_goes_to_pool(db):
    initial_alloc = utils.denoms.ether * 10000
    k, v, k2, v2 = accounts()
    blk = mkquickgenesis({v: {'balance': initial_alloc}, v2: {"balance": initial_alloc}}, db=db)
    assert blk.number == 0
    store_block(blk)
    c = Chain(env=blk.env, genesis=blk)
    txs = [get_transaction(startgas=3141590, nonce=nonce) for nonce in range(2)]
    blk = mine_next_block(blk, transactions=txs, chain=c)
    assert blk.number == 1
    store_block(blk)
    assert blk.number == 1
    assert len(blk.get_transactions()) == 1, blk.get_transactions()
    assert blk.get_nonce(v) == 1
    assert blk.get_balance(v) == initial_alloc - utils.denoms.finney * 10
    assert blk.get_balance(v2) == initial_alloc + utils.denoms.finney * 10
    assert txs[0] in blk.get_transactions()
    assert txs[1] not in blk.get_transactions()
    assert c.transaction_pool is not None
    assert blk.number == 1
    blk = mine_next_block(blk, chain=c)
    store_block(blk)
    assert blk.number == 2
    assert blk.get_balance(v) == initial_alloc - utils.denoms.finney * 10 * 2
    assert blk.get_balance(v2) == initial_alloc + utils.denoms.finney * 10 * 2
    assert c.transaction_pool.pop_transaction() is None
    assert blk.get_nonce(v) == 2
    assert blk.get_nonce(v2) == 0


def test_many_tx_over_blockgaslimit_go_to_pool_and_applied_in_order(db):
    num_tx = 5
    initial_alloc = utils.denoms.ether * 10000
    k, v, k2, v2 = accounts()
    blk = mkquickgenesis({v: {'balance': initial_alloc}, v2: {"balance": initial_alloc}}, db=db)
    assert blk.number == 0
    store_block(blk)
    c = Chain(env=blk.env, genesis=blk)
    txs = [get_transaction(startgas=3141592, nonce=nonce) for nonce in range(num_tx)]
    blk = mine_next_block(blk, transactions=txs, chain=c)
    assert blk.number == 1
    store_block(blk)
    for i in range(1, num_tx):
        assert blk.get_nonce(v) == i
        assert blk.number == i
        assert blk.get_balance(v) == initial_alloc - utils.denoms.finney * 10 * i
        assert blk.get_balance(v2) == initial_alloc + utils.denoms.finney * 10 * i
        assert txs[i - 1] in blk.get_transactions()
        if len(txs) > i:
            assert txs[i + 1] not in blk.get_transactions()
        assert c.transaction_pool is not None
        assert blk.number == i
        blk = mine_next_block(blk, chain=c)
        store_block(blk)
        assert blk.number == i + 1
        assert blk.get_balance(v) == initial_alloc - utils.denoms.finney * 10 * i
        assert blk.get_balance(v2) == initial_alloc + utils.denoms.finney * 10 * i
    assert c.transaction_pool.pop_transaction() is None
    assert blk.get_nonce(v) == 2
    assert blk.get_nonce(v2) == 0
