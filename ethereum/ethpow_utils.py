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
from ethereum.exceptions import VerificationFailed

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


def ethereum1_validate_header(state, header):
    assert header.check_pow()
    parent = state.prev_headers[0]
    if parent:
        if header.prevhash != parent.hash:
            raise ValueError("Block's prevhash and parent's hash do not match: block prevhash %s parent hash %s" %
                             (encode_hex(header.prevhash), encode_hex(parent.hash)))
        if header.number != parent.number + 1:
            raise ValueError("Block's number is not the successor of its parent number")
        if not check_gaslimit(parent, header.gas_limit, config=state.config):
            raise ValueError("Block's gaslimit is inconsistent with its parent's gaslimit")
        if header.difficulty != calc_difficulty(parent, header.timestamp, config=state.config):
            raise ValueError("Block's difficulty is inconsistent with its parent's difficulty: parent %d expected %d actual %d" %
                             (parent.difficulty, calc_difficulty(parent, header.timestamp, config=state.config), header.difficulty))
        if header.gas_used > header.gas_limit:
            raise ValueError("Gas used exceeds gas limit")
        if len(header.extra_data) > 32 and not state.is_SERENITY():
            raise ValueError("Extra data too long")
        if len(header.extra_data) > 1024:
            raise ValueError("Extra data too long")
        if header.timestamp <= parent.timestamp:
            raise ValueError("Timestamp equal to or before parent")
        if header.timestamp >= 2**256:
            raise ValueError("Timestamp waaaaaaaaaaayy too large")
    if header.gas_limit >= 2**63:
        raise ValueError("Header gas limit too high")
    return True

def ethereum1_validate_uncle(state, uncle):
    if not uncle.check_pow():
        raise VerificationFailed('pow mismatch')
    return True

def ethereum1_pre_finalize_block(state, block):
    """Apply rewards and commit."""
    delta = int(state.config['BLOCK_REWARD'] + state.config['NEPHEW_REWARD'] * len(block.uncles))
    state.delta_balance(state.block_coinbase, delta)

    br = state.config['BLOCK_REWARD']
    udpf = state.config['UNCLE_DEPTH_PENALTY_FACTOR']

    for uncle in block.uncles:
        r = int(br * (udpf + uncle.number - state.block_number) // udpf)
        state.delta_balance(uncle.coinbase, r)

    if state.block_number - state.config['MAX_UNCLE_DEPTH'] in state.recent_uncles:
        del state.recent_uncles[state.block_number - state.config['MAX_UNCLE_DEPTH']]

def ethereum1_post_finalize_block(state, block):
    if state.is_METROPOLIS():
        state.set_storage_data(utils.normalize_address(state.config["METROPOLIS_STATEROOT_STORE"]),
                               state.block_number % state.config["METROPOLIS_WRAPAROUND"],
                               state.trie.root_hash)
        state.set_storage_data(utils.normalize_address(state.config["METROPOLIS_BLOCKHASH_STORE"]),
                               state.block_number % state.config["METROPOLIS_WRAPAROUND"],
                               block.header.hash)
    state.add_block_header(block.header)
