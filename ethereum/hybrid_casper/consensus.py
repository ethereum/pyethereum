from ethereum import utils
from ethereum.common import update_block_env_variables

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
            state.transfer_value(acct, state.config['DAO_WITHDRAWER'], state.get_balance(acct))

    if state.is_METROPOLIS(at_fork_height=True):
        state.set_code(utils.normalize_address(
            config["METROPOLIS_STATEROOT_STORE"]), config["METROPOLIS_GETTER_CODE"])
        state.set_code(utils.normalize_address(
            config["METROPOLIS_BLOCKHASH_STORE"]), config["METROPOLIS_GETTER_CODE"])
