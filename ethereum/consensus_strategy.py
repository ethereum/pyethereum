class ConsensusStrategy(object):
    def __init__(self, state_initializer=None):
        self.state_initializer = state_initializer

def get_consensus_strategy(config):
    if config['CONSENSUS_STRATEGY'] in ('pow', 'ethereum1'):
        return ConsensusStrategy()
    elif config['CONSENSUS_STRATEGY'] == 'casper':
        from casper_utils import casper_state_initialize
        return ConsensusStrategy(
            state_initializer=casper_state_initialize
        )
    else:
       raise Exception("Please set a consensus strategy! (pow, casper)")
