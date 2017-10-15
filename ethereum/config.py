from rlp.utils import decode_hex

from ethereum import utils
from ethereum.db import BaseDB, EphemDB
from ethereum.child_dao_list import L as child_dao_list
import copy


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
    MAX_GAS_LIMIT=2 ** 63 - 1,
    # Gas limit adjustment algo:
    # block.gas_limit=block.parent.gas_limit * 1023/1024 +
    #                   (block.gas_used * 6 / 5) / 1024
    GASLIMIT_EMA_FACTOR=1024,
    GASLIMIT_ADJMAX_FACTOR=1024,
    BLOCK_GAS_LIMIT=4712388,
    BLKLIM_FACTOR_NOM=3,
    BLKLIM_FACTOR_DEN=2,
    # Network ID
    NETWORK_ID=1,
    # Block reward
    BLOCK_REWARD=5000 * utils.denoms.finney,
    NEPHEW_REWARD=5000 * utils.denoms.finney // 32,  # BLOCK_REWARD / 32
    # In Byzantium
    BYZANTIUM_BLOCK_REWARD=3000 * utils.denoms.finney,
    BYZANTIUM_NEPHEW_REWARD=3000 * utils.denoms.finney // 32,  # BLOCK_REWARD / 32
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
    # Delay in Byzantium
    METROPOLIS_DELAY_PERIODS=30,
    # Blank account initial nonce
    ACCOUNT_INITIAL_NONCE=0,
    # Homestead fork
    HOMESTEAD_FORK_BLKNUM=1150000,
    HOMESTEAD_DIFF_ADJUSTMENT_CUTOFF=10,
    # Metropolis fork
    METROPOLIS_FORK_BLKNUM=4370000,
    METROPOLIS_ENTRY_POINT=2 ** 160 - 1,
    METROPOLIS_STATEROOT_STORE=0x10,
    METROPOLIS_BLOCKHASH_STORE=0x20,
    METROPOLIS_WRAPAROUND=65536,
    METROPOLIS_GETTER_CODE=decode_hex('6000355460205260206020f3'),
    METROPOLIS_DIFF_ADJUSTMENT_CUTOFF=9,
    # Constantinople fork
    CONSTANTINOPLE_FORK_BLKNUM=2**100,
    # DAO fork
    DAO_FORK_BLKNUM=1920000,
    DAO_FORK_BLKHASH=decode_hex(
        '4985f5ca3d2afbec36529aa96f74de3cc10a2a4a6c44f2157a57d2c6059a11bb'),
    DAO_FORK_BLKEXTRA=decode_hex('64616f2d686172642d666f726b'),
    CHILD_DAO_LIST=list(map(utils.normalize_address, child_dao_list)),
    DAO_WITHDRAWER=utils.normalize_address(
        '0xbf4ed7b27f1d666546e30d74d50d173d20bca754'),
    # Anti-DoS fork
    ANTI_DOS_FORK_BLKNUM=2463000,
    SPURIOUS_DRAGON_FORK_BLKNUM=2675000,
    CONTRACT_CODE_SIZE_LIMIT=0x6000,
    # Default consensus strategy: ethash, poa, casper, pbft
    CONSENSUS_STRATEGY='ethash',
    # Serenity fork
    SERENITY_FORK_BLKNUM=2**99,
    PREV_HEADER_DEPTH=256,
    SYSTEM_ENTRY_POINT=utils.int_to_addr(2**160 - 2),
    SERENITY_HEADER_VERIFIER=utils.int_to_addr(255),
    SERENITY_HEADER_POST_FINALIZER=utils.int_to_addr(254),
    SERENITY_GETTER_CODE=decode_hex(
        '60ff331436604014161560155760203560003555005b6000355460205260206020f3'),
    # Custom specials
    CUSTOM_SPECIALS={},
)
assert default_config['NEPHEW_REWARD'] == \
    default_config['BLOCK_REWARD'] // 32


class Env(object):

    def __init__(self, db=None, config=None, global_config=None):
        self.db = EphemDB() if db is None else db
        assert isinstance(self.db, BaseDB)
        self.config = config or dict(default_config)
        self.global_config = global_config or dict()


config_frontier = copy.copy(default_config)
config_frontier["HOMESTEAD_FORK_BLKNUM"] = 2**99
config_frontier["ANTI_DOS_FORK_BLKNUM"] = 2**99
config_frontier["SPURIOUS_DRAGON_FORK_BLKNUM"] = 2**99
config_frontier["METROPOLIS_FORK_BLKNUM"] = 2**99
config_frontier["CONSTANTINOPLE_FORK_BLKNUM"] = 2**99

config_homestead = copy.copy(default_config)
config_homestead["HOMESTEAD_FORK_BLKNUM"] = 0
config_homestead["ANTI_DOS_FORK_BLKNUM"] = 2**99
config_homestead["SPURIOUS_DRAGON_FORK_BLKNUM"] = 2**99
config_homestead["METROPOLIS_FORK_BLKNUM"] = 2**99
config_homestead["CONSTANTINOPLE_FORK_BLKNUM"] = 2**99

config_tangerine = copy.copy(default_config)
config_tangerine["HOMESTEAD_FORK_BLKNUM"] = 0
config_tangerine["ANTI_DOS_FORK_BLKNUM"] = 0
config_tangerine["SPURIOUS_DRAGON_FORK_BLKNUM"] = 2**99
config_tangerine["METROPOLIS_FORK_BLKNUM"] = 2**99
config_tangerine["CONSTANTINOPLE_FORK_BLKNUM"] = 2**99

config_spurious = copy.copy(default_config)
config_spurious["HOMESTEAD_FORK_BLKNUM"] = 0
config_spurious["ANTI_DOS_FORK_BLKNUM"] = 0
config_spurious["SPURIOUS_DRAGON_FORK_BLKNUM"] = 0
config_spurious["METROPOLIS_FORK_BLKNUM"] = 2**99
config_spurious["CONSTANTINOPLE_FORK_BLKNUM"] = 2**99

config_metropolis = copy.copy(default_config)
config_metropolis["HOMESTEAD_FORK_BLKNUM"] = 0
config_metropolis["ANTI_DOS_FORK_BLKNUM"] = 0
config_metropolis["SPURIOUS_DRAGON_FORK_BLKNUM"] = 0
config_metropolis["METROPOLIS_FORK_BLKNUM"] = 0
config_metropolis["CONSTANTINOPLE_FORK_BLKNUM"] = 2**99
