# Update block variables into the state
def update_block_env_variables(state, block):
    state.timestamp = block.header.timestamp
    state.gas_limit = block.header.gas_limit
    state.block_number = block.header.number
    state.recent_uncles[state.block_number] = [x.hash for x in block.uncles]
    state.block_coinbase = block.header.coinbase
    state.block_difficulty = block.header.difficulty

# Block initialization state transition
def initialize(state, block=None):
    config = state.config

    state.txindex = 0
    state.gas_used = 0
    state.bloom = 0
    state.receipts = []

    if block != None:
        update_block_env_variables(state, block)

    if state.is_DAO(at_fork_height=True):
        for acct in state.config['CHILD_DAO_LIST']:
            state.transfer_value(acct, state.config['DAO_WITHDRAWER'], state.get_balance(acct))

    if state.is_METROPOLIS(at_fork_height=True):
        state.set_code(utils.normalize_address(
            config["METROPOLIS_STATEROOT_STORE"]), config["METROPOLIS_GETTER_CODE"])
        state.set_code(utils.normalize_address(
            config["METROPOLIS_BLOCKHASH_STORE"]), config["METROPOLIS_GETTER_CODE"])

