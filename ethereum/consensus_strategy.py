class ConsensusStrategy(object):
    def __init__(self, header_validate, uncle_validate, block_pre_finalize, block_post_finalize, state_initialize):
        self.header_validate=header_validate
        self.uncle_validate=uncle_validate
        self.block_pre_finalize=block_pre_finalize
        self.block_post_finalize=block_post_finalize
        self.state_initialize = state_initialize

def get_consensus_strategy(config):
    if config['CONSENSUS_STRATEGY'] in ('pow', 'ethereum1'):
        from ethpow_utils import ethereum1_validate_header, ethereum1_validate_uncle, ethereum1_pre_finalize_block, ethereum1_post_finalize_block
        return ConsensusStrategy(
            header_validate=ethereum1_validate_header,
            uncle_validate=ethereum1_validate_uncle,
            block_pre_finalize=ethereum1_pre_finalize_block,
            block_post_finalize=ethereum1_post_finalize_block,
            state_initialize=None
        )
    elif config['CONSENSUS_STRATEGY'] == 'casper':
        from casper_utils import casper_validate_header, casper_state_initialize, casper_post_finalize_block
        return ConsensusStrategy(
            header_validate=casper_validate_header,
            uncle_validate=None,
            block_pre_finalize=None,
            block_post_finalize=casper_post_finalize_block,
            state_initialize=casper_state_initialize
        )
    else:
       raise Exception("Please set a consensus strategy! (pow, casper)")
