from ethereum import utils
from ethereum.db import BaseDB
import time
from ethereum.utils import address, int256, trie_root, hash32, to_string, \
    sha3, zpad, normalize_address, int_to_addr, big_endian_to_int

# List of system addresses and global parameters
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
BLKTIME = 5
# Note that this parameter must be set in the Casper contract as well
ENTER_EXIT_DELAY = 100
