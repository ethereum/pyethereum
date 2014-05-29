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
from pyethereum.eth import create_default_config
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
    m = chainmanager.Miner(parent, uncles=uncles, coinbase=coinbase)
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
    cm = chainmanager.ChainManager()
    cm.configure(config=create_default_config(), genesis=genesis)
    return cm


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
        acct = [
            int_to_big_endian(int(value)), ZERO_ENC, trie.BLANK_ROOT, EMPTYSHA3]
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
        ["difficulty", "int", 2 ** 22],  # c_genesisDifficulty
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


def test_block_serialization_with_transaction():
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
    k, v, k2, v2 = accounts()
    # mine two blocks
    set_db()
    a_blk = mkquickgenesis({v: utils.denoms.ether * 1})
    db_store(a_blk)
    tx = get_transaction()
    a_blk2 = mine_next_block(a_blk, transactions=[tx])
    assert tx in a_blk2.get_transactions()
    db_store(a_blk2)
    assert tx in a_blk2.get_transactions()
    # receive in other db
    set_db()
    b_blk = mkquickgenesis({v: utils.denoms.ether * 1})
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
    blk = mkquickgenesis({v: utils.denoms.ether * 1})
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
    # should invalid transaction be included in blocks?
    assert tx in blk.get_transactions()


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
    transient_blocks = [blocks.TransientBlock(R1.serialize()),
                        blocks.TransientBlock(R0.serialize())]
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
    transient_blocks = [blocks.TransientBlock(b.serialize())
                        for b in reversed(remote_blocks)]
    cm.receive_chain(transient_blocks=transient_blocks)
    assert cm.head == remote_blocks[-1]


@pytest.mark.wip
def test_reward_unlces():
    """
    B0 B1 B2
    B0 Uncle

    We raise the block's coinbase account by Rb, the block reward,
    and the coinbase of each uncle by 7 of 8 that.
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
    assert cm.head.get_balance(local_coinbase) == 2 * blocks.BLOCK_REWARD
    assert cm.head.get_balance(uncle_coinbase) == blocks.UNCLE_REWARD
    assert 7 * blocks.BLOCK_REWARD / 8 == blocks.UNCLE_REWARD


# blocks 1-3 genereated with Ethereum (++) 0.5.9
# chain order w/ newest block first
cpp_rlp_blocks = ["f8b5f8b1a0cea7b6f4379812715562aaf0f44accf61ece5a2d80fe780d7e173fbbb1b146eaa01dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d49347941315bd599b73fd7b159e23dc75ddef80e7708feaa007e693fe94ea4772ab4c875af6bee3d58c0cab33981a0a336f4ae6cf514c1ee680833feffc038609184e72a000830f36d080845381ae3e80a00000000000000000000000000000000000000000000000000950e155eb5ed4cac0c0",
                  "f8b5f8b1a00c892995c469f57a34447217fc6cebbaf604c9d82d621a6505c7493ac1333e68a01dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d49347941315bd599b73fd7b159e23dc75ddef80e7708feaa0e785df309fbf0289aa9d1c09096c039aa69b880b6c001eb95ec838fb2dcebe5180833fe004028609184e72a000830f3a9f80845381ae3e80a0000000000000000000000000000000000000000000000000b985b7d378a23d84c0c0",
                  "f8b5f8b1a0c305511e7cb9b33767e50f5e94ecd7b1c51359a04f45183860ec6808d80b0d3fa01dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d49347941315bd599b73fd7b159e23dc75ddef80e7708feaa04b6da9af1b96757921ba3a0de69c615fea5482570e37a4d74d051e1e19f996c880833ff000018609184e72a000830f3e6f80845381adf680a00000000000000000000000000000000000000000000000003dfac8aa6e0214b4c0c0"]


def test_receive_cpp_block_1():
    set_db()
    cm = get_chainmanager()
    blk1 = blocks.TransientBlock(cpp_rlp_blocks[-1].decode('hex'))
    assert not blk1.transaction_list
    assert not blk1.uncles
    assert blk1.number == 1
    genesis = cm.head
    assert blk1.prevhash.encode('hex') == genesis.hex_hash()
    local_blk1 = genesis.deserialize_child(blk1.rlpdata)
    assert local_blk1.check_proof_of_work(local_blk1.nonce) == True


def test_receive_cpp_chain():
    set_db()
    cm = get_chainmanager()
    local_blk = cm.head  # genesis
    for i, rlp_block in enumerate(reversed(cpp_rlp_blocks)):
        blk = blocks.TransientBlock(rlp_block.decode('hex'))
        assert not blk.transaction_list
        assert not blk.uncles
        assert blk.number == i + 1
        local_blk = local_blk.deserialize_child(blk.rlpdata)
        assert local_blk.check_proof_of_work(local_blk.nonce) == True


def test_deserialize_cpp_block_42():
    # 54.204.10.41 / NEthereum(++)/ZeroGox/v0.5.9/ncurses/Linux/g++ V:17L
    # E       TypeError: ord() expected a character, but string of length 0 found
    # 00bab55f2e230d4d56c7a2c11e7f3132663cc6734a5d4406f2e4359f4ab56593
    """
    RomanJ dumped the block
    BlockData [
  hash=00bab55f2e230d4d56c7a2c11e7f3132663cc6734a5d4406f2e4359f4ab56593
  parentHash=0df28c56b0cc32ceb55299934fca74ff63956ede0ffd430367ebcb1bb94d42fe
  unclesHash=1dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d49347
  coinbase=a70abb9ed4b5d82ed1d82194943349bcde036812
  stateHash=203838e6ea7b03bce4b806ab4e5c069d5cd98ca2ba27a2d343d809cc6365e1ce
  txTrieHash=78aaa0f3b726f8d9273ba145e0efd4a6b21183412582449cc9457f713422b5ae
  difficulty=4142bd
  number=48
  minGasPrice=10000000000000
  gasLimit=954162
  gasUsed=500
  timestamp=1400678342
  extraData=null
  nonce=0000000000000000000000000000000000000000000000007d117303138a74e0

TransactionData [ hash=9003d7211c4b0d123778707fbdcabd93a6184be210390de4f73f89eae847556d  nonce=null, gasPrice=09184e72a000, gas=01f4, receiveAddress=e559de5527492bcb42ec68d07df0742a98ec3f1e, value=8ac7230489e80000, data=null, signatureV=27, signatureR=18d646b8c4f7a804fdf7ba8da4d5dd049983e7d2b652ab902f7d4eaebee3e33b, signatureS=229ad485ef078d6e5f252db58dd2cce99e18af02028949896248aa01baf48b77]
]
    """

    hex_rlp_data = \
        """f9016df8d3a00df28c56b0cc32ceb55299934fca74ff63956ede0ffd430367ebcb1bb94d42fea01dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d4934794a70abb9ed4b5d82ed1d82194943349bcde036812a0203838e6ea7b03bce4b806ab4e5c069d5cd98ca2ba27a2d343d809cc6365e1cea078aaa0f3b726f8d9273ba145e0efd4a6b21183412582449cc9457f713422b5ae834142bd308609184e72a000830e8f328201f484537ca7c680a00000000000000000000000000000000000000000000000007d117303138a74e0f895f893f86d808609184e72a0008201f494e559de5527492bcb42ec68d07df0742a98ec3f1e888ac7230489e80000801ba018d646b8c4f7a804fdf7ba8da4d5dd049983e7d2b652ab902f7d4eaebee3e33ba0229ad485ef078d6e5f252db58dd2cce99e18af02028949896248aa01baf48b77a06e957f0f99502ad60a66a016f72957eff0f3a5bf791ad4a0606a44f35a6e09288201f4c0"""
    header_args, transaction_list, uncles = rlp.decode(
        hex_rlp_data.decode('hex'))
    for tx_data, _state_root, _gas_used_encoded in transaction_list:
        tx = transactions.Transaction.create(tx_data)


# TODO ##########################################
#
# test for remote block with invalid transaction
# test for multiple transactions from same address received
#    in arbitrary order mined in the same block
