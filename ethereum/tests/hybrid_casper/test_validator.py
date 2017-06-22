import copy
import pytest
from ethereum import utils
from ethereum.tools import tester
from ethereum.tests.utils import new_db
from ethereum.db import EphemDB
from ethereum.hybrid_casper import casper_utils, validator
from ethereum.slogging import get_logger
logger = get_logger()

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
    return validator.mine_and_broadcast_blocks(number_of_blocks=number_of_blocks)

def test_validator(db):
    """"
    TODO
    """
    # keys = tester.keys[:5]
    genesis = casper_utils.make_casper_genesis(k0, ALLOC, EPOCH_LENGTH, SLASH_DELAY)
    network = validator.Network()
    t = tester.Chain(genesis=genesis)
    casper = tester.ABIContract(t, casper_utils.casper_abi, t.chain.env.config['CASPER_ADDRESS'])
    casper.initiate()
    t.mine(26)
    init_val_addr = utils.privtoaddr(k0)
    init_val_valcode_addr = utils.mk_contract_address(init_val_addr, 2)
    validators = [validator.Validator(k0, copy.deepcopy(genesis), network, mining=True, valcode_addr=init_val_valcode_addr)]
    # validators[0].mine_and_broadcast_blocks(1)
    mine_epochs(validators[0], 1)
    print('~~~ end ~~~')
    for i in range(1, 100):
        try:
            block = validators[0].chain.get_block_by_number(i)
            print(block.hash)
            print(block.transactions)
        except Exception as e:
            print(e)
            break
    assert False
