from ethereum.pow import ethash, ethash_utils, ethpow
from ethereum import utils
from ethereum.common import update_block_env_variables, calc_difficulty
from ethereum.exceptions import VerificationFailed
import rlp


# Block initialization state transition
def initialize(state, block=None):
    config = state.config

    state.txindex = 0
    state.gas_used = 0
    state.bloom = 0
    state.receipts = []

    if block is not None:
        update_block_env_variables(state, block)

    if state.is_DAO(at_fork_height=True):
        for acct in state.config['CHILD_DAO_LIST']:
            state.transfer_value(
                acct,
                state.config['DAO_WITHDRAWER'],
                state.get_balance(acct))

    # if state.is_METROPOLIS(at_fork_height=True):
    #     state.set_code(utils.normalize_address(
    #         config["METROPOLIS_STATEROOT_STORE"]), config["METROPOLIS_GETTER_CODE"])
    #     state.set_code(utils.normalize_address(
    # config["METROPOLIS_BLOCKHASH_STORE"]), config["METROPOLIS_GETTER_CODE"])


# Check that proof of work is valid
def check_pow(state, header):
    assert ethpow.check_pow(header.number, header.mining_hash, header.mixhash,
                            header.nonce, header.difficulty)
    return True


# Get uncle blocks to add to a block on the given state
def get_uncle_candidates(chain, state):
    uncles = []
    ineligible = {}
    for h, _uncles in state.recent_uncles.items():
        for u in _uncles:
            ineligible[u] = True
    for i in range(
            0, min(state.config['MAX_UNCLE_DEPTH'], len((state.prev_headers)))):
        ineligible[state.prev_headers[i].hash] = True
    for i in range(
            1, min(state.config['MAX_UNCLE_DEPTH'], len(state.prev_headers))):
        child_hashes = chain.get_child_hashes(state.prev_headers[i].hash)
        for c in child_hashes:
            if c not in ineligible and len(uncles) < 2:
                uncles.append(chain.get_block(c).header)
        if len(uncles) == 2:
            break
    return uncles


# Validate that a block has valid uncles
def validate_uncles(state, block):
    """Validate the uncles of this block."""
    # Make sure hash matches up
    if utils.sha3(rlp.encode(block.uncles)) != block.header.uncles_hash:
        raise VerificationFailed("Uncle hash mismatch")
    # Enforce maximum number of uncles
    if len(block.uncles) > state.config['MAX_UNCLES']:
        raise VerificationFailed("Too many uncles")
    # Uncle must have lower block number than blockj
    for uncle in block.uncles:
        if uncle.number >= block.header.number:
            raise VerificationFailed("Uncle number too high")

    # Check uncle validity
    MAX_UNCLE_DEPTH = state.config['MAX_UNCLE_DEPTH']
    ancestor_chain = [block.header] + \
        [a for a in state.prev_headers[:MAX_UNCLE_DEPTH + 1] if a]
    # Uncles of this block cannot be direct ancestors and cannot also
    # be uncles included 1-6 blocks ago
    ineligible = [b.hash for b in ancestor_chain]
    for blknum, uncles in state.recent_uncles.items():
        if state.block_number > int(
                blknum) >= state.block_number - MAX_UNCLE_DEPTH:
            ineligible.extend([u for u in uncles])
    eligible_ancestor_hashes = [x.hash for x in ancestor_chain[2:]]
    for uncle in block.uncles:
        if uncle.prevhash not in eligible_ancestor_hashes:
            raise VerificationFailed("Uncle does not have a valid ancestor")
        parent = [x for x in ancestor_chain if x.hash == uncle.prevhash][0]
        if uncle.difficulty != calc_difficulty(
                parent, uncle.timestamp, config=state.config):
            raise VerificationFailed("Difficulty mismatch")
        if uncle.number != parent.number + 1:
            raise VerificationFailed("Number mismatch")
        if uncle.timestamp < parent.timestamp:
            raise VerificationFailed("Timestamp mismatch")
        if uncle.hash in ineligible:
            raise VerificationFailed("Duplicate uncle")
        if uncle.gas_used > uncle.gas_limit:
            raise VerificationFailed("Uncle used too much gas")
        if not check_pow(state, uncle):
            raise VerificationFailed('uncle pow mismatch')
        ineligible.append(uncle.hash)
    return True


# Block finalization state transition
def finalize(state, block):
    """Apply rewards and commit."""

    if state.is_METROPOLIS():
        br = state.config['BYZANTIUM_BLOCK_REWARD']
        nr = state.config['BYZANTIUM_NEPHEW_REWARD']
    else:
        br = state.config['BLOCK_REWARD']
        nr = state.config['NEPHEW_REWARD']
        
    delta = int(br + nr * len(block.uncles))
    state.delta_balance(state.block_coinbase, delta)

    udpf = state.config['UNCLE_DEPTH_PENALTY_FACTOR']

    for uncle in block.uncles:
        r = int(br * (udpf + uncle.number - state.block_number) // udpf)
        state.delta_balance(uncle.coinbase, r)

    if state.block_number - \
            state.config['MAX_UNCLE_DEPTH'] in state.recent_uncles:
        del state.recent_uncles[state.block_number -
                                state.config['MAX_UNCLE_DEPTH']]
