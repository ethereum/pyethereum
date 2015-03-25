from pyethereum import tester as t
from pyethereum import blocks, utils, transactions, vm
import rlp
from rlp.utils import decode_hex, encode_hex, ascii_chr, str_to_bytes, bytes_to_str
from pyethereum import processblock as pb
import tempfile
import copy
from pyethereum.db import DB, EphemDB
from pyethereum.utils import to_string, safe_ord, int_to_big_endian, big_endian_to_int
import json
import os
import time
from pyethereum import ethash
from pyethereum import ethash_utils
db = EphemDB()

env = {
    "currentCoinbase": b"2adc25665018aa1fe0e6bc666dac8fc2697ff9ba",
    "currentDifficulty": "256",
    "currentGasLimit": "1000000000",
    "currentNumber": "257",
    "currentTimestamp": "1",
    "previousHash": b"5e20a0453cecd065ea59c37ac63e079ee08998b6045136a8ce6635c7912ec0b6"
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
    if s[:2] == b'0x':
        return utils.big_endian_to_int(decode_hex(s[2:]))
    else:
        return int(s)


def mktest(code, language, data=None, fun=None, args=None,
           gas=1000000, value=0, test_type=VM):
    s = t.state(1)
    if language == 'evm':
        ca = s.contract('x = 5')
        s.block.set_code(ca, code)
        d = data or b''
    else:
        c = s.abi_contract(code, language=language)
        d = c._translator.encode(fun, args) if fun else (data or '')
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
def run_vm_test(params, mode):
    pre = params['pre']
    exek = params['exec']
    env = params['env']

    assert set(env.keys()) == set(['currentGasLimit', 'currentTimestamp',
                                   'previousHash', 'currentCoinbase',
                                   'currentDifficulty', 'currentNumber'])
    # setup env
    header = blocks.BlockHeader(
        prevhash=decode_hex(env['previousHash']),
        number=int(env['currentNumber']),
        coinbase=decode_hex(env['currentCoinbase']),
        difficulty=int(env['currentDifficulty']),
        gas_limit=parse_int_or_hex(env['currentGasLimit']),
        timestamp=int(env['currentTimestamp']))
    blk = blocks.Block(header, db=db)

    # setup state
    for address, h in list(pre.items()):
        assert len(address) == 40
        address = decode_hex(address)
        assert set(h.keys()) == set(['code', 'nonce', 'balance', 'storage'])
        blk.set_nonce(address, int(h['nonce']))
        blk.set_balance(address, int(h['balance']))
        blk.set_code(address, decode_hex(h['code'][2:]))
        for k, v in h['storage'].items():
            blk.set_storage_data(address,
                                 utils.big_endian_to_int(decode_hex(k[2:])),
                                 utils.big_endian_to_int(decode_hex(v[2:])))

    # execute transactions
    sender = decode_hex(exek['caller'])  # a party that originates a call
    recvaddr = decode_hex(exek['address'])
    tx = transactions.Transaction(
        nonce=blk._get_acct_item(decode_hex(exek['caller']), 'nonce'),
        gasprice=int(exek['gasPrice']),
        startgas=int(exek['gas']),
        to=recvaddr,
        value=int(exek['value']),
        data=decode_hex(exek['data'][2:]))
    tx.sender = sender

    # capture apply_message calls
    apply_message_calls = []
    orig_apply_msg = pb.apply_msg

    ext = pb.VMExt(blk, tx)

    def call_wrapper(msg):
        ext.set_balance(msg.sender, ext.get_balance(msg.sender) - msg.value)
        hexdata = encode_hex(msg.data.extract_all())
        apply_message_calls.append(dict(gasLimit=to_string(msg.gas),
                                        value=to_string(msg.value),
                                        destination=encode_hex(msg.to),
                                        data=b'0x' + hexdata))
        return 1, msg.gas, b''

    def sendmsg_wrapper(msg, code):
        ext.set_balance(msg.sender, ext.get_balance(msg.sender) - msg.value)
        hexdata = encode_hex(msg.data.extract_all())
        apply_message_calls.append(dict(gasLimit=to_string(msg.gas),
                                        value=to_string(msg.value),
                                        destination=encode_hex(msg.to),
                                        data=b'0x' + hexdata))
        return 1, msg.gas, b''

    def create_wrapper(msg):
        ext.set_balance(msg.sender, ext.get_balance(msg.sender) - msg.value)
        sender = decode_hex(msg.sender) if \
            len(msg.sender) == 40 else msg.sender
        nonce = utils.encode_int(ext._block.get_nonce(msg.sender))
        addr = encode_hex(utils.sha3(rlp.encode([sender, nonce]))[12:])
        hexdata = encode_hex(msg.data.extract_all())
        apply_message_calls.append(dict(gasLimit=to_string(msg.gas),
                                        value=to_string(msg.value),
                                        destination=b'', data=b'0x' + hexdata))
        return 1, msg.gas, addr

    ext.sendmsg = sendmsg_wrapper
    ext.call = call_wrapper
    ext.create = create_wrapper

    def blkhash(n):
        if n >= ext.block_number or n < ext.block_number - 256:
            return b''
        else:
            return utils.sha3(to_string(n))

    ext.block_hash = blkhash

    msg = vm.Message(tx.sender, tx.to, tx.value, tx.startgas,
                     vm.CallData([safe_ord(x) for x in tx.data]))
    time_pre = time.time()
    success, gas_remained, output = \
        vm.vm_execute(ext, msg, decode_hex(exek['code'][2:]))
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
        params2['out'] = b'0x' + encode_hex(''.join(map(ascii_chr, output)))
        params2['gas'] = to_string(gas_remained)
        params2['logs'] = [log.to_dict() for log in blk.logs]
        params2['post'] = blk.to_dict(True)['state']

    if mode == FILL:
        return params2
    elif mode == VERIFY:
        params1 = copy.deepcopy(params)
        if 'post' in params1:
            for k, v in list(params1['post'].items()):
                if v == {'code': b'0x', 'nonce': '0', 'balance': '0', 'storage': {}}:
                    del params1['post'][k]
        if 'post' in params2:
            for k, v in list(params2['post'].items()):
                if v == {'code': b'0x', 'nonce': '0', 'balance': '0', 'storage': {}}:
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
    assert len(env['currentCoinbase']) == 40

    # setup env
    header = blocks.BlockHeader(
        prevhash=decode_hex(env['previousHash']),
        number=int(env['currentNumber']),
        coinbase=decode_hex(env['currentCoinbase']),
        difficulty=int(env['currentDifficulty']),
        gas_limit=parse_int_or_hex(env['currentGasLimit']),
        timestamp=int(env['currentTimestamp']))
    blk = blocks.Block(header, db=db)

    # setup state
    for address, h in list(pre.items()):
        assert len(address) == 40
        address = decode_hex(address)
        assert set(h.keys()) == set(['code', 'nonce', 'balance', 'storage'])
        blk.set_nonce(address, int(h['nonce']))
        blk.set_balance(address, int(h['balance']))
        blk.set_code(address, decode_hex(h['code'][2:]))
        for k, v in h['storage'].items():
            blk.set_storage_data(address,
                                 utils.big_endian_to_int(decode_hex(k[2:])),
                                 utils.big_endian_to_int(decode_hex(v[2:])))

    for address, h in list(pre.items()):
        address = decode_hex(address)
        assert blk.get_nonce(address) == int(h['nonce'])
        assert blk.get_balance(address) == int(h['balance'])
        assert blk.get_code(address) == decode_hex(h['code'][2:])
        for k, v in h['storage'].items():
            assert blk.get_storage_data(address, utils.big_endian_to_int(
                decode_hex(k[2:]))) == utils.big_endian_to_int(decode_hex(v[2:]))

    # execute transactions
    tx = transactions.Transaction(
        nonce=int(exek['nonce'] or b"0"),
        gasprice=int(exek['gasPrice'] or b"0"),
        startgas=parse_int_or_hex(exek['gasLimit'] or b"0"),
        to=decode_hex(exek['to'][2:] if exek['to'][:2] == b'0x' else exek['to']),
        value=int(exek['value'] or b"0"),
        data=decode_hex(exek['data'][2:])).sign(exek['secretKey'])

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

    time_pre = time.time()
    try:
        # with a blk.commit_state() the tests pass
        success, output = pb.apply_transaction(blk, tx)
        blk.commit_state()
    except pb.InvalidTransaction:
        success, output = False, b''
        blk.commit_state()
        pass
    time_post = time.time()

    if tx.to == b'':
        output = blk.get_code(output)

    pb.apply_msg = orig_apply_msg

    params2 = copy.deepcopy(params)
    if success:
        params2['out'] = b'0x' + encode_hex(output)
        params2['post'] = copy.deepcopy(blk.to_dict(True)['state'])
        params2['logs'] = [log.to_dict() for log in blk.get_receipt(0).logs]
        params2['postStateRoot'] = encode_hex(blk.state.root_hash)

    if mode == FILL:
        return params2
    elif mode == VERIFY:
        params1 = copy.deepcopy(params)
        if 'post' in params1:
            for k, v in list(params1['post'].items()):
                if v == {'code': b'0x', 'nonce': '0', 'balance': '0', 'storage': {}}:
                    del params1['post'][k]
        if 'post' in params2:
            for k, v in list(params2['post'].items()):
                if v == {'code': b'0x', 'nonce': '0', 'balance': '0', 'storage': {}}:
                    del params2['post'][k]
        for k in ['pre', 'exec', 'env', 'callcreates',
                  'out', 'gas', 'logs', 'post', 'postStateRoot']:
            shouldbe = params1.get(k, None)
            reallyis = params2.get(k, None)
            if shouldbe != reallyis:
                raise Exception("Mismatch: " + k + ':\n shouldbe %r\n reallyis %r' % (shouldbe, reallyis))

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


def test_chain_data(blks, db=None, skip=0):
    if db is None:
        db = EphemDB()

    chain_manager = utils.get_chainmanager(db, blocks.genesis(db))

    # Total quantity of ether
    tot = sum([int(y["balance"]) for x, y in
               list(chain_manager.head.to_dict(True)["state"].items())])

    # Guaranteed safe funds in each account
    safe = {x: y["balance"] for x, y in
            list(chain_manager.head.to_dict(True)["state"].items())}

    # Process blocks sequentially
    for blk in blks[skip:]:
        print(blk.number, encode_hex(blk.hash),
              '%d txs' % len(blk.transaction_list))
        head = chain_manager.head
        assert blocks.check_header_pow(blk.header_args)
        chain_manager.receive_chain([blk])
        newhead = chain_manager.head
        newtot = sum([int(y["balance"]) for x, y in
                      list(newhead.to_dict(True)["state"].items())])
        if newtot != tot + newhead.ether_delta:
            raise Exception("Ether balance sum mismatch: %d %d" %
                            (newtot, tot + newhead.ether_delta))
        for tx in blk.get_transactions():
            safe[tx.sender] = max(safe.get(tx.sender, 0) - tx.value, 0)
        tot = newtot
        if blk.hash not in chain_manager:
            print('block could not be added')
            assert head == chain_manager.head
            chain_manager.head.deserialize_child(blk.rlpdata)
            assert blk.hash in chain_manager
    return safe


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
