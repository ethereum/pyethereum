import pytest
import json
import pyethereum.processblock as pb
import pyethereum.vm as vm
import pyethereum.blocks as blocks
import pyethereum.transactions as transactions
import pyethereum.utils as u
import pyethereum.bloom as bloom
import pyethereum.tlogging as tlogging
import os
import sys
from tests.utils import new_db

from pyethereum.slogging import get_logger, configure_logging
logger = get_logger()
# customize VM log output to your needs
# hint: use 'py.test' with the '-s' option to dump logs to the console
configure_logging(':trace')

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
    filenames = os.listdir(os.path.join('fixtures', 'VMTests'))
    files = [os.path.join('fixtures', 'VMTests', f) for f in filenames]
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
        logger.debug('skipping test:%r in %r' %(testname, filename))
        return
    logger.debug('running test:%r in %r' %(testname, filename))
    params = vm_tests_fixtures()[filename][testname]
    run_test_vm(params)


def run_test_vm(params):
    pre = params['pre']
    exek = params['exec']
    callcreates = params.get('callcreates', [])
    env = params['env']
    post = params.get('post',{})

    check_testdata(env.keys(), ['currentGasLimit', 'currentTimestamp',
                                'previousHash', 'currentCoinbase',
                                'currentDifficulty', 'currentNumber'])
    # setup env
    blk = blocks.Block(new_db(),
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

    # execute transactions
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

    # capture apply_message calls
    apply_message_calls = []
    orig_apply_msg = pb.apply_msg

    def apply_msg_wrapper(_ext, msg, code, toplevel=False):
        apply_message_calls.append(dict(gasLimit=msg.gas, value=msg.value,
                                        destination=msg.to,
                                        data=msg.data.encode('hex')))
        if not toplevel:
            pb.apply_msg = orig_apply_msg
        result, gas_rem, data = orig_apply_msg(_ext, msg, code)
        if not toplevel:
            pb.apply_msg = apply_msg_wrapper
        return result, gas_rem, data

    pb.apply_msg = apply_msg_wrapper

    ext = pb.VMExt(blk, tx)
    msg = vm.Message(tx.sender, tx.to, tx.value, tx.startgas, tx.data)
    success, gas_remained, output = \
        vm.vm_execute(ext, msg, exek['code'][2:].decode('hex'))
    pb.apply_msg = orig_apply_msg
    blk.commit_state()

    """
     generally expected that the test implementer will read env, exec and pre
     then check their results against gas, logs, out, post and callcreates.
     If an exception is expected, then latter sections are absent in the test. 
     Since the reverting of the state is not part of the VM tests.
     """


    if not success:
        return

    for k in ['gas', 'logs', 'out', 'post', 'callcreates']:
        assert k in params
    assert len(callcreates) == len(apply_message_calls)


    # check against callcreates
    for i, callcreate in enumerate(callcreates):
        amc = apply_message_calls[i]
        assert callcreate['data'] == '0x' + amc['data']
        assert callcreate['gasLimit'] == str(amc['gasLimit'])
        assert callcreate['value'] == str(amc['value'])
        assert callcreate['destination'] == amc['destination']

    if 'out' in params:
        assert '0x' + ''.join(map(chr, output)).encode('hex') == params['out']
    if 'gas' in params:
        assert str(gas_remained) == params['gas']
    if 'logs' in params:
        """
        The logs sections is a mapping between the blooms and their corresponding logentries.
        Each logentry has the format:
        address: The address of the logentry.
        data: The data of the logentry.
        topics: The topics of the logentry, given as an array of values.
        """
        test_logs = params['logs']
        vm_logs = []
        for log in tx.logs:
            vm_logs.append({
                "bloom": bloom.b64(bloom.bloom_from_list(log.bloomables())).encode('hex'),
                "address": log.address,
                "data": '0x'+log.data.encode('hex'),
                "topics": [u.zpad(u.int_to_big_endian(t), 32).encode('hex') for t in log.topics]
            })

        assert len(vm_logs) == len(test_logs)
        assert vm_logs == test_logs

    # check state
    for address, data in post.items():
        state = blk.account_to_dict(address, for_vmtest=True)
        state.pop('storage_root', None)  # attribute not present in vmtest fixtures
        assert data == state

def random():
    "used for external random vm tests"
    configure_logging(':critical')
    import sys
    data = json.loads(sys.argv[1])
    for test_data in data.values():
        try:
            run_test_vm(test_data)
        except Exception:
            sys.exit(1)

if __name__ == '__main__':
    random()

