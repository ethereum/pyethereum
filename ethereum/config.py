from ethereum import utils
from ethereum.db import BaseDB
import time
from ethereum.utils import address, int256, trie_root, hash32, to_string, \
    sha3, zpad, normalize_address, int_to_addr, big_endian_to_int

default_config = dict(
    # Genesis block difficulty
    GENESIS_DIFFICULTY=131072,
    # Genesis block gas limit
    GENESIS_GAS_LIMIT=3141592,
    # Genesis block prevhash, coinbase, nonce
    GENESIS_PREVHASH=b'\x00' * 32,
    GENESIS_COINBASE=b'\x00' * 20,
    GENESIS_NONCE=utils.zpad(utils.encode_int(42), 8),
    GENESIS_MIXHASH=b'\x00' * 32,
    GENESIS_TIMESTAMP=0,
    GENESIS_EXTRA_DATA=b'',
    GENESIS_INITIAL_ALLOC={},
    # Minimum gas limit
    MIN_GAS_LIMIT=5000,
    # Gas limit adjustment algo:
    # block.gas_limit=block.parent.gas_limit * 1023/1024 +
    #                   (block.gas_used * 6 / 5) / 1024
    GASLIMIT_EMA_FACTOR=1024,
    GASLIMIT_ADJMAX_FACTOR=1024,
    BLKLIM_FACTOR_NOM=3,
    BLKLIM_FACTOR_DEN=2,
    # Block reward
    BLOCK_REWARD=5000 * utils.denoms.finney,
    NEPHEW_REWARD=5000 * utils.denoms.finney // 32,  # BLOCK_REWARD / 32
    # GHOST constants
    UNCLE_DEPTH_PENALTY_FACTOR=8,
    MAX_UNCLE_DEPTH=6,  # max (block.number - uncle.number)
    MAX_UNCLES=2,
    # Difficulty adjustment constants
    DIFF_ADJUSTMENT_CUTOFF=13,
    BLOCK_DIFF_FACTOR=2048,
    MIN_DIFF=131072,
    # PoW info
    POW_EPOCH_LENGTH=30000,
    # Maximum extra data length
    MAX_EXTRADATA_LENGTH=32,
    # Exponential difficulty timebomb period
    EXPDIFF_PERIOD=100000,
    EXPDIFF_FREE_PERIODS=2,
    # Blank account initial nonce
    ACCOUNT_INITIAL_NONCE=0,
    # Homestead fork (500k on livenet?)
    HOMESTEAD_FORK_BLKNUM=2**100,
    HOMESTEAD_DIFF_ADJUSTMENT_CUTOFF=16,
)
assert default_config['NEPHEW_REWARD'] == \
    default_config['BLOCK_REWARD'] // 32


class Env(object):

    def __init__(self, db, config=None, global_config=None, genesis_timestamp=time.time()):
        assert isinstance(db, BaseDB)
        self.db = db
        self.config = config or dict(default_config)
        self.global_config = global_config or dict()
        self.genesis_timestamp = genesis_timestamp

SYS = utils.int_to_addr(2**160 - 1)
STATEROOTS = utils.int_to_addr(2**160 - 2)
BLKNUMBER = utils.int_to_addr(2**160 - 3)
GAS_CONSUMED = utils.int_to_addr(2**160 - 4)
ETHER = utils.int_to_addr(2**160 - 5)
CASPER = int_to_addr(2**160 - 6)
ECRECOVERACCT = utils.int_to_addr(2**160 - 7)
PROPOSER = utils.int_to_addr(2**160 - 8)
RNGSEEDS = utils.int_to_addr(2**160 - 9)
BLOCKHASHES = utils.int_to_addr(2**160 - 10)
GENESIS_TIME = utils.int_to_addr(2**160 - 11)
TXGAS = utils.int_to_addr(2**160 - 12)
TXINDEX = utils.int_to_addr(2**160 - 13)
LOG = utils.int_to_addr(2**160 - 14)
BET_INCENTIVIZER = utils.int_to_addr(2**160 - 15)
GASLIMIT = 4712388 # Pau million
NULL_SENDER = utils.int_to_addr(0)
BLKTIME = 3
ENTER_EXIT_DELAY = 60
