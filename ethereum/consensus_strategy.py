class ConsensusStrategy(object):
    def __init__(self, header_validate, uncle_validate, state_initialize):
        self.header_validate=header_validate
        self.uncle_validate=uncle_validate
        self.state_initialize = state_initialize

def get_consensus_strategy(config):
    if config['CONSENSUS_STRATEGY'] in ('pow', 'ethereum1'):
        from ethpow_utils import ethereum1_validate_header, ethereum1_validate_uncle
        return ConsensusStrategy(
            header_validate=ethereum1_validate_header,
            uncle_validate=ethereum1_validate_uncle,
            state_initialize=None
        )
    elif config['CONSENSUS_STRATEGY'] == 'casper':
        from casper_utils import casper_validate_header, casper_state_initialize
        return ConsensusStrategy(
            header_validate=casper_validate_header,
            uncle_validate=None,
            state_initialize=casper_state_initialize
        )
    else:
       raise Exception("Please set a consensus strategy! (pow, casper)")
