from ethereum import utils, transactions
from ethereum.common import update_block_env_variables
from ethereum.messages import apply_transaction
from ethereum.hybrid_casper import casper_utils
from ethereum.utils import privtoaddr

# Block initialization state transition
def initialize(state, block=None):
    config = state.config

    state.txindex = 0
    state.gas_used = 0
    state.bloom = 0
    state.receipts = []

    if block is not None:
        update_block_env_variables(state, block)

    # Initalize the next epoch in the Casper contract
    if state.block_number % state.config['EPOCH_LENGTH'] == 0 and state.block_number != 0:
        key, account = state.config['NULL_SENDER'], privtoaddr(state.config['NULL_SENDER'])
        data = casper_utils.casper_translator.encode('initialize_epoch', [state.block_number // state.config['EPOCH_LENGTH']])
        transaction = transactions.Transaction(state.get_nonce(account), 0, 3141592,
                                               state.config['CASPER_ADDRESS'], 0, data).sign(key)
        success, output = apply_transaction(state, transaction)
        assert success

    if state.is_DAO(at_fork_height=True):
        for acct in state.config['CHILD_DAO_LIST']:
            state.transfer_value(
                acct,
                state.config['DAO_WITHDRAWER'],
                state.get_balance(acct))

    if state.is_METROPOLIS(at_fork_height=True):
        state.set_code(utils.normalize_address(
            config["METROPOLIS_STATEROOT_STORE"]), config["METROPOLIS_GETTER_CODE"])
        state.set_code(utils.normalize_address(
            config["METROPOLIS_BLOCKHASH_STORE"]), config["METROPOLIS_GETTER_CODE"])
