import copy
import pytest
from ethereum import utils
from ethereum.tools import tester
from ethereum.tests.utils import new_db
from ethereum.db import EphemDB
from ethereum.hybrid_casper import casper_utils, validator
from ethereum.slogging import get_logger, configure_logging
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

def init_chain_and_casper():
    genesis = casper_utils.make_casper_genesis(k0, ALLOC, EPOCH_LENGTH, SLASH_DELAY)
    t = tester.Chain(genesis=genesis)
    casper = tester.ABIContract(t, casper_utils.casper_abi, t.chain.env.config['CASPER_ADDRESS'])
    casper.initiate()
    return t, casper

# Mines blocks required for number_of_epochs epoch changes, plus an offset of 2 blocks
def mine_epochs(validator, number_of_epochs):
    distance_to_next_epoch = (EPOCH_LENGTH - validator.chain.state.block_number) % EPOCH_LENGTH
    number_of_blocks = distance_to_next_epoch + EPOCH_LENGTH*(number_of_epochs-1) + 2
    end_block = validator.chain.state.block_number + number_of_blocks
    while validator.chain.state.block_number < end_block:
        last_block = validator.mine_and_broadcast_blocks(1)
    return last_block

def test_validator(db):
    """"
    Create 5 validators, mine 5 epochs, and make sure all of the prev_commit_epoch's are for the 5th epoch
    """
    # Enable validator logging
    config_string = 'eth.validator:info,eth.chain:info,test.validator:info'
    configure_logging(config_string=config_string)
    # Begin tests
    genesis = casper_utils.make_casper_genesis(k0, ALLOC, EPOCH_LENGTH, SLASH_DELAY)
    network = validator.Network()
    t = tester.Chain(genesis=genesis)
    casper = tester.ABIContract(t, casper_utils.casper_abi, t.chain.env.config['CASPER_ADDRESS'])
    casper.initiate()
    t.mine(26)
    init_val_addr = utils.privtoaddr(k0)
    init_val_valcode_addr = utils.mk_contract_address(init_val_addr, 2)

    validators = [validator.Validator(k0, copy.deepcopy(genesis), network, mining=True, valcode_addr=init_val_valcode_addr)]
    # Add four more validators
    for i in range(1, 5):
        log.info('Adding validator {}'.format(i))
        validators.append(validator.Validator(tester.keys[i], copy.deepcopy(genesis), network))
    # Submit deposits for new validators
    for i in range(1, 5):
        validators[i].broadcast_deposit()
    mine_epochs(validators[0], 5)
    for i in range(1, 10000):
        try:
            block = validators[0].chain.get_block_by_number(i)
            if validators[0].chain.get_block_by_number(i).header.number % EPOCH_LENGTH == 0:
                log.info('~~~ Epoch: {} ~~~'.format(i / EPOCH_LENGTH))
            log.info('{} {}'.format(utils.encode_hex(block.hash), block.transactions))
        except AttributeError:
            break
    for v in validators:
        assert v.prev_commit_epoch == 5
