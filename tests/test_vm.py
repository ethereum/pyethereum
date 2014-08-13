import pytest
import json
import pyethereum.processblock as pb
import pyethereum.blocks as blocks
import pyethereum.transactions as transactions
import pyethereum.utils as u

import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()


def check_testdata(data_keys, expected_keys):
    assert set(data_keys) == set(expected_keys), \
        "test data changed, please adjust tests"


@pytest.fixture(scope="module")
def vm_tests_fixtures():
    """Read vm tests from fixtures"""
    # FIXME: assert that repo is uptodate
    # cd fixtures; git pull origin develop; cd ..;  git commit fixtures
    try:
        vm_fixture = json.load(open('fixtures/vmtests.json', 'r'))
    except IOError:
        raise IOError("Could not read vmtests.json from fixtures",
            "Make sure you did 'git submodule init'")
    try:
        vm_fixture.update(json.load(open('fixtures/random.json', 'r')))
    except IOError:
        raise IOError("Could not read random.json from fixtures.")
    #assert vm_fixture.keys() == ['boolean', 'suicide', 'random', 'arith', 'mktx'],\
    #    "Tests changed, try updating the fixtures submodule"

    return vm_fixture

def test_random():
    do_test_vm('random')

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
        timestamp=int(env['currentTimestamp']))

    # code FIXME WHAT TO DO WITH THIS CODE???
    # if isinstance(env['code'], str):
    #     continue
    # else:
    #     addr = 0 # FIXME
    #     blk.set_code(addr, ''.join(map(chr, env['code'])))

    # setup state
    for address, h in pre.items():
        check_testdata(h.keys(), ['code', 'nonce', 'balance', 'storage'])
        blk.set_nonce(address, int(h['nonce']))
        blk.set_balance(address, int(h['balance']))
        blk.set_code(address, h['code'][2:].decode('hex'))
        for k, v in h['storage']:
            blk.set_storage_data(address,
                                 u.big_endian_to_int(k.decode('hex')),
                                 u.big_endian_to_int(v.decode('hex')))
        logger.debug('PRE Balance: %r: %r', address, h['balance'])

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
        data=exek['data'][2:].decode('hex'))
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
                                        data=msg.data.encode('hex')))
        result, gas_rem, data = orig_apply_msg(_block, _tx, msg, code)
        pb.disable_debug()
        return result, gas_rem, data

    pb.apply_msg = apply_msg_wrapper

    msg = pb.Message(tx.sender, tx.to, tx.value, tx.startgas, tx.data)
    blk.delta_balance(exek['caller'], tx.value)
    blk.delta_balance(exek['address'], -tx.value)
    success, gas_remained, output = \
        pb.apply_msg(blk, tx, msg, exek['code'][2:].decode('hex'))
    pb.apply_msg = orig_apply_msg
    apply_message_calls.pop(0)
    blk.commit_state()

    assert success
    assert len(callcreates) == len(apply_message_calls)

    # check against callcreates
    for i, callcreate in enumerate(callcreates):
        amc = apply_message_calls[i]
        assert callcreate['data'] == '0x'+amc['data'].encode('hex')
        assert callcreate['gasLimit'] == str(amc['gasLimit'])
        assert callcreate['value'] == str(amc['value'])
        assert callcreate['destination'] == amc['destination']

    assert '0x'+''.join(map(chr, output)).encode('hex') == params['out']
    assert str(gas_remained) == params['gas']

    # check state
    for address, data in post.items():
        state = blk.account_to_dict(address)
        state.pop('storage_root', None)  # attribute not present in vmtest fixtures
        assert data == state
