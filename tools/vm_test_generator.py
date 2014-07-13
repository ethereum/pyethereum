import json
import pyethereum
t = pyethereum.tester
pb = pyethereum.processblock
import serpent
import sys


# Code: serpent code
# Tx:[ val, data ]
def gen_test(code, val, data):
    while 1:
        s = t.state(1)
        c = s.contract(code)
        pre = s.block.to_dict()['state']
        env = {
            "currentCoinbase": s.block.coinbase,
            "currentDifficulty": str(s.block.difficulty),
            "currentGasLimit": str(s.block.gas_limit),
            "currentNumber": str(s.block.number),
            "currentTimestamp": str(s.block.timestamp),
            "previousHash": s.block.prevhash.encode('hex')
        }
        apply_message_calls = []

        orig_apply_msg = pb.apply_msg

        def apply_msg_wrapper(_block, _tx, msg, code):
            pb.enable_debug()
            apply_message_calls.append(dict(gasLimit=msg.gas, value=msg.value,
                                            desgination=msg.to,
                                            data=msg.data.encode('hex')))
            result, gas_rem, data = orig_apply_msg(_block, _tx, msg, code)
            pb.disable_debug()
            return result, gas_rem, data

        pb.apply_msg = apply_msg_wrapper

        d = serpent.encode_datalist(map(int, data))
        tx = pyethereum.transactions.Transaction(1, 10**12, 10000, c, val, data)\
            .sign(t.keys[0])
        msg = pb.Message(t.accounts[0], c, val, 10000, d)
        exek = {
            "address": msg.to,
            "caller": msg.sender,
            "code": '0x'+s.block.get_code(c).encode('hex'),
            "data": '0x'+d.encode('hex'),
            "gas": str(10000),
            "gasPrice": str(10**12),
            "origin": tx.sender,
            "value": str(val)
        }
        success, gas, o = pb.apply_msg(s.block, tx, msg, s.block.get_code(c))
        post = s.block.to_dict()['state']
        callcreates = apply_message_calls[1:]
        if success:
            break

    return {
        "callcreates": callcreates,
        "env": env,
        "pre": pre,
        "post": post,
        "exec": exek,
        "gas": str(gas),
        "out": '0x'+''.join(map(chr, o)).encode('hex')
    }

if __name__ == "__main__":
    o = gen_test(sys.argv[2], int(sys.argv[3]), sys.argv[4:])
    print json.dumps({sys.argv[1]: o}, indent=4)
