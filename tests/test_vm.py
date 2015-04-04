import pytest
import json
import pyethereum.processblock as pb
import pyethereum.vm as vm
import pyethereum.blocks as blocks
import pyethereum.transactions as transactions
import pyethereum.utils as u
import pyethereum.bloom as bloom
import rlp
import os
import sys
from tests.utils import new_db

from pyethereum.slogging import get_logger, configure_logging
logger = get_logger()
# customize VM log output to your needs
# hint: use 'py.test' with the '-s' option to dump logs to the console
configure_logging(':trace')

MAX_TESTS_PER_FILE = 200


def check_testdata(data_keys, expected_keys):
    assert set(data_keys) == set(expected_keys), \
        "test data changed, please adjust tests"

vm_fixture_cache = {}


@pytest.fixture(scope="module")
def vm_tests_fixtures():
    """
    Read vm tests from fixtures
    fixtures/VMTests/*
    """
    if len(vm_fixture_cache):
        return vm_fixture_cache
    # FIXME: assert that repo is uptodate
    # cd fixtures; git pull origin develop; cd ..;  git commit fixtures

    # Recursively traverse directories to get list of files
    dirs = [os.path.join('fixtures', 'VMTests')]
    files = []
    i = 0
    while i < len(dirs):
        children = [os.path.join(dirs[i], f) for f in os.listdir(dirs[i])]
        for f in children:
            if os.path.isdir(f):
                dirs.append(f)
            else:
                files.append(f)
        i += 1
    try:
        for f in files:
            fn = os.path.split(f)[1]
            if f[-5:] == '.json':
                vm_fixture_cache[fn[:-5]] = json.load(open(f, 'r'))
    except IOError:
        raise IOError("Could not read vmtests.json from fixtures",
                      "Make sure you did 'git submodule init'")
    return vm_fixture_cache


# SETUP TESTS IN GLOBAL NAME SPACE
def gen_func(filename, testname):
    return lambda: do_test_vm(filename, testname)

for filename, tests in vm_tests_fixtures().items():
    for testname, testdata in tests.items()[:MAX_TESTS_PER_FILE]:
        func_name = 'test_%s_%s' % (filename.replace(os.path.sep, '_'), testname)
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
        logger.debug('skipping test:%r in %r' % (testname, filename))
        return
    logger.debug('running test:%r in %r' % (testname, filename))
    params = vm_tests_fixtures()[filename][testname]
    run_test_vm(params)

db = new_db()


def run_test_vm(params):
    print params
    pre = params['pre']
    exek = params['exec']
    callcreates = params.get('callcreates', [])
    env = params['env']
    post = params.get('post', {})

    check_testdata(env.keys(), ['currentGasLimit', 'currentTimestamp',
                                'previousHash', 'currentCoinbase',
                                'currentDifficulty', 'currentNumber'])
    # setup env
    blk = blocks.Block(db,
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
        for k, v in h['storage'].iteritems():
            blk.set_storage_data(address,
                                 u.big_endian_to_int(k[2:].decode('hex')),
                                 u.big_endian_to_int(v[2:].decode('hex')))

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

    ext = pb.VMExt(blk, tx)

    def call_wrapper(msg):
        ext.set_balance(msg.sender, ext.get_balance(msg.sender) - msg.value)
        hexdata = msg.data.extract_all().encode('hex')
        apply_message_calls.append(dict(gasLimit=msg.gas, value=msg.value,
                                        destination=msg.to, data=hexdata))
        return 1, msg.gas, ''

    def sendmsg_wrapper(msg, code):
        ext.set_balance(msg.sender, ext.get_balance(msg.sender) - msg.value)
        hexdata = msg.data.extract_all().encode('hex')
        apply_message_calls.append(dict(gasLimit=msg.gas, value=msg.value,
                                        destination=msg.to, data=hexdata))
        return 1, msg.gas, ''

    def create_wrapper(msg):
        ext.set_balance(msg.sender, ext.get_balance(msg.sender) - msg.value)
        sender = msg.sender.decode('hex') if len(msg.sender) == 40 else msg.sender
        nonce = u.encode_int(ext._block.get_nonce(msg.sender))
        addr = u.sha3(rlp.encode([sender, nonce]))[12:].encode('hex')
        hexdata = msg.data.extract_all().encode('hex')
        apply_message_calls.append(dict(gasLimit=msg.gas, value=msg.value,
                                        destination='', data=hexdata))
        return 1, msg.gas, addr

    ext.sendmsg = sendmsg_wrapper
    ext.call = call_wrapper
    ext.create = create_wrapper

    def blkhash(n):
        if n >= ext.block_number or n < ext.block_number - 256:
            return ''
        else:
            return u.sha3(str(n))

    ext.block_hash = blkhash

    msg = vm.Message(tx.sender, tx.to, tx.value, tx.startgas,
                     vm.CallData([ord(x) for x in tx.data]))
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
        assert 'gas' not in params
        assert 'post' not in params
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
                "data": '0x' + log.data.encode('hex'),
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
    if len(sys.argv) < 2:
        for filename, tests in vm_tests_fixtures().items():
            print 'f', filename
            for testname, testdata in tests.items():
                print 't', filename, testname
                do_test_vm(filename, testname)
                print 0
    else:
        if os.path.isfile(sys.argv[1]):
            data = open(sys.argv[1]).read()
        else:
            data = sys.argv[1]
        data = json.loads(data)
        for test_data in data.values():
            try:
                run_test_vm(test_data)
                print 0,
            except Exception:
                print 1,
                sys.exit(1)

if __name__ == '__main__':
    random()
