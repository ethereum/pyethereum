import pytest
import json
import pyethereum.processblock as pb
import pyethereum.blocks as blocks
import pyethereum.transactions as transactions
import pyethereum.utils as u
import os
import sys

import logging
logging.basicConfig(level=logging.DEBUG, format='%(message)s')
logger = logging.getLogger()
pblogger = pb.pblogger

# customize VM log output to your needs
# hint: use 'py.test' with the '-s' option to dump logs to the console
pblogger.log_pre_state = True    # dump storage at account before execution
pblogger.log_post_state = True   # dump storage at account after execution
pblogger.log_block = False       # dump block after TX was applied
pblogger.log_memory = True      # dump memory before each op
pblogger.log_op = True           # log op, gas, stack before each op
pblogger.log_json = False        # generate machine readable output
pblogger.log_apply_op = True     # generate machine readable output
pblogger.log_stack = True        # generate machine readable output


def check_testdata(data_keys, expected_keys):
    assert set(data_keys) == set(expected_keys), \
        "test data changed, please adjust tests"


@pytest.fixture(scope="module")
def vm_tests_fixtures():
    """
    Read vm tests from fixtures
    fixtures/VMTests/*
    """
    # FIXME: assert that repo is uptodate
    # cd fixtures; git pull origin develop; cd ..;  git commit fixtures
    filenames = os.listdir(os.path.join('fixtures', 'StateTests'))
    files = [os.path.join('fixtures', 'StateTests', f) for f in filenames]
    vm_fixtures = {}
    try:
        for f, fn in zip(files, filenames):
            if f[-5:] == '.json':
                vm_fixtures[fn[:-5]] = json.load(open(f, 'r'))
    except IOError, e:
        raise IOError("Could not read vmtests.json from fixtures",
                      "Make sure you did 'git submodule init'")
    return vm_fixtures


# SETUP TESTS IN GLOBAL NAME SPACE
def gen_func(filename, testname):
    return lambda: do_test_vm(filename, testname)

for filename, tests in vm_tests_fixtures().items():
    for testname, testdata in tests.items():
        func_name = 'test_%s_%s' % (filename, testname)
        func = gen_func(filename, testname)
        globals()[func_name] = func

faulty = [
    # Put a list of strings of known faulty tests here
]


def do_test_vm(filename, testname=None, limit=99999999):
    if testname is None:
        for testname in vm_tests_fixtures()[filename].keys()[:limit]:
            do_test_vm(filename, testname)
        return
    if testname in faulty:
        logger.debug('skipping test:%r in %r', testname, filename)
        return
    logger.debug('running test:%r in %r', testname, filename)
    params = vm_tests_fixtures()[filename][testname]

    pre = params['pre']
    exek = params['transaction']
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
    # addr = 0 # FIXME
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
        pblogger.log('PRE Balance', address=address, balance=h['balance'])

    # execute transactions
    tx = transactions.Transaction(
        nonce=int(exek['nonce']),
        gasprice=int(exek['gasPrice']),
        startgas=int(exek['gasLimit']),
        to=exek['to'],
        value=int(exek['value']),
        data=exek['data'][2:].decode('hex')).sign(exek['secretKey'])
    pblogger.log_apply_op = True
    pblogger.log_op = True

    try:
        success, output = pb.apply_transaction(blk, tx)
        blk.commit_state()
    except:
        output = ''
        print 'Transaction not valid'
        pass

    assert '0x' + output.encode('hex') == params['out']

    # check state
    for address, data in post.items():
        state = blk.account_to_dict(address, for_vmtest=True)
        state.pop('storage_root', None)
        assert state == data
