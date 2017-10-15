from ethereum.config import default_config
from ethereum.block import Block, BlockHeader
from ethereum import trie
from ethereum.db import EphemDB
from ethereum.utils import sha3, encode_hex
import rlp
from ethereum.slogging import get_logger
from ethereum.exceptions import InsufficientBalance, BlockGasLimitReached, \
    InsufficientStartGas, InvalidNonce, UnsignedTransaction
from ethereum.messages import apply_transaction
log = get_logger('eth.block')


# Gas limit adjustment algo
def calc_gaslimit(parent, config=default_config):
    decay = parent.gas_limit // config['GASLIMIT_EMA_FACTOR']
    new_contribution = ((parent.gas_used * config['BLKLIM_FACTOR_NOM']) //
                        config['BLKLIM_FACTOR_DEN'] // config['GASLIMIT_EMA_FACTOR'])
    gl = max(
        parent.gas_limit -
        decay +
        new_contribution,
        config['MIN_GAS_LIMIT'])
    if gl < config['GENESIS_GAS_LIMIT']:
        gl2 = parent.gas_limit + decay
        gl = min(config['GENESIS_GAS_LIMIT'], gl2)
    assert check_gaslimit(parent, gl, config=config)
    return gl


def check_gaslimit(parent, gas_limit, config=default_config):
    #  block.gasLimit - parent.gasLimit <= parent.gasLimit // GasLimitBoundDivisor
    gl = parent.gas_limit // config['GASLIMIT_ADJMAX_FACTOR']
    a = bool(abs(gas_limit - parent.gas_limit) <= gl)
    b = bool(gas_limit >= config['MIN_GAS_LIMIT'])
    return a and b


# Difficulty adjustment algo
def calc_difficulty(parent, timestamp, config=default_config):
    # Special case for test chains
    if parent.difficulty == 1:
        return 1
    offset = parent.difficulty // config['BLOCK_DIFF_FACTOR']
    if parent.number >= (config['METROPOLIS_FORK_BLKNUM'] - 1):
        sign = max((2 if parent.uncles_hash != sha3(rlp.encode([])) else 1) -
                   ((timestamp - parent.timestamp) // config['METROPOLIS_DIFF_ADJUSTMENT_CUTOFF']), -99)
    elif parent.number >= (config['HOMESTEAD_FORK_BLKNUM'] - 1):
        sign = max(1 - ((timestamp - parent.timestamp) //
                        config['HOMESTEAD_DIFF_ADJUSTMENT_CUTOFF']), -99)
    else:
        sign = 1 if timestamp - \
            parent.timestamp < config['DIFF_ADJUSTMENT_CUTOFF'] else -1
    # If we enter a special mode where the genesis difficulty starts off below
    # the minimal difficulty, we allow low-difficulty blocks (this will never
    # happen in the official protocol)
    o = int(max(parent.difficulty + offset * sign,
                min(parent.difficulty, config['MIN_DIFF'])))
    period_count = (parent.number + 1) // config['EXPDIFF_PERIOD']
    if parent.number >= (config['METROPOLIS_FORK_BLKNUM'] - 1):
        period_count -= config['METROPOLIS_DELAY_PERIODS']
    if period_count >= config['EXPDIFF_FREE_PERIODS']:
        o = max(o + 2**(period_count -
                        config['EXPDIFF_FREE_PERIODS']), config['MIN_DIFF'])
    return o


# Given a parent state, initialize a block with the given arguments
def mk_block_from_prevstate(chain, state=None, timestamp=None,
                            coinbase=b'\x35' * 20, extra_data='moo ha ha says the laughing cow.'):
    state = state or chain.state
    blk = Block(BlockHeader())
    now = timestamp or chain.time()
    blk.header.number = state.prev_headers[0].number + 1
    blk.header.difficulty = calc_difficulty(
        state.prev_headers[0], now, chain.config)
    blk.header.gas_limit = calc_gaslimit(state.prev_headers[0], chain.config)
    blk.header.timestamp = max(now, state.prev_headers[0].timestamp + 1)
    blk.header.prevhash = state.prev_headers[0].hash
    blk.header.coinbase = coinbase
    blk.header.extra_data = extra_data
    blk.header.bloom = 0
    blk.transactions = []
    return blk


# Validate a block header
def validate_header(state, header):
    parent = state.prev_headers[0]
    if parent:
        if header.prevhash != parent.hash:
            raise ValueError("Block's prevhash and parent's hash do not match: block prevhash %s parent hash %s" %
                             (encode_hex(header.prevhash), encode_hex(parent.hash)))
        if header.number != parent.number + 1:
            raise ValueError(
                "Block's number is not the successor of its parent number")
        if not check_gaslimit(parent, header.gas_limit, config=state.config):
            raise ValueError(
                "Block's gaslimit is inconsistent with its parent's gaslimit")
        if header.difficulty != calc_difficulty(
                parent, header.timestamp, config=state.config):
            raise ValueError("Block's difficulty is inconsistent with its parent's difficulty: parent %d expected %d actual %d. Time diff %d" %
                             (parent.difficulty, calc_difficulty(parent, header.timestamp, config=state.config), header.difficulty, header.timestamp - parent.timestamp))
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
    if 0 <= header.number - \
            state.config["DAO_FORK_BLKNUM"] < 10 and header.extra_data != state.config["DAO_FORK_BLKEXTRA"]:
        raise ValueError("Missing extra data for block near DAO fork")
    return True


# Add transactions
def add_transactions(state, block, txqueue, min_gasprice=0):
    if not txqueue:
        return
    pre_txs = len(block.transactions)
    log.info('Adding transactions, %d in txqueue, %d dunkles' %
             (len(txqueue.txs), pre_txs))
    while True:
        tx = txqueue.pop_transaction(max_gas=state.gas_limit - state.gas_used,
                                     min_gasprice=min_gasprice)
        if tx is None:
            break
        try:
            apply_transaction(state, tx)
            block.transactions.append(tx)
        except (InsufficientBalance, BlockGasLimitReached, InsufficientStartGas,
                InvalidNonce, UnsignedTransaction) as e:
            log.error(e)
    log.info('Added %d transactions' % (len(block.transactions) - pre_txs))


# Validate that the transaction list root is correct
def validate_transaction_tree(state, block):
    if block.header.tx_list_root != mk_transaction_sha(block.transactions):
        raise ValueError("Transaction root mismatch: header %s computed %s, %d transactions" %
                         (encode_hex(block.header.tx_list_root), encode_hex(mk_transaction_sha(block.transactions)),
                          len(block.transactions)))
    return True


# Set state root, receipt root, etc
def set_execution_results(state, block):
    block.header.receipts_root = mk_receipt_sha(state.receipts)
    block.header.tx_list_root = mk_transaction_sha(block.transactions)
    state.commit()
    block.header.state_root = state.trie.root_hash
    block.header.gas_used = state.gas_used
    block.header.bloom = state.bloom
    log.info('Block pre-sealed, %d gas used' % state.gas_used)


# Verify state root, receipt root, etc
def verify_execution_results(state, block):
    if block.header.bloom != state.bloom:
        raise ValueError("Bloom mismatch: header %d computed %d" %
                         (block.header.bloom, state.bloom))
    state.commit()
    if block.header.state_root != state.trie.root_hash:
        raise ValueError("State root mismatch: header %s computed %s" %
                         (encode_hex(block.header.state_root), encode_hex(state.trie.root_hash)))
    if block.header.receipts_root != mk_receipt_sha(state.receipts):
        raise ValueError("Receipt root mismatch: header %s computed %s, gas used header %d computed %d, %d receipts" %
                         (encode_hex(block.header.receipts_root), encode_hex(mk_receipt_sha(state.receipts)),
                          block.header.gas_used, state.gas_used, len(state.receipts)))
    if block.header.gas_used != state.gas_used:
        raise ValueError("Gas used mismatch: header %d computed %d" %
                         (block.header.gas_used, state.gas_used))
    return True


# Make the root of a receipt tree
def mk_receipt_sha(receipts):
    t = trie.Trie(EphemDB())
    for i, receipt in enumerate(receipts):
        t.update(rlp.encode(i), rlp.encode(receipt))
    return t.root_hash


# Make the root of a transaction tree
mk_transaction_sha = mk_receipt_sha


# State changes after block finalized
def post_finalize(state, block):
    state.add_block_header(block.header)


# Update block variables into the state
def update_block_env_variables(state, block):
    state.timestamp = block.header.timestamp
    state.gas_limit = block.header.gas_limit
    state.block_number = block.header.number
    state.recent_uncles[state.block_number] = [x.hash for x in block.uncles]
    state.block_coinbase = block.header.coinbase
    state.block_difficulty = block.header.difficulty
