from pyethereum import tester as t
from pyethereum import blocks, utils, transactions, vm
import rlp
from pyethereum import processblock as pb
import tempfile
import copy
from db import DB
import json
import os
db = DB(utils.db_path(tempfile.mktemp()))

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
VM = 3
STATE = 4
fill_vm_test = lambda params: run_vm_test(params, FILL)
check_vm_test = lambda params: run_vm_test(params, VERIFY)
fill_state_test = lambda params: run_state_test(params, FILL)
check_state_test = lambda params: run_state_test(params, VERIFY)


def mktest(code, language, data=None, fun=None, args=None,
           gas=1000000, value=0, test_type=VM):
    s = t.state(1)
    if language == 'evm':
        ca = s.contract('x = 5')
        s.block.set_code(ca, code)
        d = data or ''
    else:
        c = s.abi_contract(code, language=language)
        d = c._translator.encode(fun, args) if fun else data
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
        tx = {"data": '0x'+d.encode('hex'), "gasLimit": str(gas),
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
    header = blocks.BlockHeader(
                       prevhash=env['previousHash'].decode('hex'),
                       number=int(env['currentNumber']),
                       coinbase=env['currentCoinbase'].decode('hex'),
                       difficulty=int(env['currentDifficulty']),
                       gas_limit=int(env['currentGasLimit']),
                       timestamp=int(env['currentTimestamp']))
    blk = blocks.Block(header, db=db)

    # setup state
    for address, h in pre.items():
        assert len(address) == 40
        address = address.decode('hex')
        assert set(h.keys()) == set(['code', 'nonce', 'balance', 'storage'])
        blk.set_nonce(address, int(h['nonce']))
        blk.set_balance(address, int(h['balance']))
        blk.set_code(address, h['code'][2:].decode('hex'))
        for k, v in h['storage'].iteritems():
            blk.set_storage_data(address,
                                 utils.big_endian_to_int(k[2:].decode('hex')),
                                 utils.big_endian_to_int(v[2:].decode('hex')))

    # execute transactions
    sender = exek['caller'].decode('hex')  # a party that originates a call
    recvaddr = exek['address'].decode('hex')
    tx = transactions.Transaction(
        nonce=blk._get_acct_item(exek['caller'].decode('hex'), 'nonce'),
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
                                        destination=msg.to.encode('hex'),
                                        data='0x'+hexdata))
        return 1, msg.gas, ''

    def sendmsg_wrapper(msg, code):
        ext.set_balance(msg.sender, ext.get_balance(msg.sender) - msg.value)
        hexdata = msg.data.extract_all().encode('hex')
        apply_message_calls.append(dict(gasLimit=str(msg.gas),
                                        value=str(msg.value),
                                        destination=msg.to.encode('hex'),
                                        data='0x'+hexdata))
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
    success, gas_remained, output = \
        vm.vm_execute(ext, msg, exek['code'][2:].decode('hex'))
    pb.apply_msg = orig_apply_msg
    blk.commit_state()
    for s in blk.suicides:
        blk.del_account(s)

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
    if mode == VERIFY:
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


# Fills up a vm test without post data, or runs the test
def run_state_test(params, mode):
    pre = params['pre']
    exek = params['transaction']
    env = params['env']

    assert set(env.keys()) == set(['currentGasLimit', 'currentTimestamp',
                                   'previousHash', 'currentCoinbase',
                                   'currentDifficulty', 'currentNumber'])
    assert len(env['currentCoinbase']) == 40
    env['currentCoinbase'] = env['currentCoinbase'].decode('hex')

    # setup env
    header = blocks.BlockHeader(
                       prevhash=env['previousHash'].decode('hex'),
                       number=int(env['currentNumber']),
                       coinbase=env['currentCoinbase'],
                       difficulty=int(env['currentDifficulty']),
                       gas_limit=int(env['currentGasLimit']),
                       timestamp=int(env['currentTimestamp']))
    blk = blocks.Block(header, db=db)

    # setup state
    for address, h in pre.items():
        assert len(address) == 40
        address = address.decode('hex')
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
        startgas=int(exek['gasLimit'] or "0"),
        to=(exek['to'][2:] if exek['to'][:2] == '0x' else exek['to']).decode('hex'),
        value=int(exek['value'] or "0"),
        data=exek['data'][2:].decode('hex')).sign(exek['secretKey'])

    orig_apply_msg = pb.apply_msg

    def apply_msg_wrapper(ext, msg, code):

        def blkhash(n):
            if n >= blk.number or n < blk.number - 256:
                return ''
            else:
                return utils.sha3(str(n))

        ext.block_hash = blkhash
        return orig_apply_msg(ext, msg, code)

    pb.apply_msg = apply_msg_wrapper

    try:
        success, output = pb.apply_transaction(blk, tx)
        blk.commit_state()
    except pb.InvalidTransaction:
        success, output = False, ''
        pass

    if tx.to == '':
        output = blk.get_code(output)

    pb.apply_msg = orig_apply_msg

    params2 = copy.deepcopy(params)
    if success:
        params2['out'] = '0x' + output.encode('hex')
        params2['post'] = blk.to_dict(True)['state']
        params2['logs'] = [log.to_dict() for log in blk.get_receipt(0).logs]

    if mode == FILL:
        return params2
    if mode == VERIFY:
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
