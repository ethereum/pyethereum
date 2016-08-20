from ethereum import ethash, ethash_utils, utils
from ethereum.block import Block, BlockHeader
import time
import sys
from ethereum.utils import sha3
import warnings
from collections import OrderedDict
from ethereum.slogging import get_logger
import rlp
from ethereum.state_transition import calc_difficulty, check_gaslimit, \
    initialize
from ethereum.config import default_config

# Gas limit adjustment algo
def calc_gaslimit(parent, config=default_config):
    decay = parent.gas_limit // config['GASLIMIT_EMA_FACTOR']
    new_contribution = ((parent.gas_used * config['BLKLIM_FACTOR_NOM']) //
                        config['BLKLIM_FACTOR_DEN'] // config['GASLIMIT_EMA_FACTOR'])
    gl = max(parent.gas_limit - decay + new_contribution, config['MIN_GAS_LIMIT'])
    if gl < config['GENESIS_GAS_LIMIT']:
        gl2 = parent.gas_limit + decay
        gl = min(config['GENESIS_GAS_LIMIT'], gl2)
    assert check_gaslimit(parent, gl, config=config)
    return gl


def get_uncle_candidates(chain, state):
    uncles = []
    ineligible = {}
    for h, _uncles in state.recent_uncles.items():
        for u in _uncles:
            ineligible[u] = True
    for i in range(0, min(state.config['MAX_UNCLE_DEPTH'], len((state.prev_headers)))):
        ineligible[state.prev_headers[i].hash] = True
    for i in range(1, min(state.config['MAX_UNCLE_DEPTH'], len(state.prev_headers))):
        child_hashes = chain.get_child_hashes(state.prev_headers[i].hash)
        for c in child_hashes:
            if c not in ineligible and len(uncles) < 2:
                uncles.append(chain.get_block(c).header)
        if len(uncles) == 2:
            break
    return uncles


def ethereum1_setup_block(chain, state=None, timestamp=None, coinbase='\x35'*20, extra_data='moo ha ha says the laughing cow.'):
    state = state or chain.state
    blk = Block(BlockHeader())
    now = timestamp or chain.time()
    blk.header.number = state.block_number + 1
    blk.header.difficulty = calc_difficulty(state.prev_headers[0], now, chain.config)
    blk.header.gas_limit = calc_gaslimit(state.prev_headers[0], chain.config)
    blk.header.timestamp = max(now, state.prev_headers[0].timestamp + 1)
    blk.header.prevhash = state.prev_headers[0].hash
    blk.header.coinbase = coinbase
    blk.header.extra_data = extra_data
    blk.header.bloom = 0
    blk.transactions = []
    blk.uncles = get_uncle_candidates(chain, state)
    blk.header.uncles_hash = sha3(rlp.encode(blk.uncles))
    initialize(state, blk)
    return blk
