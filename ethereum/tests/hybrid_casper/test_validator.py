import copy
import pytest
from ethereum import utils
from ethereum.tools import tester
from ethereum.tests.utils import new_db
from ethereum.db import EphemDB
from ethereum.hybrid_casper import casper_utils, validator
from ethereum.hybrid_casper.casper_utils import mk_prepare, mk_commit
from ethereum.slogging import get_logger
from ethereum.messages import apply_transaction
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

def init_multi_validator_chain_and_casper(validator_keys):
    t, casper = init_chain_and_casper()
    mine_epochs(t, 1)
    for k in validator_keys[1:]:
        valcode_addr = t.tx(k0, '', 0, casper_utils.mk_validation_code(utils.privtoaddr(k)))
        assert utils.big_endian_to_int(t.call(k0, casper_utils.purity_checker_address, 0, casper_utils.ct.encode('submit', [valcode_addr]))) == 1
        casper.deposit(valcode_addr, utils.privtoaddr(k), value=3 * 10**18)
        t.mine()
    casper.prepare(mk_prepare(0, 1, epoch_blockhash(t, 1), epoch_blockhash(t, 0), 0, epoch_blockhash(t, 0), k0))
    casper.commit(mk_commit(0, 1, epoch_blockhash(t, 1), 0, k0))
    epoch_1_anchash = utils.sha3(epoch_blockhash(t, 1) + epoch_blockhash(t, 0))
    assert casper.get_consensus_messages__committed(1)
    mine_epochs(t, 1)
    assert casper.get_dynasty() == 1
    casper.prepare(mk_prepare(0, 2, epoch_blockhash(t, 2), epoch_1_anchash, 1, epoch_1_anchash, k0))
    casper.commit(mk_commit(0, 2, epoch_blockhash(t, 2), 1, k0))
    casper.get_consensus_messages__committed(2)
    mine_epochs(t, 1)
    assert casper.get_dynasty() == 2
    return t, casper

# Helper function for gettting blockhashes by epoch, based on the current chain
def epoch_blockhash(t, epoch):
    if epoch == 0:
        return b'\x00' * 32
    return t.head_state.prev_headers[epoch*EPOCH_LENGTH * -1 - 1].hash

# Mines blocks required for number_of_epochs epoch changes, plus an offset of 2 blocks
def mine_epochs(t, number_of_epochs):
    distance_to_next_epoch = (EPOCH_LENGTH - t.head_state.block_number) % EPOCH_LENGTH
    number_of_blocks = distance_to_next_epoch + EPOCH_LENGTH*(number_of_epochs-1) + 2
    return t.mine(number_of_blocks=number_of_blocks)

def test_head_change_for_more_commits(db):
    """"
    Local: L3_5, L4_1
    add
    Remote: R3_5, R5_2
    """
    keys = tester.keys[:5]
    genesis = casper_utils.make_casper_genesis(k0, ALLOC, EPOCH_LENGTH, SLASH_DELAY)
    network = validator.Network()
    t = tester.Chain(genesis=genesis)
    casper = tester.ABIContract(t, casper_utils.casper_abi, t.chain.env.config['CASPER_ADDRESS'])
    casper.initiate()
    t.mine()
    validators = []
    for i, k in enumerate(keys):
        validators.append(validator.Validator(k, copy.deepcopy(genesis), network))
    for v in validators:
        valcode_tx, deposit_tx = v.mk_deposit_transactions(3 * 10**18)
        valcode_success, o = apply_transaction(t.head_state, valcode_tx)
        deposit_success, o = apply_transaction(t.head_state, deposit_tx)
        assert valcode_success and deposit_success
        t.block.transactions.append(valcode_tx)
        t.block.transactions.append(deposit_tx)
        network.broadcast(t.mine())
    assert False
    # t, casper = init_multi_validator_chain_and_casper(keys)
    # epoch_1_anchash = utils.sha3(epoch_blockhash(t, 1) + epoch_blockhash(t, 0))
    # epoch_2_anchash = utils.sha3(epoch_blockhash(t, 2) + epoch_1_anchash)
    # # L3_5: Prepare and commit all
    # for i, k in enumerate(keys):
    #     casper.prepare(mk_prepare(i, 3, epoch_blockhash(t, 3), epoch_2_anchash, 2, epoch_2_anchash, k))
    #     t.mine()
    # for i, k in enumerate(keys):
    #     casper.commit(mk_commit(i, 3, epoch_blockhash(t, 3), 2 if i == 0 else 0, k))
    #     t.mine()
    # epoch_3_anchash = utils.sha3(epoch_blockhash(t, 3) + epoch_2_anchash)
    # root_hash = t.mine().hash
