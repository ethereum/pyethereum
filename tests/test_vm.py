import pytest
import json
import tempfile
import pyethereum.processblock as pb
import pyethereum.blocks as blocks
import pyethereum.transactions as transactions
import sys

import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()

tempdir = tempfile.mktemp()

filename = 'fixtures/vmtests.json' if len(sys.argv) == 2 else sys.argv[2]


def check_testdata(data_keys, expected_keys):
    assert set(data_keys) == set(expected_keys), \
        "test data changed, please adjust tests"


@pytest.fixture(scope="module")
def vm_tests_fixtures():
    """Read vm tests from fixtures"""
    # FIXME: assert that repo is uptodate
    try:
        vm_fixture = json.load(open(filename, 'r'))
    except IOError:
        raise IOError("Could not read vmtests.json from fixtures."
                      " Make sure you did 'git submodule init'!")
    check_testdata(vm_fixture.keys(),
                   [u'boolean', u'suicide', u'arith', u'mktx'])
    return vm_fixture


def test_boolean():
    do_test_vm('boolean')


def test_suicide():
    do_test_vm('suicide')


def test_arith():
    do_test_vm('arith')


def test_mktx():
    do_test_vm('mktx')


def do_test_vm(name):

    logger.debug('running test:%r', name)
    params = vm_tests_fixtures()[name]

    pre = params['pre']
    exek = params['exec']
    callcreates = params['callcreates']
    env = params['env']
    post = params['post']

    check_testdata(env.keys(), ['currentGasLimit', 'currentTimestamp',
                                'previousHash', 'currentCoinbase',
                                'currentDifficulty', 'currentNumber'])
    # setup env
    blk = blocks.Block(
        prevhash=env['previousHash'].decode('hex'),
        number=int(env['currentNumber']),
        coinbase=env['currentCoinbase'],
        difficulty=int(env['currentDifficulty']),
        gas_limit=int(env['currentGasLimit']),
        timestamp=env['currentTimestamp'])

    # code FIXME WHAT TO DO WITH THIS CODE???
    # if isinstance(env['code'], str):
    #     continue
    # else:
    #     addr = 0 # FIXME
    #     blk.set_code(addr, ''.join(map(chr, env['code'])))

    # setup state
    for address, h in pre.items():
        check_testdata(h.keys(), ['code', 'nonce', 'balance', 'storage'])
        blk.set_balance(address, h['balance'])
        logger.debug('PRE Balance: %r: %r', address, h['balance'])
        blk._set_acct_item(address, 'nonce', h['nonce'])
        blk.set_code(address, h['code'][2:].decode('hex'))

    # execute transactions
    pb.enable_debug()
    sender = exek['caller']  # a party that originates a call
    recvaddr = exek['address']
    tx = transactions.Transaction(
        nonce=blk._get_acct_item(exek['caller'], 'nonce'),
        gasprice=int(exek['gasPrice']),
        startgas=int(exek['gas']),
        to=recvaddr,
        value=int(exek['value']),
        data=exek['data'])
    tx.sender = sender
    logger.debug('TX %r > %r v:%r gas:%s @price:%s',
                 sender, recvaddr, tx.value, tx.startgas, tx.gasprice)

    # capture apply_message calls
    apply_message_calls = []
    orig_apply_msg = pb.apply_msg

    def apply_msg_wrapper(_block, _tx, msg, code):
        pb.enable_debug()
        apply_message_calls.append(dict(gasLimit=msg.gas, value=msg.value,
                                        destination=msg.to,
                                        data='0x'+msg.data.encode('hex')))
        result, gas_rem, data = orig_apply_msg(_block, _tx, msg, code)
        pb.disable_debug()
        return result, gas_rem, data

    pb.apply_msg = apply_msg_wrapper

    msg = pb.Message(tx.sender, tx.to, tx.value, tx.startgas, tx.data)
    blk.delta_balance(exek['caller'], tx.value)
    success, gas_remained, output = \
        pb.apply_msg(blk, tx, msg, exek['code'][2:].decode('hex'))
    blk.delta_balance(exek['address'], -tx.value)
    pb.apply_msg = orig_apply_msg
    apply_message_calls.pop(0)

    assert success
    assert len(callcreates) == len(apply_message_calls)

    # check against callcreates
    for i, callcreate in enumerate(callcreates):
        amc = apply_message_calls[i]
        assert callcreate['data'] == amc['data']
        assert callcreate['gasLimit'] == amc['gasLimit']
        assert callcreate['value'] == amc['value']
        assert callcreate['destination'] == amc['destination']

    # data and out not set in tests yet
    assert output == params['out']
    assert not params['out']
    assert gas_remained == params['gas']

    # check state
    for address, data in post.items():
        assert data['code'][2:].decode('hex') == blk.get_code(address)
        assert data['balance'] == blk.get_balance(address)
        assert data['nonce'] == blk.get_nonce(address)
        assert data['storage'] == blk.get_storage(address).to_dict()
