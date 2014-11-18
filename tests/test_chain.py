import os
import pytest
import json
import pyethereum.processblock as processblock
import pyethereum.blocks as blocks
import pyethereum.transactions as transactions
import pyethereum.rlp as rlp
import pyethereum.trie as trie
import pyethereum.miner as miner
import pyethereum.utils as utils
from pyethereum.db import DB as DB
from pyethereum.config import get_default_config
from tests.utils import set_db

import logging
logging.basicConfig(level=logging.DEBUG, format='%(message)s')
logger = logging.getLogger()

set_db()

pblogger = processblock.pblogger

# customize VM log output to your needs
# hint: use 'py.test' with the '-s' option to dump logs to the console
pblogger.log_pre_state = True    # dump storage at account before execution
pblogger.log_post_state = True   # dump storage at account after execution
pblogger.log_block = False       # dump block after TX was applied
pblogger.log_memory = False      # dump memory before each op
pblogger.log_op = True           # log op, gas, stack before each op
pblogger.log_json = False        # generate machine readable output


@pytest.fixture(scope="module")
def genesis_fixture():
    """
    Read genesis block from fixtures.
    """
    genesis_fixture = None
    with open('fixtures/genesishashestest.json', 'r') as f:
        genesis_fixture = json.load(f)
    assert genesis_fixture is not None, "Could not read genesishashtest.json from fixtures. Make sure you did 'git submodule init'!"
    # FIXME: assert that link is uptodate
    for k in ('genesis_rlp_hex', 'genesis_state_root', 'genesis_hash', 'initial_alloc'):
        assert k in genesis_fixture
    assert utils.sha3(genesis_fixture['genesis_rlp_hex'].decode('hex')).encode('hex') ==\
        genesis_fixture['genesis_hash']
    return genesis_fixture


@pytest.fixture(scope="module")
def accounts():
    k = utils.sha3('cow')
    v = utils.privtoaddr(k)
    k2 = utils.sha3('horse')
    v2 = utils.privtoaddr(k2)
    return k, v, k2, v2


@pytest.fixture(scope="module")
def mkgenesis(initial_alloc={}):
    return blocks.genesis(initial_alloc)


@pytest.fixture(scope="module")
def mkquickgenesis(initial_alloc={}):
    "set INITIAL_DIFFICULTY to a value that is quickly minable"
    return blocks.genesis(initial_alloc, difficulty=2 ** 16)


def mine_next_block(parent, uncles=[], coinbase=None, transactions=[]):
    # advance one block
    coinbase = coinbase or parent.coinbase
    m = miner.Miner(parent, uncles=uncles, coinbase=coinbase)
    for tx in transactions:
        m.add_transaction(tx)
    blk = m.mine(steps=1000 ** 2)
    assert blk is not False, "Mining failed. Use mkquickgenesis!"
    return blk


@pytest.fixture(scope="module")
def get_transaction(gasprice=0, nonce=0):
    k, v, k2, v2 = accounts()
    tx = transactions.Transaction(
        nonce, gasprice, startgas=10000,
        to=v2, value=utils.denoms.finney * 10, data='').sign(k)
    return tx


@pytest.fixture(scope="module")
def get_chainmanager(genesis=None):
    import pyethereum.chainmanager as chainmanager
    cm = chainmanager.ChainManager()
    cm.configure(config=get_default_config(), genesis=genesis)
    return cm


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


def test_transfer():
    k, v, k2, v2 = accounts()
    blk = blocks.genesis({v: utils.denoms.ether * 1})
    b_v = blk.get_balance(v)
    b_v2 = blk.get_balance(v2)
    value = 42
    success = blk.transfer_value(v, v2, value)
    assert success
    assert blk.get_balance(v) == b_v - value
    assert blk.get_balance(v2) == b_v2 + value


def test_failing_transfer():
    k, v, k2, v2 = accounts()
    blk = blocks.genesis({v: utils.denoms.ether * 1})
    b_v = blk.get_balance(v)
    b_v2 = blk.get_balance(v2)
    value =  utils.denoms.ether * 2
    # should fail
    success = blk.transfer_value(v, v2, value)
    assert not success
    assert blk.get_balance(v) == b_v
    assert blk.get_balance(v2) == b_v2

def test_transient_block():
    blk = blocks.genesis()
    tb_blk = blocks.TransientBlock(blk.serialize())
    assert blk.hash == tb_blk.hash
    assert blk.number == tb_blk.number



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

@pytest.mark.xfail
def test_genesis_state_root(genesis_fixture):
    # https://ethereum.etherpad.mozilla.org/12
    set_db()
    genesis = blocks.genesis()
    for k, v in blocks.GENESIS_INITIAL_ALLOC.items():
        assert genesis.get_balance(k) == v
    assert genesis.state_root.encode(
        'hex') == genesis_fixture['genesis_state_root']

@pytest.mark.xfail
def test_genesis_hash(genesis_fixture):
    set_db()
    genesis = blocks.genesis()
    """
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
    genesis_block_defaults = [
        ["prevhash", "bin", h256],  # h256()
        ["uncles_hash", "bin", utils.sha3(rlp.encode([]))],  # sha3EmptyList
        ["coinbase", "addr", "0" * 40],  # h160()
        ["state_root", "trie_root", sr],  # stateRoot
        ["tx_list_root", "trie_root", trie.BLANK_ROOT],  # h256()
        ["difficulty", "int", 2 ** 17],  # c_genesisDifficulty
        ["number", "int", 0],  # 0
        ["min_gas_price", "int", 0],  # 0
        ["gas_limit", "int", 10 ** 6],  # 10**6 for genesis
        ["gas_used", "int", 0],  # 0
        ["timestamp", "int", 0],  # 0
        ["extra_data", "bin", ""],  # ""
        ["nonce", "bin", utils.sha3(chr(42))],  # sha3(bytes(1, 42));
    ]

    cpp_genesis_block = rlp.decode(
        genesis_fixture['genesis_rlp_hex'].decode('hex'))
    cpp_genesis_header = cpp_genesis_block[0]

    for i, (name, typ, genesis_default) in enumerate(genesis_block_defaults):
        assert utils.decoders[typ](cpp_genesis_header[i]) == genesis_default
        assert getattr(genesis, name) == genesis_default

    assert genesis.hex_hash() == genesis_fixture['genesis_hash']

    assert genesis.hex_hash() == utils.sha3(
        genesis_fixture['genesis_rlp_hex'].decode('hex')
    ).encode('hex')


def test_mine_block():
    k, v, k2, v2 = accounts()
    set_db()
    blk = mkquickgenesis({v: utils.denoms.ether * 1})
    db_store(blk)
    blk2 = mine_next_block(blk, coinbase=v)
    db_store(blk2)
    assert blk2.get_balance(v) == blocks.BLOCK_REWARD + blk.get_balance(v)
    assert blk.state.db.db == blk2.state.db.db
    assert blk2.get_parent() == blk


def test_mine_block_with_transaction():
    k, v, k2, v2 = accounts()
    # mine two blocks
    set_db()
    a_blk = mkquickgenesis({v: utils.denoms.ether * 1})
    db_store(a_blk)
    tx = get_transaction()
    a_blk2 = mine_next_block(a_blk, transactions=[tx])
    assert tx in a_blk2.get_transactions()


def test_block_serialization_with_transaction_empty_genesis():
    k, v, k2, v2 = accounts()
    set_db()
    a_blk = mkquickgenesis({})
    db_store(a_blk)
    tx = get_transaction(gasprice=10)  # must fail, as there is no balance
    a_blk2 = mine_next_block(a_blk, transactions=[tx])
    assert tx not in a_blk2.get_transactions()


def test_mine_block_with_transaction():
    k, v, k2, v2 = accounts()
    set_db()
    blk = mkquickgenesis({v: utils.denoms.ether * 1})
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
    blk = mkquickgenesis({v: utils.denoms.ether * 1})
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
    a_blk = mkquickgenesis()
    db_store(a_blk)
    a_blk2 = mine_next_block(a_blk)
    db_store(a_blk2)

    # receive in other db
    set_db()
    b_blk = mkquickgenesis()
    assert b_blk == a_blk
    db_store(b_blk)
    b_blk2 = b_blk.deserialize(a_blk2.serialize())
    assert a_blk2.hex_hash() == b_blk2.hex_hash()
    db_store(b_blk2)
    assert a_blk2.hex_hash() == b_blk2.hex_hash()


def test_block_serialization_with_transaction_other_db():

    hx = lambda x: x.encode('hex')

    k, v, k2, v2 = accounts()
    # mine two blocks
    set_db()
    a_blk = mkquickgenesis({v: utils.denoms.ether * 1})
    db_store(a_blk)
    tx = get_transaction()
    logger.debug('a: state_root before tx %r', hx(a_blk.state_root))
    logger.debug('a: state:\n%s', utils.dump_state(a_blk.state))
    a_blk2 = mine_next_block(a_blk, transactions=[tx])
    logger.debug('a: state_root after tx %r', hx(a_blk2.state_root))
    logger.debug('a: state:\n%s', utils.dump_state(a_blk2.state))
    assert tx in a_blk2.get_transactions()
    db_store(a_blk2)
    assert tx in a_blk2.get_transactions()
    logger.debug('preparing receiving chain ---------------------')
    # receive in other db
    set_db()
    b_blk = mkquickgenesis({v: utils.denoms.ether * 1})
    db_store(b_blk)

    assert b_blk.number == 0
    assert b_blk == a_blk
    logger.debug('b: state_root before tx %r', hx(b_blk.state_root))
    logger.debug('starting deserialization of remote block w/ tx')
    b_blk2 = b_blk.deserialize(a_blk2.serialize()) # BOOM
    logger.debug('b: state_root after %r', hx(b_blk2.state_root))

    assert a_blk2.hex_hash() == b_blk2.hex_hash()

    assert tx in b_blk2.get_transactions()
    db_store(b_blk2)
    assert a_blk2.hex_hash() == b_blk2.hex_hash()
    assert tx in b_blk2.get_transactions()


def test_transaction():
    k, v, k2, v2 = accounts()
    set_db()
    blk = mkquickgenesis({v: utils.denoms.ether * 1})
    db_store(blk)
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
    assert tx.hex_hash() == \
        transactions.Transaction.deserialize(tx.serialize()).hex_hash()
    assert tx.hex_hash() == \
        transactions.Transaction.hex_deserialize(tx.hex_serialize()).hex_hash()
    assert tx in set([tx])


def test_mine_block_with_transaction():
    k, v, k2, v2 = accounts()
    set_db()
    blk = mkquickgenesis({v: utils.denoms.ether * 1})
    db_store(blk)
    tx = get_transaction()
    blk = mine_next_block(blk, transactions=[tx])
    assert tx in blk.get_transactions()
    assert blk.get_balance(v) == utils.denoms.finney * 990
    assert blk.get_balance(v2) == utils.denoms.finney * 10


def test_invalid_transaction():
    k, v, k2, v2 = accounts()
    set_db()
    blk = mkquickgenesis({v2: utils.denoms.ether * 1})
    db_store(blk)
    tx = get_transaction()
    blk = mine_next_block(blk, transactions=[tx])
    assert blk.get_balance(v) == 0
    assert blk.get_balance(v2) == utils.denoms.ether * 1
    assert tx not in blk.get_transactions()


def test_add_side_chain():
    """"
    Local: L0, L1, L2
    add
    Remote: R0, R1
    """
    k, v, k2, v2 = accounts()
    # Remote: mine one block
    set_db()
    R0 = mkquickgenesis({v: utils.denoms.ether * 1})
    db_store(R0)
    tx0 = get_transaction(nonce=0)
    R1 = mine_next_block(R0, transactions=[tx0])
    db_store(R1)
    assert tx0 in R1.get_transactions()

    # Local: mine two blocks
    set_db()
    L0 = mkquickgenesis({v: utils.denoms.ether * 1})
    cm = get_chainmanager(genesis=L0)
    tx0 = get_transaction(nonce=0)
    L1 = mine_next_block(L0, transactions=[tx0])
    cm.add_block(L1)
    tx1 = get_transaction(nonce=1)
    L2 = mine_next_block(L1, transactions=[tx1])
    cm.add_block(L2)

    # receive serialized remote blocks, newest first
    transient_blocks = [blocks.TransientBlock(R0.serialize()),
                        blocks.TransientBlock(R1.serialize())]
    cm.receive_chain(transient_blocks=transient_blocks)
    assert L2.hash in cm


def test_add_longer_side_chain():
    """"
    Local: L0, L1, L2
    Remote: R0, R1, R2, R3
    """
    k, v, k2, v2 = accounts()
    # Remote: mine one block
    set_db()
    blk = mkquickgenesis({v: utils.denoms.ether * 1})
    db_store(blk)
    remote_blocks = [blk]
    for i in range(3):
        tx = get_transaction(nonce=i)
        blk = mine_next_block(remote_blocks[-1], transactions=[tx])
        db_store(blk)
        remote_blocks.append(blk)
    # Local: mine two blocks
    set_db()
    L0 = mkquickgenesis({v: utils.denoms.ether * 1})
    cm = get_chainmanager(genesis=L0)
    tx0 = get_transaction(nonce=0)
    L1 = mine_next_block(L0, transactions=[tx0])
    cm.add_block(L1)
    tx1 = get_transaction(nonce=1)
    L2 = mine_next_block(L1, transactions=[tx1])
    cm.add_block(L2)

    # receive serialized remote blocks, newest first
    transient_blocks = [blocks.TransientBlock(b.serialize()) for b in remote_blocks]
    cm.receive_chain(transient_blocks=transient_blocks)
    assert cm.head == remote_blocks[-1]



def test_reward_uncles():
    """
    B0 B1 B2
    B0 Uncle

    We raise the block's coinbase account by Rb, the block reward,
    and also add uncle and nephew rewards
    """
    k, v, k2, v2 = accounts()
    set_db()
    blk0 = mkquickgenesis()
    local_coinbase = '1' * 40
    uncle_coinbase = '2' * 40
    cm = get_chainmanager(genesis=blk0)
    blk1 = mine_next_block(blk0, coinbase=local_coinbase)
    cm.add_block(blk1)
    assert blk1.get_balance(local_coinbase) == 1 * blocks.BLOCK_REWARD
    uncle = mine_next_block(blk0, coinbase=uncle_coinbase)
    cm.add_block(uncle)
    assert uncle.hash in cm
    assert cm.head.get_balance(local_coinbase) == 1 * blocks.BLOCK_REWARD
    assert cm.head.get_balance(uncle_coinbase) == 0
    # next block should reward uncles
    blk2 = mine_next_block(blk1, uncles=[uncle], coinbase=local_coinbase)
    cm.add_block(blk2)
    assert blk2.get_parent().prevhash == uncle.prevhash
    assert blk2 == cm.head
    assert cm.head.get_balance(local_coinbase) == \
        2 * blocks.BLOCK_REWARD + blocks.NEPHEW_REWARD
    assert cm.head.get_balance(uncle_coinbase) == blocks.UNCLE_REWARD


# TODO ##########################################
#
# test for remote block with invalid transaction
# test for multiple transactions from same address received
#    in arbitrary order mined in the same block
