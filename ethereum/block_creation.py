import time
import rlp
from ethereum.config import default_config
from ethereum.state_transition import check_gaslimit, initialize, \
    validate_uncles, pre_seal_finalize, mk_receipt_sha, mk_transaction_sha, \
    apply_transaction
from ethereum.consensus_strategy import get_consensus_strategy
from ethereum.exceptions import InsufficientBalance, BlockGasLimitReached, \
    InsufficientStartGas, InvalidNonce, UnsignedTransaction
from ethereum.utils import sha3
from ethereum.state import State
from ethereum import casper_utils, ethpow_utils
from ethereum.slogging import get_logger
log = get_logger('eth.block_creation')


def add_transactions(state, block, txqueue, min_gasprice=0):
    pre_txs = len(block.transactions)
    log.info('Adding transactions, %d in txqueue, %d dunkles' % (len(txqueue.txs), pre_txs))
    while 1:
        tx = txqueue.pop_transaction(max_gas=state.gas_limit - state.gas_used,
                                     min_gasprice=min_gasprice)
        if tx is None:
            break
        try:
            apply_transaction(state, tx)
            block.transactions.append(tx)
        except (InsufficientBalance, BlockGasLimitReached, InsufficientStartGas,
                InvalidNonce, UnsignedTransaction), e:
            pass
    log.info('Added %d transactions' % (len(block.transactions) - pre_txs))


def pre_seal(state, block):
    pre_seal_finalize(state, block)
    block.header.receipts_root = mk_receipt_sha(state.receipts)
    block.header.tx_list_root = mk_transaction_sha(block.transactions)
    state.commit()
    block.header.state_root = state.trie.root_hash
    block.header.gas_used = state.gas_used
    block.header.bloom = state.bloom
    log.info('Block pre-sealed, %d gas used' % state.gas_used)


def make_head_candidate(chain, txqueue,
                        parent=None,
                        timestamp=None,
                        coinbase='\x35'*20,
                        extra_data='moo ha ha says the laughing cow.',
                        min_gasprice=0):
    log.info('Creating head candidate')
    if parent is None:
        temp_state = State.from_snapshot(chain.state.to_snapshot(root_only=True), chain.env)
    else:
        temp_state = chain.mk_poststate_of_blockhash(parent.hash)

    cs = get_consensus_strategy(chain.env.config)
    cs.block_setup(chain, temp_state, timestamp, coinbase, extra_data)
    add_transactions(temp_state, block, txqueue, min_gasprice)
    pre_seal(temp_state, block)
    assert validate_uncles(temp_state, block)
    log.info('Created head candidate successfully')
    return block
