import pytest

from ethereum import tester as t
from ethereum import blocks, utils, transactions, vm, abi, opcodes
from ethereum.exceptions import InvalidTransaction
import rlp
from rlp.utils import decode_hex, encode_hex, ascii_chr, str_to_bytes
from ethereum import processblock as pb
import copy
from ethereum.db import EphemDB
from ethereum.utils import to_string, safe_ord, parse_int_or_hex
from ethereum.utils import remove_0x_head, int_to_hex, normalize_address
from ethereum.config import Env
import json
import os
import time
from ethereum import ethash
from ethereum import ethash_utils

db = EphemDB()
db_env = Env(db)

env = {
    "currentCoinbase": b"2adc25665018aa1fe0e6bc666dac8fc2697ff9ba",
    "currentDifficulty": "256",
    "currentGasLimit": "1000000000",
    "currentNumber": "257",
    "currentTimestamp": "1",
    "previousHash": b"5e20a0453cecd065ea59c37ac63e079ee08998b6045136a8ce6635c7912ec0b6"
}

# from ethereum.slogging import LogRecorder, configure_logging, set_level
# config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace,eth.pb.msg:trace'
# configure_logging(config_string=config_string)

FILL = 1
VERIFY = 2
TIME = 3
VM = 4
STATE = 5
fill_vm_test = lambda params: run_vm_test(params, FILL)
check_vm_test = lambda params: run_vm_test(params, VERIFY)
time_vm_test = lambda params: run_vm_test(params, TIME)
fill_state_test = lambda params: run_state_test(params, FILL)
check_state_test = lambda params: run_state_test(params, VERIFY)
time_state_test = lambda params: run_state_test(params, TIME)
fill_ethash_test = lambda params: run_ethash_test(params, FILL)
check_ethash_test = lambda params: run_ethash_test(params, VERIFY)
time_ethash_test = lambda params: run_ethash_test(params, TIME)
fill_abi_test = lambda params: run_abi_test(params, FILL)
check_abi_test = lambda params: run_abi_test(params, VERIFY)
time_abi_test = lambda params: run_abi_test(params, TIME)
fill_genesis_test = lambda params: run_genesis_test(params, FILL)
check_genesis_test = lambda params: run_genesis_test(params, VERIFY)
time_genesis_test = lambda params: run_genesis_test(params, TIME)

fixture_path = os.path.join(os.path.dirname(__file__), '..', 'fixtures')


def normalize_hex(s):
    return s if len(s) > 2 else b'0x00'


def acct_standard_form(a):
    return {
        "balance": parse_int_or_hex(a["balance"]),
        "nonce": parse_int_or_hex(a["nonce"]),
        "code": to_string(a["code"]),
        "storage": {normalize_hex(k): normalize_hex(v) for
                    k, v in a["storage"].items() if normalize_hex(v).rstrip(b'0') != b'0x'}
    }


def compare_post_states(shouldbe, reallyis):
    if shouldbe is None and reallyis is None:
        return True
    if shouldbe is None or reallyis is None:
        raise Exception("Shouldbe: %r \n\nreallyis: %r" % (shouldbe, reallyis))
    for k in shouldbe:
        if k not in reallyis:
            r = {"nonce": 0, "balance": 0, "code": b"0x", "storage": {}}
        else:
            r = acct_standard_form(reallyis[k])
        s = acct_standard_form(shouldbe[k])
        if s != r:
            raise Exception("Key %r\n\nshouldbe: %r \n\nreallyis: %r" %
                            (k, s, r))
    return True


def callcreate_standard_form(c):
    return {
        "gasLimit": parse_int_or_hex(c["gasLimit"]),
        "value": parse_int_or_hex(c["value"]),
        "data": to_string(c["data"])
    }


def mktest(code, language, data=None, fun=None, args=None,
           gas=1000000, value=0, test_type=VM):
    s = t.state(1)
    if language == 'evm':
        ca = s.contract('x = 5')
        s.block.set_code(ca, code)
        d = data or b''
    else:
        c = s.abi_contract(code, language=language)
        d = c._translator.encode(fun, args) if fun else (data or b'')
        ca = c.address
    pre = s.block.to_dict(True)['state']
    if test_type == VM:
        exek = {"address": ca, "caller": t.a0,
                "code": b'0x' + encode_hex(s.block.get_code(ca)),
                "data": b'0x' + encode_hex(d), "gas": to_string(gas),
                "gasPrice": to_string(1), "origin": t.a0,
                "value": to_string(value)}
        return fill_vm_test({"env": env, "pre": pre, "exec": exek})
    else:
        tx = {"data": b'0x' + encode_hex(d), "gasLimit": parse_int_or_hex(gas),
              "gasPrice": to_string(1), "nonce": to_string(s.block.get_nonce(t.a0)),
              "secretKey": encode_hex(t.k0), "to": ca, "value": to_string(value)}
        return fill_state_test({"env": env, "pre": pre, "transaction": tx})


# Fills up a vm test without post data, or runs the test
def run_vm_test(params, mode, profiler=None):
    pre = params['pre']
    exek = params['exec']
    env = params['env']
    if 'previousHash' not in env:
        env['previousHash'] = encode_hex(db_env.config['GENESIS_PREVHASH'])

    assert set(env.keys()) == set(['currentGasLimit', 'currentTimestamp',
                                   'previousHash', 'currentCoinbase',
                                   'currentDifficulty', 'currentNumber'])
    # setup env
    header = blocks.BlockHeader(
        prevhash=decode_hex(env['previousHash']),
        number=parse_int_or_hex(env['currentNumber']),
        coinbase=decode_hex(env['currentCoinbase']),
        difficulty=parse_int_or_hex(env['currentDifficulty']),
        gas_limit=parse_int_or_hex(env['currentGasLimit']),
        timestamp=parse_int_or_hex(env['currentTimestamp']))

    blk = blocks.Block(header, env=db_env)

    # setup state
    for address, h in list(pre.items()):
        assert len(address) == 40
        address = decode_hex(address)
        assert set(h.keys()) == set(['code', 'nonce', 'balance', 'storage'])
        blk.set_nonce(address, parse_int_or_hex(h['nonce']))
        blk.set_balance(address, parse_int_or_hex(h['balance']))
        blk.set_code(address, decode_hex(h['code'][2:]))
        for k, v in h['storage'].items():
            blk.set_storage_data(address,
                                 utils.big_endian_to_int(decode_hex(k[2:])),
                                 utils.big_endian_to_int(decode_hex(v[2:])))

    # execute transactions
    sender = decode_hex(exek['caller'])  # a party that originates a call
    recvaddr = decode_hex(exek['address'])
    nonce = blk._get_acct_item(sender, 'nonce')
    gasprice = parse_int_or_hex(exek['gasPrice'])
    startgas = parse_int_or_hex(exek['gas'])
    value = parse_int_or_hex(exek['value'])
    data = decode_hex(exek['data'][2:])

    # bypass gas check in tx initialization by temporarily increasing startgas
    num_zero_bytes = str_to_bytes(data).count(ascii_chr(0))
    num_non_zero_bytes = len(data) - num_zero_bytes
    intrinsic_gas = (opcodes.GTXCOST + opcodes.GTXDATAZERO * num_zero_bytes +
                     opcodes.GTXDATANONZERO * num_non_zero_bytes)
    startgas += intrinsic_gas
    tx = transactions.Transaction(nonce=nonce, gasprice=gasprice, startgas=startgas,
                                  to=recvaddr, value=value, data=data)
    tx.startgas -= intrinsic_gas
    tx.sender = sender

    # capture apply_message calls
    apply_message_calls = []
    orig_apply_msg = pb.apply_msg

    ext = pb.VMExt(blk, tx)

    def msg_wrapper(msg):
        hexdata = encode_hex(msg.data.extract_all())
        apply_message_calls.append(dict(gasLimit=to_string(msg.gas),
                                        value=to_string(msg.value),
                                        destination=encode_hex(msg.to),
                                        data=b'0x' + hexdata))
        return 1, msg.gas, b''

    def create_wrapper(msg):
        sender = decode_hex(msg.sender) if \
            len(msg.sender) == 40 else msg.sender
        nonce = utils.encode_int(ext._block.get_nonce(msg.sender))
        addr = utils.sha3(rlp.encode([sender, nonce]))[12:]
        hexdata = encode_hex(msg.data.extract_all())
        apply_message_calls.append(dict(gasLimit=to_string(msg.gas),
                                        value=to_string(msg.value),
                                        destination=b'', data=b'0x' + hexdata))
        return 1, msg.gas, addr

    ext.msg = msg_wrapper
    ext.create = create_wrapper

    def blkhash(n):
        if n >= ext.block_number or n < ext.block_number - 256:
            return b''
        else:
            return utils.sha3(to_string(n))

    ext.block_hash = blkhash

    msg = vm.Message(tx.sender, tx.to, tx.value, tx.startgas,
                     vm.CallData([safe_ord(x) for x in tx.data]))
    code = decode_hex(exek['code'][2:])
    time_pre = time.time()
    if profiler:
        profiler.enable()
    success, gas_remained, output = vm.vm_execute(ext, msg, code)
    if profiler:
        profiler.disable()
    pb.apply_msg = orig_apply_msg
    blk.commit_state()
    for s in blk.suicides:
        blk.del_account(s)
    time_post = time.time()

    """
     generally expected that the test implementer will read env, exec and pre
     then check their results against gas, logs, out, post and callcreates.
     If an exception is expected, then latter sections are absent in the test.
     Since the reverting of the state is not part of the VM tests.
     """

    params2 = copy.deepcopy(params)

    if success:
        params2['callcreates'] = apply_message_calls
        params2['out'] = b'0x' + encode_hex(b''.join(map(ascii_chr, output)))
        params2['gas'] = to_string(gas_remained)
        params2['logs'] = [log.to_dict() for log in blk.logs]
        params2['post'] = blk.to_dict(with_state=True)['state']

    if mode == FILL:
        return params2
    elif mode == VERIFY:
        if not success:
            assert 'post' not in params, 'failed, but expected to succeed'

        params1 = copy.deepcopy(params)
        shouldbe, reallyis = params1.get('post', None), params2.get('post', None)
        compare_post_states(shouldbe, reallyis)

        def normalize_value(k, p):
            if k in p:
                if k == 'gas':
                    return parse_int_or_hex(p[k])
                elif k == 'callcreates':
                    return list(map(callcreate_standard_form, p[k]))
                else:
                    return utils.to_string(k)
            return None

        for k in ['pre', 'exec', 'env', 'callcreates',
                  'out', 'gas', 'logs']:
            shouldbe = normalize_value(k, params1)
            reallyis = normalize_value(k, params2)
            if shouldbe != reallyis:
                raise Exception("Mismatch: " + k + ':\n shouldbe %r\n reallyis %r' %
                                (shouldbe, reallyis))
    elif mode == TIME:
        return time_post - time_pre


# Fills up a vm test without post data, or runs the test
def run_state_test(params, mode):
    pre = params['pre']
    exek = params['transaction']
    env = params['env']

    assert set(env.keys()) == set(['currentGasLimit', 'currentTimestamp',
                                   'previousHash', 'currentCoinbase',
                                   'currentDifficulty', 'currentNumber'])
    assert len(env['currentCoinbase']) == 40

    # setup env
    header = blocks.BlockHeader(
        prevhash=decode_hex(env['previousHash']),
        number=parse_int_or_hex(env['currentNumber']),
        coinbase=decode_hex(env['currentCoinbase']),
        difficulty=parse_int_or_hex(env['currentDifficulty']),
        timestamp=parse_int_or_hex(env['currentTimestamp']),
        # work around https://github.com/ethereum/pyethereum/issues/390 [1]:
        gas_limit=min(db_env.config['MAX_GAS_LIMIT'], parse_int_or_hex(env['currentGasLimit'])))
    blk = blocks.Block(header, env=db_env)

    # work around https://github.com/ethereum/pyethereum/issues/390 [2]:
    blk.gas_limit = parse_int_or_hex(env['currentGasLimit'])

    # setup state
    for address, h in list(pre.items()):
        assert len(address) == 40
        address = decode_hex(address)
        assert set(h.keys()) == set(['code', 'nonce', 'balance', 'storage'])
        blk.set_nonce(address, parse_int_or_hex(h['nonce']))
        blk.set_balance(address, parse_int_or_hex(h['balance']))
        blk.set_code(address, decode_hex(h['code'][2:]))
        for k, v in h['storage'].items():
            blk.set_storage_data(address,
                                 utils.big_endian_to_int(decode_hex(k[2:])),
                                 utils.big_endian_to_int(decode_hex(v[2:])))

    for address, h in list(pre.items()):
        address = decode_hex(address)
        assert blk.get_nonce(address) == parse_int_or_hex(h['nonce'])
        assert blk.get_balance(address) == parse_int_or_hex(h['balance'])
        assert blk.get_code(address) == decode_hex(h['code'][2:])
        for k, v in h['storage'].items():
            assert blk.get_storage_data(address, utils.big_endian_to_int(
                decode_hex(k[2:]))) == utils.big_endian_to_int(decode_hex(v[2:]))

    # execute transactions
    orig_apply_msg = pb.apply_msg

    def apply_msg_wrapper(ext, msg):

        def blkhash(n):
            if n >= blk.number or n < blk.number - 256:
                return b''
            else:
                return utils.sha3(to_string(n))

        ext.block_hash = blkhash
        return orig_apply_msg(ext, msg)

    pb.apply_msg = apply_msg_wrapper

    try:
        tx = transactions.Transaction(
            nonce=parse_int_or_hex(exek['nonce'] or b"0"),
            gasprice=parse_int_or_hex(exek['gasPrice'] or b"0"),
            startgas=parse_int_or_hex(exek['gasLimit'] or b"0"),
            to=normalize_address(exek['to'], allow_blank=True),
            value=parse_int_or_hex(exek['value'] or b"0"),
            data=decode_hex(remove_0x_head(exek['data'])))
    except InvalidTransaction:
        tx = None
        success, output = False, b''
        time_pre = time.time()
        time_post = time_pre
    else:
        if 'secretKey' in exek:
            tx.sign(exek['secretKey'])
        elif all(key in exek for key in ['v', 'r', 's']):
            tx.v = decode_hex(remove_0x_head(exek['v']))
            tx.r = decode_hex(remove_0x_head(exek['r']))
            tx.s = decode_hex(remove_0x_head(exek['s']))
        else:
            assert False

        time_pre = time.time()
        try:
            print('trying')
            success, output = pb.apply_transaction(blk, tx)
            blk.commit_state()
            print('success', blk.get_receipts()[-1].gas_used)
        except InvalidTransaction:
            success, output = False, b''
            blk.commit_state()
            pass
        time_post = time.time()

        if tx.to == b'':
            output = blk.get_code(output)

    pb.apply_msg = orig_apply_msg

    params2 = copy.deepcopy(params)
    if success:
        params2['logs'] = [log.to_dict() for log in blk.get_receipt(0).logs]

    params2['out'] = b'0x' + encode_hex(output)
    params2['post'] = copy.deepcopy(blk.to_dict(True)['state'])
    params2['postStateRoot'] = encode_hex(blk.state.root_hash)

    if mode == FILL:
        return params2
    elif mode == VERIFY:
        params1 = copy.deepcopy(params)
        shouldbe, reallyis = params1.get('post', None), params2.get('post', None)
        compare_post_states(shouldbe, reallyis)
        for k in ['pre', 'exec', 'env', 'callcreates',
                  'out', 'gas', 'logs', 'postStateRoot']:
            _shouldbe = params1.get(k, None)
            _reallyis = params2.get(k, None)
            if _shouldbe != _reallyis:
                print(('Mismatch {key}: shouldbe {shouldbe_key} != reallyis {reallyis_key}.\n'
                       'post: {shouldbe_post} != {reallyis_post}').format(
                    shouldbe_key=_shouldbe, reallyis_key=_reallyis,
                    shouldbe_post=shouldbe, reallyis_post=reallyis, key=k))
                raise Exception("Mismatch: " + k + ':\n shouldbe %r\n reallyis %r' %
                                (_shouldbe, _reallyis))

    elif mode == TIME:
        return time_post - time_pre


def run_ethash_test(params, mode):
    if 'header' not in params:
        b = blocks.genesis(db)
        b.nonce = decode_hex(params['nonce'])
        b.number = params.get('number', 0)
        header = b.header
        params['header'] = encode_hex(rlp.encode(b.header))
    else:
        header = blocks.BlockHeader(decode_hex(params['header']))
    header_hash = header.mining_hash
    cache_size = ethash.get_cache_size(header.number)
    full_size = ethash.get_full_size(header.number)
    seed = b'\x00' * 32
    for i in range(header.number // ethash_utils.EPOCH_LENGTH):
        seed = utils.sha3(seed)
    nonce = header.nonce
    assert len(nonce) == 8
    assert len(seed) == 32
    t1 = time.time()
    cache = ethash.mkcache(cache_size, seed)
    t2 = time.time()
    cache_hash = encode_hex(utils.sha3(ethash.serialize_cache(cache)))
    t6 = time.time()
    light_verify = ethash.hashimoto_light(full_size, cache, header_hash, nonce)
    t7 = time.time()
    # assert full_mine == light_mine
    out = {
        "seed": encode_hex(seed),
        "header_hash": encode_hex(header_hash),
        "nonce": encode_hex(nonce),
        "cache_size": cache_size,
        "full_size": full_size,
        "cache_hash": cache_hash,
        "mixhash": encode_hex(light_verify["mix digest"]),
        "result": encode_hex(light_verify["result"]),
    }
    if mode == FILL:
        header.mixhash = light_verify["mixhash"]
        params["header"] = encode_hex(rlp.encode(header))
        for k, v in list(out.items()):
            params[k] = v
        return params
    elif mode == VERIFY:
        should, actual = header.mixhash, light_verify['mixhash']
        assert should == actual, "Mismatch: mixhash %r %r" % (should, actual)
        for k, v in list(out.items()):
            assert params[k] == v, "Mismatch: " + k + ' %r %r' % (params[k], v)
    elif mode == TIME:
        return {
            "cache_gen": t2 - t1,
            "verification_time": t7 - t6
        }


def run_abi_test(params, mode):
    types, args = params['types'], params['args']
    out = abi.encode_abi(types, args)
    assert abi.decode_abi(types, out) == args
    if mode == FILL:
        params['result'] = encode_hex(out)
        return params
    elif mode == VERIFY:
        assert params['result'] == encode_hex(out)
    elif mode == TIME:
        x = time.time()
        abi.encode_abi(types, args)
        y = time.time()
        abi.decode_abi(out, args)
        return {
            'encoding': y - x,
            'decoding': time.time() - y
        }


def run_genesis_test(params, mode):
    params = copy.deepcopy(params)
    if 'difficulty' not in params:
        params['difficulty'] = int_to_hex(2 ** 34)
    if 'mixhash' not in params:
        params['mixhash'] = '0x' + '0' * 64
    if 'nonce' not in params:
        params['nonce'] = '0x0000000000000042'
    if 'timestamp' not in params:
        params['timestamp'] = int_to_hex(5000)
    if 'parentHash' not in params:
        params['parentHash'] = '0x' + '0' * 64
    if 'gasLimit' not in params:
        params['gasLimit'] = int_to_hex(5000)
    if 'extraData' not in params:
        params['extraData'] = '0x'
    if 'coinbase' not in params:
        params['coinbase'] = '0x' + '3' * 40
    x = time.time()
    b = blocks.genesis(EphemDB(), start_alloc=params['alloc'],
                       difficulty=parse_int_or_hex(params['difficulty']),
                       timestamp=parse_int_or_hex(params['timestamp']),
                       extra_data=decode_hex(remove_0x_head(params['extraData'])),
                       gas_limit=parse_int_or_hex(params['gasLimit']),
                       mixhash=decode_hex(remove_0x_head(params['mixhash'])),
                       prevhash=decode_hex(remove_0x_head(params['parentHash'])),
                       coinbase=decode_hex(remove_0x_head(params['coinbase'])),
                       nonce=decode_hex(remove_0x_head(params['nonce'])))
    assert b.difficulty == parse_int_or_hex(params['difficulty'])
    assert b.timestamp == parse_int_or_hex(params['timestamp'])
    assert b.extra_data == decode_hex(remove_0x_head(params['extraData']))
    assert b.gas_limit == parse_int_or_hex(params['gasLimit'])
    assert b.mixhash == decode_hex(remove_0x_head(params['mixhash']))
    assert b.prevhash == decode_hex(remove_0x_head(params['parentHash']))
    assert b.nonce == decode_hex(remove_0x_head(params['nonce']))
    print(9)
    if mode == FILL:
        params['result'] = encode_hex(rlp.encode(b))
        return params
    elif mode == VERIFY:
        assert params['result'] == encode_hex(rlp.encode(b))
    elif mode == TIME:
        return {
            'creation': time.time() - x
        }


def get_tests_from_file_or_dir(dname, json_only=False):
    if os.path.isfile(dname):
        if dname[-5:] == '.json' or not json_only:
            with open(dname) as f:
                return {dname: json.load(f)}
        else:
            return {}
    else:
        o = {}
        for f in os.listdir(dname):
            fullpath = os.path.join(dname, f)
            for k, v in list(get_tests_from_file_or_dir(fullpath, True).items()):
                o[k] = v
        return o


def get_blocks_from_textdump(data):
    if '\n' not in data:
        r = rlp.decode(decode_hex(data))
        if len(r[0]) != 3:
            blocks = [r]
        else:
            blocks = r
    else:
        blocks = [rlp.decode(decode_hex(ln)) for ln in data.split('\n')]
    return blocks


def fixture_to_bytes(value):
    if isinstance(value, str):
        return str_to_bytes(value)
    elif isinstance(value, list):
        return [fixture_to_bytes(v) for v in value]
    elif isinstance(value, dict):
        ret = {}
        for k, v in list(value.items()):
            if isinstance(k, str) and (len(k) == 40 or k[:2] == '0x'):
                key = str_to_bytes(k)
            else:
                key = k
            ret[key] = fixture_to_bytes(v)
        return ret
    else:
        return value


def generate_test_params(testsource, metafunc, skip_func=None, exclude_func=None):
    if ['filename', 'testname', 'testdata'] != metafunc.fixturenames:
        return

    fixtures = get_tests_from_file_or_dir(
        os.path.join(fixture_path, testsource))

    base_dir = os.path.dirname(os.path.dirname(__file__))
    params = []
    for filename, tests in fixtures.items():
        if isinstance(tests, dict):
            filename = os.path.relpath(filename, base_dir)
            for testname, testdata in tests.items():
                if exclude_func and exclude_func(filename, testname, testdata):
                    continue
                if skip_func:
                    skipif = pytest.mark.skipif(
                        skip_func(filename, testname, testdata),
                        reason="Excluded"
                    )
                    params.append(skipif((filename, testname, testdata)))
                else:
                    params.append((filename, testname, testdata))

    metafunc.parametrize(
        ('filename', 'testname', 'testdata'),
        params
    )
    return params
