from pyethereum import tester as t
from pyethereum import blocks, utils, transactions, vm
import rlp
from pyethereum import processblock as pb
import tempfile
import copy
from db import DB, EphemDB
import json
import os
import time
import ethash
db = EphemDB()

env = {
    "currentCoinbase": "2adc25665018aa1fe0e6bc666dac8fc2697ff9ba",
    "currentDifficulty": "256",
    "currentGasLimit": "1000000000",
    "currentNumber": "257",
    "currentTimestamp": "1",
    "previousHash": "5e20a0453cecd065ea59c37ac63e079ee08998b6045136a8ce6635c7912ec0b6"
}

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


def parse_int_or_hex(s):
    if s[:2] == '0x':
        return utils.big_endian_to_int(s[2:].decode('hex'))
    else:
        return int(s)


def mktest(code, language, data=None, fun=None, args=None,
           gas=1000000, value=0, test_type=VM):
    s = t.state(1)
    if language == 'evm':
        ca = s.contract('x = 5')
        s.block.set_code(ca, code)
        d = data or ''
    else:
        c = s.abi_contract(code, language=language)
        d = c._translator.encode(fun, args) if fun else (data or '')
        ca = c.address
    pre = s.block.to_dict(True)['state']
    if test_type == VM:
        exek = {"address": ca, "caller": t.a0,
                "code": '0x'+s.block.get_code(ca).encode('hex'),
                "data": '0x'+d.encode('hex'), "gas": str(gas),
                "gasPrice": str(1), "origin": t.a0,
                "value": str(value)}
        return fill_vm_test({"env": env, "pre": pre, "exec": exek})
    else:
        tx = {"data": '0x'+d.encode('hex'), "gasLimit": parse_int_or_hex(gas),
              "gasPrice": str(1), "nonce": str(s.block.get_nonce(t.a0)),
              "secretKey": t.k0.encode('hex'), "to": ca, "value": str(value)}
        return fill_state_test({"env": env, "pre": pre, "transaction": tx})


# Fills up a vm test without post data, or runs the test
def run_vm_test(params, mode):
    pre = params['pre']
    exek = params['exec']
    env = params['env']

    assert set(env.keys()) == set(['currentGasLimit', 'currentTimestamp',
                                   'previousHash', 'currentCoinbase',
                                   'currentDifficulty', 'currentNumber'])
    # setup env
    blk = blocks.Block(db,
                       prevhash=env['previousHash'].decode('hex'),
                       number=int(env['currentNumber']),
                       coinbase=env['currentCoinbase'],
                       difficulty=int(env['currentDifficulty']),
                       gas_limit=parse_int_or_hex(env['currentGasLimit']),
                       timestamp=int(env['currentTimestamp']))

    # setup state
    for address, h in pre.items():
        assert set(h.keys()) == set(['code', 'nonce', 'balance', 'storage'])
        blk.set_nonce(address, int(h['nonce']))
        blk.set_balance(address, int(h['balance']))
        blk.set_code(address, h['code'][2:].decode('hex'))
        for k, v in h['storage'].iteritems():
            blk.set_storage_data(address,
                                 utils.big_endian_to_int(k[2:].decode('hex')),
                                 utils.big_endian_to_int(v[2:].decode('hex')))

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
        apply_message_calls.append(dict(gasLimit=str(msg.gas),
                                        value=str(msg.value),
                                        destination=msg.to, data='0x'+hexdata))
        return 1, msg.gas, ''

    def sendmsg_wrapper(msg, code):
        ext.set_balance(msg.sender, ext.get_balance(msg.sender) - msg.value)
        hexdata = msg.data.extract_all().encode('hex')
        apply_message_calls.append(dict(gasLimit=str(msg.gas),
                                        value=str(msg.value),
                                        destination=msg.to, data='0x'+hexdata))
        return 1, msg.gas, ''

    def create_wrapper(msg):
        ext.set_balance(msg.sender, ext.get_balance(msg.sender) - msg.value)
        sender = msg.sender.decode('hex') if \
            len(msg.sender) == 40 else msg.sender
        nonce = utils.encode_int(ext._block.get_nonce(msg.sender))
        addr = utils.sha3(rlp.encode([sender, nonce]))[12:].encode('hex')
        hexdata = msg.data.extract_all().encode('hex')
        apply_message_calls.append(dict(gasLimit=str(msg.gas),
                                        value=str(msg.value),
                                        destination='', data='0x'+hexdata))
        return 1, msg.gas, addr

    ext.sendmsg = sendmsg_wrapper
    ext.call = call_wrapper
    ext.create = create_wrapper

    def blkhash(n):
        if n >= ext.block_number or n < ext.block_number - 256:
            return ''
        else:
            return utils.sha3(str(n))

    ext.block_hash = blkhash

    msg = vm.Message(tx.sender, tx.to, tx.value, tx.startgas,
                     vm.CallData([ord(x) for x in tx.data]))
    time_pre = time.time()
    success, gas_remained, output = \
        vm.vm_execute(ext, msg, exek['code'][2:].decode('hex'))
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
        params2['out'] = '0x' + ''.join(map(chr, output)).encode('hex')
        params2['gas'] = str(gas_remained)
        params2['logs'] = [log.to_dict() for log in blk.logs]
        params2['post'] = blk.to_dict(True)['state']

    if mode == FILL:
        return params2
    elif mode == VERIFY:
        params1 = copy.deepcopy(params)
        if 'post' in params1:
            for k, v in params1['post'].items():
                if v == {u'code': u'0x', u'nonce': u'0', u'balance': u'0', u'storage': {}}:
                    del params1['post'][k]
        if 'post' in params2:
            for k, v in params2['post'].items():
                if v == {u'code': u'0x', u'nonce': u'0', u'balance': u'0', u'storage': {}}:
                    del params2['post'][k]
        for k in ['pre', 'exec', 'env', 'callcreates',
                  'out', 'gas', 'logs', 'post']:
            assert params1.get(k, None) == params2.get(k, None), \
                k + ': %r %r' % (params1.get(k, None), params2.get(k, None))
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
    # setup env
    blk = blocks.Block(db,
                       prevhash=env['previousHash'].decode('hex'),
                       number=int(env['currentNumber']),
                       coinbase=env['currentCoinbase'],
                       difficulty=int(env['currentDifficulty']),
                       gas_limit=parse_int_or_hex(env['currentGasLimit']),
                       timestamp=int(env['currentTimestamp']))

    # setup state
    for address, h in pre.items():
        assert set(h.keys()) == set(['code', 'nonce', 'balance', 'storage'])
        blk.set_nonce(address, int(h['nonce']))
        blk.set_balance(address, int(h['balance']))
        blk.set_code(address, h['code'][2:].decode('hex'))
        for k, v in h['storage'].iteritems():
            blk.set_storage_data(address,
                                 utils.big_endian_to_int(k[2:].decode('hex')),
                                 utils.big_endian_to_int(v[2:].decode('hex')))

    # execute transactions
    tx = transactions.Transaction(
        nonce=int(exek['nonce'] or "0"),
        gasprice=int(exek['gasPrice'] or "0"),
        startgas=parse_int_or_hex(exek['gasLimit'] or "0"),
        to=exek['to'][2:] if exek['to'][:2] == '0x' else exek['to'],
        value=int(exek['value'] or "0"),
        data=exek['data'][2:].decode('hex')).sign(exek['secretKey'])

    orig_apply_msg = pb.apply_msg

    def apply_msg_wrapper(ext, msg):

        def blkhash(n):
            if n >= blk.number or n < blk.number - 256:
                return ''
            else:
                return utils.sha3(str(n))

        ext.block_hash = blkhash
        return orig_apply_msg(ext, msg)

    pb.apply_msg = apply_msg_wrapper

    time_pre = time.time()
    try:
        success, output = pb.apply_transaction(blk, tx)
        blk.commit_state()
    except pb.InvalidTransaction:
        success, output = False, ''
        blk.commit_state()
        pass
    time_post = time.time()

    if tx.to == '':
        output = blk.get_code(output)

    pb.apply_msg = orig_apply_msg

    params2 = copy.deepcopy(params)
    if success:
        params2['out'] = '0x' + output.encode('hex')
        params2['post'] = copy.deepcopy(blk.to_dict(True)['state'])
        params2['logs'] = [log.to_dict() for log in blk.get_receipt(0).logs]
        params2['postStateRoot'] = blk.state.root_hash.encode('hex')

    if mode == FILL:
        return params2
    elif mode == VERIFY:
        params1 = copy.deepcopy(params)
        if 'post' in params1:
            for k, v in params1['post'].items():
                if v == {u'code': u'0x', u'nonce': u'0', u'balance': u'0', u'storage': {}}:
                    del params1['post'][k]
        if 'post' in params2:
            for k, v in params2['post'].items():
                if v == {u'code': u'0x', u'nonce': u'0', u'balance': u'0', u'storage': {}}:
                    del params2['post'][k]
        for k in ['pre', 'exec', 'env', 'callcreates',
                  'out', 'gas', 'logs', 'post', 'postStateRoot']:
            if params1.get(k, None) != params2.get(k, None):
                shouldbe = params1.get(k, None)
                reallyis = params2.get(k, None)
                raise Exception("Mismatch: " + k + ': %r %r' % (shouldbe, reallyis))

    elif mode == TIME:
        return time_post - time_pre


def run_ethash_test(params, mode):
    if 'header' not in params:
        b = blocks.genesis(db)
        b.seedhash = params['seed'].decode('hex')
        b.nonce = params['nonce'].decode('hex')
        b.number = params.get('number', 0)
        params['header'] = b.serialize_header().encode('hex')
    header = params['header'].decode('hex')
    block = blocks.Block.init_from_header(db, header, transient=True)
    header_hash = utils.sha3(block.serialize_header_without_nonce())
    cache_size = ethash.get_cache_size(block.number)
    full_size = ethash.get_full_size(block.number)
    seed = block.seedhash
    nonce = block.nonce
    assert len(nonce) == 8
    assert len(seed) == 32
    t1 = time.time()
    cache = ethash.mkcache(cache_size, seed)
    t2 = time.time()
    cache_hash = utils.sha3(ethash.serialize_cache(cache)).encode('hex')
    t6 = time.time()
    light_verify = ethash.hashimoto_light(full_size, cache, header_hash, nonce)
    t7 = time.time()
    # assert full_mine == light_mine
    out = {
        "seed": seed.encode('hex'),
        "header_hash": header_hash.encode('hex'),
        "nonce": nonce.encode('hex'),
        "cache_size": cache_size,
        "full_size": full_size,
        "cache_hash": cache_hash,
        "mixhash": light_verify["mixhash"].encode('hex'),
        "result": light_verify["result"].encode('hex'),
    }
    if mode == FILL:
        block.mixhash = light_verify["mixhash"]
        params["header"] = block.serialize_header().encode('hex')
        for k, v in out.items():
            params[k] = v
        return params
    elif mode == VERIFY:
        should, actual = block.mixhash, light_verify['mixhash']
        assert should == actual, "Mismatch: mixhash %r %r" % (should, actual)
        for k, v in out.items():
            assert params[k] == v, "Mismatch: " + k + ' %r %r' % (params[k], v)
    elif mode == TIME:
        return {
            "cache_gen": t2 - t1,
            "verification_time": t7 - t6
        }


def get_tests_from_file_or_dir(dname, json_only=False):
    if os.path.isfile(dname):
        if dname[-5:] == '.json' or not json_only:
            return {dname: json.load(open(dname))}
        else:
            return {}
    else:
        o = {}
        for f in os.listdir(dname):
            fullpath = os.path.join(dname, f)
            for k, v in get_tests_from_file_or_dir(fullpath, True).items():
                o[k] = v
        return o
