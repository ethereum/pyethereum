class ConsensusStrategy(object):
    def __init__(self, **kwargs):
        assert sorted(kwargs.keys()) == sorted(['check_seal', 'validate_uncles', 'initialize',
                                                'finalize', 'get_uncles'])
        for k, v in kwargs.items():
            setattr(self, k, v)


def get_consensus_strategy(config):
    if config['CONSENSUS_STRATEGY'] in (
            'pow', 'ethpow', 'ethash', 'ethereum1'):
        from ethereum.pow.consensus import check_pow, validate_uncles, \
            initialize, finalize, get_uncle_candidates
        return ConsensusStrategy(
            check_seal=check_pow,
            validate_uncles=validate_uncles,
            initialize=initialize,
            finalize=finalize,
            get_uncles=get_uncle_candidates,
        )
    elif config['CONSENSUS_STRATEGY'] == 'hybrid_casper':
        from ethereum.hybrid_casper.consensus import initialize
        from ethereum.pow.consensus import check_pow, validate_uncles, \
            finalize, get_uncle_candidates
        return ConsensusStrategy(
            check_seal=check_pow,
            validate_uncles=validate_uncles,
            initialize=initialize,
            finalize=finalize,
            get_uncles=get_uncle_candidates,
        )
    else:
        raise Exception("Please set a consensus strategy! (pow, casper)")
