from ethereum.slogging import get_logger
log = get_logger('eth.block_creation')
from ethereum.block import Block, BlockHeader
from ethereum.common import mk_block_from_prevstate, validate_header, \
    verify_execution_results, validate_transaction_tree, \
    set_execution_results, add_transactions, post_finalize
from ethereum.consensus_strategy import get_consensus_strategy
from ethereum.messages import apply_transaction
from ethereum.state import State
from ethereum.utils import sha3, encode_hex
import rlp


# Applies the block-level state transition function
def apply_block(state, block):
    # Pre-processing and verification
    snapshot = state.snapshot()
    cs = get_consensus_strategy(state.config)
    try:
        # Start a new block context
        cs.initialize(state, block)
        # Basic validation
        assert validate_header(state, block.header)
        assert cs.check_seal(state, block.header)
        assert cs.validate_uncles(state, block)
        assert validate_transaction_tree(state, block)
        # Process transactions
        for tx in block.transactions:
            apply_transaction(state, tx)
        # Finalize (incl paying block rewards)
        cs.finalize(state, block)
        # Verify state root, tx list root, receipt root
        #print('std', state.to_dict())
        assert verify_execution_results(state, block)
        # Post-finalize (ie. add the block header to the state for now)
        post_finalize(state, block)
    except (ValueError, AssertionError) as e:
        state.revert(snapshot)
        raise e
    return state


# Creates a candidate block on top of the given chain
def make_head_candidate(chain, txqueue=None,
                        parent=None,
                        timestamp=None,
                        coinbase=b'\x35' * 20,
                        extra_data='moo ha ha says the laughing cow.',
                        min_gasprice=0):
    log.debug('Creating head candidate')
    if parent is None:
        temp_state = State.from_snapshot(
            chain.state.to_snapshot(
                root_only=True), chain.env)
    else:
        temp_state = chain.mk_poststate_of_blockhash(parent.hash)

    cs = get_consensus_strategy(chain.env.config)
    # Initialize a block with the given parent and variables
    blk = mk_block_from_prevstate(
        chain,
        temp_state,
        timestamp,
        coinbase,
        extra_data)
    # Find and set the uncles
    blk.uncles = cs.get_uncles(chain, temp_state)
    blk.header.uncles_hash = sha3(rlp.encode(blk.uncles))
    # Call the initialize state transition function
    cs.initialize(temp_state, blk)
    # Add transactions
    add_transactions(temp_state, blk, txqueue, min_gasprice)
    # Call the finalize state transition function
    cs.finalize(temp_state, blk)
    # Set state root, receipt root, etc
    set_execution_results(temp_state, blk)
    log.debug('Created head candidate successfully')
    return blk, temp_state
