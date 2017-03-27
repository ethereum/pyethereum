from rlp.utils import decode_hex

from ethereum import utils
from ethereum.db import BaseDB
from ethereum.child_dao_list import L as child_dao_list


default_config = dict(
    # Genesis block difficulty
    GENESIS_DIFFICULTY=131072,
    # Genesis block gas limit
    GENESIS_GAS_LIMIT=4712388,
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
    MAX_GAS_LIMIT=2 ** 63 - 1,
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
    # Homestead fork
    HOMESTEAD_FORK_BLKNUM=1150000,
    HOMESTEAD_DIFF_ADJUSTMENT_CUTOFF=10,
    # Metropolis fork
    METROPOLIS_FORK_BLKNUM=2 ** 100,
    METROPOLIS_ENTRY_POINT=2 ** 160 - 1,
    METROPOLIS_STATEROOT_STORE=0x10,
    METROPOLIS_BLOCKHASH_STORE=0x20,
    METROPOLIS_WRAPAROUND=65536,
    METROPOLIS_GETTER_CODE=decode_hex('6000355460205260206020f3'),
    METROPOLIS_DIFF_ADJUSTMENT_CUTOFF=9,
    # DAO fork
    DAO_FORK_BLKNUM=1920000,
    CHILD_DAO_LIST=map(utils.normalize_address, child_dao_list),
    DAO_WITHDRAWER=utils.normalize_address('0xbf4ed7b27f1d666546e30d74d50d173d20bca754'),
    # Anti-DoS fork
    ANTI_DOS_FORK_BLKNUM=2457000,
    CLEARING_FORK_BLKNUM=2 ** 98,
    # Trace
    TRACE_TRANSACTIONS=False
)
assert default_config['NEPHEW_REWARD'] == \
    default_config['BLOCK_REWARD'] // 32


class Env(object):

    def __init__(self, db, config=None, global_config=None):
        assert isinstance(db, BaseDB)
        self.db = db
        self.config = config or dict(default_config)
        self.global_config = global_config or dict()
