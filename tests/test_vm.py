import pytest
import json
import pyethereum.processblock as pb
import pyethereum.blocks as blocks
import pyethereum.transactions as transactions
import pyethereum.utils as u

import logging
logging.basicConfig(level=logging.DEBUG, format='%(message)s')
logger = logging.getLogger()
pblogger = pb.pblogger

# customize VM log output to your needs
# hint: use 'py.test' with the '-s' option to dump logs to the console
pblogger.log_pre_state = True    # dump storage at account before execution
pblogger.log_post_state = True   # dump storage at account after execution
pblogger.log_block = False       # dump block after TX was applied
pblogger.log_memory = False      # dump memory before each op
pblogger.log_op = True           # log op, gas, stack before each op
pblogger.log_json = False        # generate machine readable output


def check_testdata(data_keys, expected_keys):
    assert set(data_keys) == set(expected_keys), \
        "test data changed, please adjust tests"


@pytest.fixture(scope="module")
def vm_tests_fixtures(name):
    """Read vm tests from fixtures"""
    # FIXME: assert that repo is uptodate
    # cd fixtures; git pull origin develop; cd ..;  git commit fixtures

    filename = 'fixtures/' + name + '.json'

    try:
        vm_fixture = json.load(open(filename, 'r'))
    except IOError:
        raise IOError("Could not read " + filename + " from fixtures",
            "Make sure you did 'git submodule init'")
    
    return vm_fixture

def test_random():
    do_test_vm('random')

def test_generic():
    do_test_vm('vmtests')

def test_Arithmetic():
    do_test_vm('vmArithmeticTest')

def test_BitwiseLogicOperation():
    do_test_vm('vmBitwiseLogicOperationTest')

def do_test_vm(name):
    logger.debug('running test:%r', name)
    for testname in vm_tests_fixtures(name).keys():

        logger.debug('running test:%r', testname)
               
        params = vm_tests_fixtures(name)[testname]

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
            pblogger.log('PRE Balance', address=address, balance=h['balance'])
    
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
        pblogger.log('TX', tx=tx.hex_hash(), sender=sender, to=recvaddr, value=tx.value, startgas=tx.startgas, gasprice=tx.gasprice)
    
        # capture apply_message calls
        apply_message_calls = []
        orig_apply_msg = pb.apply_msg
    
        def apply_msg_wrapper(_block, _tx, msg, code):
            apply_message_calls.append(dict(gasLimit=msg.gas, value=msg.value,
                                            destination=msg.to,
                                            data=msg.data.encode('hex')))
            result, gas_rem, data = orig_apply_msg(_block, _tx, msg, code)
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

            # check hex values in same format

            def newFormat(x):
                if x == '0x':
                    return '0x00'
		elif x[:2] == '0x':
		    return "0x%0.2X" % int(x,0)
     
            data['storage'] = {  newFormat(k) : newFormat(v[0]) for k,v in data['storage'].items() }
            state['storage'] = { newFormat(k) : newFormat(v) for k,v in state['storage'].items()}   

            #if len(state['storage'])==0: continue

            assert data == state
