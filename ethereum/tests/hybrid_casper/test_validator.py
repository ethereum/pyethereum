import copy
import pytest
from ethereum import utils
from ethereum.tools import tester
from ethereum.meta import make_head_candidate
from ethereum.pow.ethpow import Miner
from ethereum.tests.utils import new_db
from ethereum.db import EphemDB
from ethereum.hybrid_casper import casper_utils, validator
from ethereum.slogging import get_logger
log = get_logger('test.validator')

_db = new_db()

# from ethereum.slogging import configure_logging
# config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace,eth.pb.msg:trace,eth.pb.tx:debug'
# configure_logging(config_string=config_string)

EPOCH_LENGTH = 25
SLASH_DELAY = 864
ALLOC = {a: {'balance': 5*10**19} for a in tester.accounts[:10]}
k0, k1, k2, k3, k4, k5, k6, k7, k8, k9 = tester.keys[:10]
a0, a1, a2, a3, a4, a5, a6, a7, a8, a9 = tester.accounts[:10]


@pytest.fixture(scope='function')
def db():
    return EphemDB()
alt_db = db

def init_multi_validator_casper(num_validators):
    """"
    Initialize Casper genesis, login an initial validator, and create num_validators validators
    """
    # Begin tests
    genesis = casper_utils.make_casper_genesis(ALLOC, EPOCH_LENGTH, 25, 0.02, 0.002)
    t = tester.Chain(genesis=genesis)
    casper = tester.ABIContract(t, casper_utils.casper_abi, t.chain.config['CASPER_ADDRESS'])
    # Get the val code addresses and network
    network = validator.Network()
    # Initialize validators, starting with the first validator
    validators = []
    # Add our validators
    for i in range(0, num_validators):
        log.info('Adding validator {}'.format(i))
        validators.append(validator.Validator(tester.keys[i], copy.deepcopy(genesis), network))
    t = tester.Chain(genesis=genesis)
    casper = tester.ABIContract(t, casper_utils.casper_abi, t.chain.env.config['CASPER_ADDRESS'])
    t.mine(26)
    # Pump the blocks into the validators
    for i in range(1, 27):
        block = t.chain.get_block_by_number(i)
        log.info('Pumping block: {} {}'.format(utils.encode_hex(block.hash), block.transactions))
        for v in validators:
            v.chain.add_block(block)
    if num_validators < 1:
        return t, casper
    # Submit deposits for new validators
    for i in range(0, num_validators):
        validators[i].broadcast_deposit()
        validators[0].mine_and_broadcast_blocks(1)
    return t, casper, validators


# Mines blocks required for number_of_epochs epoch changes, plus an offset of 2 blocks
def mine_epochs(validator, number_of_epochs):
    distance_to_next_epoch = (EPOCH_LENGTH - validator.chain.state.block_number) % EPOCH_LENGTH
    number_of_blocks = distance_to_next_epoch + EPOCH_LENGTH*(number_of_epochs-1) + 2
    end_block = validator.chain.state.block_number + number_of_blocks
    while validator.chain.state.block_number < end_block:
        last_block = validator.mine_and_broadcast_blocks(1)
    return last_block

def mk_casper_tester(validator):
    return tester.ABIContract(tester.State(validator.chain.state), casper_utils.casper_abi, validator.chain.casper_address)

def log_chain(validator):
    # Log the main chain up to 10000 blocks
    for i in range(1, 10000):
        try:
            block = validator.chain.get_block_by_number(i)
            if validator.chain.get_block_by_number(i).header.number % EPOCH_LENGTH == 0:
                log.info('~~~ Epoch: {} ~~~'.format(i / EPOCH_LENGTH))
            log.info('{} {}'.format(utils.encode_hex(block.hash), block.transactions))
        except AttributeError:
            break

def test_validate_sequential_epochs(db):
    """"
    Create 3 validators, mine 4 epochs, and make sure everything went through properly
    """
    # Enable validator logging
    t, casper, validators = init_multi_validator_casper(3)
    validators[0].mining = True
    # Mine enough epochs to log everyone in
    mine_epochs(validators[0], 3)
    # Check all validators are logged in
    casper = mk_casper_tester(validators[0])
    assert casper.get_dynasty() == 4
    assert 9 * 10**18 <= casper.get_total_curdyn_deposits() < 10 * 10**18
    # Mine two epochs, checking that everyone prepares and commits
    for i in range(4, 6):
        mine_epochs(validators[0], 1)
        # Make sure each validator's prev_commit_epoch is correct
        for v in validators:
            assert v.prev_commit_epoch == i
        # Make sure the hash for the epoch is justified
        casper = mk_casper_tester(validators[0])
        cp_hash = validators[0].chain.get_block_by_number(i*EPOCH_LENGTH).hash
        assert validators[0].chain.get_checkpoint_score(cp_hash) >= 0.6
    # Log the first validator's chain
    log_chain(validators[0])

def test_validate_epochs_skipping_one(db):
    """"
    Create 3 validators, validate an epoch, then skip one, and then mine the next one. Make sure the correct info was submitted
    """
    # Enable validator logging
    t, casper, validators = init_multi_validator_casper(3)
    validators[0].mining = True
    # Mine enough epochs to log everyone in, and then mine one more where everyone is able to prepare & commit
    mine_epochs(validators[0], 3)
    # Mine the fourth epoch without including any Casper transactions
    validators[0].mining = False
    for i in range(EPOCH_LENGTH):
        head_candidate, head_candidate_state = make_head_candidate(
            validators[0].chain, timestamp=validators[0].chain.state.timestamp + 14)
        block = Miner(head_candidate).mine(rounds=100, start_nonce=0)
        validators[0].broadcast_newblock(block)
    # Make sure our prev_commit_epoch is for epoch 3
    for v in validators:
        assert v.prev_commit_epoch == 3
    # Now mine the 5th epoch
    validators[0].mining = True
    mine_epochs(validators[0], 1)
    # Check that the prev_commit_epoch is 5
    for v in validators:
        assert v.prev_commit_epoch == 5
    # Make sure the hash for the epoch is justified and the epoch is committed
    cp_hash = validators[0].chain.get_block_by_number(5*EPOCH_LENGTH).hash
    assert validators[0].chain.get_checkpoint_score(cp_hash) >= 0.6
    # Make sure epoch 4 was not committed
    cp_4_hash = validators[0].chain.get_block_by_number(4*EPOCH_LENGTH).hash
    assert validators[0].chain.get_checkpoint_score(cp_4_hash) == 0
    # TODO: Check that the ancestry hash is correct
    # Log the first validator's chain
    log_chain(validators[0])

def test_withdrawl(db):
    """"
    Create 3 validators, log one out, and check that the logout was successful
    """
    # Enable validator logging
    t, casper, validators = init_multi_validator_casper(3)
    validators[0].mining = True
    # Mine enough epochs to log everyone in, and then mine one more where everyone is able to prepare & commit
    mine_epochs(validators[0], 3)
    # Submit a logout tx which should logout our 3rd validator
    validators[2].broadcast_logout(0)
    # Mine the logout tx and finish the epoch
    mine_epochs(validators[0], 1)
    casper = mk_casper_tester(validators[0])
    log.info('Dynasty: {}'.format(casper.get_dynasty()))
    # Check that all three validators are logged in
    assert 9 * 10**18 <= casper.get_total_curdyn_deposits() < 10 * 10**18
    # Mine & finalize enough epochs to logout the validator
    mine_epochs(validators[0], 2)
    casper = mk_casper_tester(validators[0])
    # Check that only two validators are logged in
    assert 6 * 10**18 <= casper.get_total_curdyn_deposits() < 7 * 10**18
    # TODO: For bonus points, verify this works when an epoch is not finalized!
    # Log the first validator's chain
    log_chain(validators[0])
