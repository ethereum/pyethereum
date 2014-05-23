import os
import pytest
import json
import tempfile
import pyethereum.processblock as processblock
import pyethereum.blocks as blocks
import pyethereum.transactions as transactions
import pyethereum.utils as utils
import pyethereum.rlp as rlp
import pyethereum.trie as trie
from pyethereum.db import DB as DB
import pyethereum.chainmanager as chainmanager

tempdir = tempfile.mktemp()


@pytest.fixture(scope="module")
def genesis_fixture():
    """
    Read genesis block from fixtures.
    """
    genesis_fixture = None
    with open('fixtures/genesishashestest.json', 'r') as f:
        genesis_fixture = json.load(f)
    assert genesis_fixture is not None, "Could not read genesishashtest.json from fixtures. Make sure you did 'git submodule init'!"
    return genesis_fixture


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
def get_transaction(gasprice=0):
    k, v, k2, v2 = accounts()
    tx = transactions.Transaction(
        0, gasprice, startgas=10000,
        to=v2, value=utils.denoms.finney * 10, data='').sign(k)
    return tx


def set_db(name=''):
    if name:
        utils.data_dir.set(os.path.join(tempdir, name))
    else:
        utils.data_dir.set(tempfile.mktemp())


set_db()


def db_store(blk):
    utils.db_put(blk.hash, blk.serialize())
    assert blocks.get_block(blk.hash) == blk


def test_db():
    set_db()
    db = DB(utils.get_db_path())
    a, b = DB(utils.get_db_path()),  DB(utils.get_db_path())
    assert a == b
    assert a.uncommitted == b.uncommitted
    a.put('a', 'b')
    b.get('a') == 'b'
    assert a.uncommitted == b.uncommitted
    a.commit()
    assert a.uncommitted == b.uncommitted
    assert 'test' not in db
    set_db()
    assert a != DB(utils.get_db_path())


def test_genesis():
    k, v, k2, v2 = accounts()
    set_db()
    blk = blocks.genesis({v: utils.denoms.ether * 1})
    sr = blk.state_root
    db = DB(utils.get_db_path())
    assert blk.state.db.db == db.db
    db.put(blk.hash, blk.serialize())
    blk.state.db.commit()
    assert sr in db
    db.commit()
    assert sr in db
    blk2 = blocks.genesis({v: utils.denoms.ether * 1})
    blk3 = blocks.genesis()
    assert blk == blk2
    assert blk != blk3
    set_db()
    blk2 = blocks.genesis({v: utils.denoms.ether * 1})
    blk3 = blocks.genesis()
    assert blk == blk2
    assert blk != blk3


def test_genesis_db():
    k, v, k2, v2 = accounts()
    set_db()
    blk = blocks.genesis({v: utils.denoms.ether * 1})
    db_store(blk)
    blk2 = blocks.genesis({v: utils.denoms.ether * 1})
    blk3 = blocks.genesis()
    assert blk == blk2
    assert blk != blk3
    set_db()
    blk2 = blocks.genesis({v: utils.denoms.ether * 1})
    blk3 = blocks.genesis()
    assert blk == blk2
    assert blk != blk3


def test_trie_state_root_nodep(genesis_fixture):
    def int_to_big_endian(integer):
        if integer == 0:
            return ''
        s = '%x' % integer
        if len(s) & 1:
            s = '0' + s
        return s.decode('hex')
    EMPTYSHA3 = utils.sha3('')
    assert EMPTYSHA3.encode('hex') == \
        'c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470'
    ZERO_ENC = int_to_big_endian(0)
    assert ZERO_ENC == ''
    state = trie.Trie(tempfile.mktemp())
    for address, value in genesis_fixture['initial_alloc'].items():
        acct = [int_to_big_endian(int(value)), ZERO_ENC, trie.BLANK_ROOT, EMPTYSHA3]
        state.update(address.decode('hex'), rlp.encode(acct))
    assert state.root_hash.encode(
        'hex') == genesis_fixture['genesis_state_root']


def test_genesis_state_root(genesis_fixture):
    # https://ethereum.etherpad.mozilla.org/12
    set_db()
    genesis = blocks.genesis()
    for k, v in blocks.GENESIS_INITIAL_ALLOC.items():
        assert genesis.get_balance(k) == v
    assert genesis.state_root.encode(
        'hex') == genesis_fixture['genesis_state_root']


def test_genesis_hash(genesis_fixture):
    set_db()
    genesis = blocks.genesis()
    """
    cpp: https://github.com/ethereum/cpp-ethereum/libethereum/BlockInfo.cpp#L64
    h256() << sha3EmptyList << h160() << stateRoot << h256()
    << c_genesisDifficulty << 0 << 0 << 1000000 << 0 << (uint)0 << string()
    << sha3(bytes(1, 42));

    PoC5 etherpad: https://ethereum.etherpad.mozilla.org/11
    Genesis block is: ( B32(0, 0, ...), B32(sha3(B())), B20(0, 0, ...),
    B32(stateRoot), B32(0, 0, ...), P(2^22), P(0), P(0), P(1000000), P(0),
    P(0) << B() << B32(sha3(B(42))) )

    Genesis hash:
    69a7356a245f9dc5b865475ada5ee4e89b18f93c06503a9db3b3630e88e9fb4e

    YP: https://raw.githubusercontent.com/ethereum/latexpaper/master/Paper.tex
    0256 , SHA3RLP(), 0160 , stateRoot, 0256 , 2**22 , 0, 0, 1000000, 0, 0, (),
    SHA3(42), (), ()

    Where 0256 refers to the parent and state and transaction root hashes,
    a 256-bit hash which is all zeroes;
    0160 refers to the coinbase address,
    a 160-bit hash which is all zeroes;
    2**22 refers to the difficulty;
    0 refers to the timestamp (the Unix epoch);
    () refers to the extradata and the sequences of both uncles and
    transactions, all empty.
    SHA3(42) refers to the SHA3 hash of a byte array of length one whose first
    and only byte is of value 42.
    SHA3RLP() values refer to the hashes of the transaction and uncle lists
    in RLP
    both empty.
    The proof-of-concept series include a development premine, making the state
    root hash some value stateRoot. The latest documentation should be
    consulted for the value of the state root.
    """

    h256 = '\00' * 32
    sr = genesis_fixture['genesis_state_root'].decode('hex')
    genisi_block_defaults = [
        ["prevhash", "bin", h256],  # h256()
        ["uncles_hash", "bin", utils.sha3(rlp.encode([]))],  # sha3EmptyList
        ["coinbase", "addr", "0" * 40],  # h160()
        ["state_root", "trie_root", sr],  # stateRoot
        ["tx_list_root", "trie_root", trie.BLANK_ROOT],  # h256()
        ["difficulty", "int", 2 ** 22],  # c_genesisDifficulty
        ["number", "int", 0],  # 0
        ["min_gas_price", "int", 0],  # 0
        ["gas_limit", "int", 10000],  # 10000
        ["gas_used", "int", 0],  # 0
        ["timestamp", "int", 0],  # 0
        ["extra_data", "bin", ""],  # ""
        ["nonce", "bin", utils.sha3(chr(42))],  # sha3(bytes(1, 42));
    ]

    cpp_genesis_block = rlp.decode(genesis_fixture['genesis_rlp_hex'].decode('hex'))
    cpp_genesis_header = cpp_genesis_block[0]

    for i, (name, typ, genesis_default) in enumerate(genisi_block_defaults):
        assert utils.decoders[typ](cpp_genesis_header[i]) == genesis_default
        assert getattr(genesis, name) == genesis_default

    assert genesis.hex_hash() == genesis_fixture['genesis_hash']

    assert genesis.hex_hash() == utils.sha3(
        genesis_fixture['genesis_rlp_hex'].decode('hex')
    ).encode('hex')


def test_mine_block():
    k, v, k2, v2 = accounts()
    set_db()
    blk = mkgenesis({v: utils.denoms.ether * 1})
    db_store(blk)
    blk2 = mine_next_block(blk, coinbase=v)
    db_store(blk2)
    assert blk2.get_balance(v) == blocks.BLOCK_REWARD + blk.get_balance(v)
    assert blk.state.db.db == blk2.state.db.db
    assert blk2.get_parent() == blk


def test_block_serialization_with_transaction():
    k, v, k2, v2 = accounts()
    # mine two blocks
    set_db()
    a_blk = mkgenesis({v: utils.denoms.ether * 1})
    db_store(a_blk)
    tx = get_transaction()
    a_blk2 = mine_next_block(a_blk, transactions=[tx])
    assert tx in a_blk2.get_transactions()


def test_block_serialization_with_transaction_empty_genesis():
    k, v, k2, v2 = accounts()
    set_db()
    a_blk = mkgenesis({})
    db_store(a_blk)
    tx = get_transaction(gasprice=10)  # must fail, as there is no balance
    a_blk2 = mine_next_block(a_blk, transactions=[tx])
    assert tx not in a_blk2.get_transactions()


def test_mine_block_with_transaction():
    k, v, k2, v2 = accounts()
    set_db()
    blk = mkgenesis({v: utils.denoms.ether * 1})
    db_store(blk)
    tx = get_transaction()
    blk2 = mine_next_block(blk, coinbase=v, transactions=[tx])
    assert tx in blk2.get_transactions()
    db_store(blk2)
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


@pytest.mark.bswto
def test_block_serialization_with_transaction_other_db():
    k, v, k2, v2 = accounts()
    # mine two blocks
    set_db()
    a_blk = mkgenesis({v: utils.denoms.ether * 1})
    db_store(a_blk)
    tx = get_transaction()
    a_blk2 = mine_next_block(a_blk, transactions=[tx])
    assert tx in a_blk2.get_transactions()
    db_store(a_blk2)
    assert tx in a_blk2.get_transactions()
    # receive in other db
    set_db()
    b_blk = mkgenesis({v: utils.denoms.ether * 1})
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
    db_store(blk)
    blk = mine_next_block(blk)
    tx = get_transaction()
    assert tx not in blk.get_transactions()
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
