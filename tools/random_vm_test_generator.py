import json
import pyethereum
t = pyethereum.tester
pb = pyethereum.processblock
import sys
import random


def gen_random_code():
    o = []
    for i in range(4):
        o.extend([96, random.randrange(256)])
        o.extend([99] + [random.randrange(256) for i in range(4)])
    ops = pyethereum.opcodes.opcodes.keys()
    o += [random.choice(ops) for i in range(64)]
    return ''.join(map(chr, o))


# Code: serpent code
# Tx:[ val, data ]
def gen_test():
    orig_apply_msg = pb.apply_msg
    apply_message_calls = []

    def apply_msg_wrapper(_block, _tx, msg, code):
        pb.enable_debug()
        apply_message_calls.append(dict(gasLimit=msg.gas,
                                        value=msg.value,
                                        desgination=msg.to,
                                        data=msg.data.encode('hex')))
        result, gas_rem, out = orig_apply_msg(_block, _tx, msg, code)
        pb.disable_debug()
        return result, gas_rem, out

    pb.apply_msg = apply_msg_wrapper

    while 1:
            CODE = gen_random_code()
            DATA = gen_random_code()
            VAL = 0
            s = t.state(1)
            pre = s.block.to_dict()['state']
            FROM = t.keys[0]
            FROMADDR = t.accounts[0]
            TO = t.accounts[1]
            env = {
                "currentCoinbase": s.block.coinbase,
                "currentDifficulty": str(s.block.difficulty),
                "currentGasLimit": str(s.block.gas_limit),
                "currentNumber": str(s.block.number),
                "currentTimestamp": str(s.block.timestamp),
                "previousHash": s.block.prevhash.encode('hex')
            }
            apply_message_calls = []

            tx = pyethereum.transactions.Transaction(1, 10**12, 10000, TO, VAL, DATA)\
                .sign(FROM)
            msg = pb.Message(FROMADDR, TO, VAL, 10000, DATA)
            exek = {
                "address": msg.to,
                "caller": msg.sender,
                "code": '0x'+CODE.encode('hex'),
                "data": '0x'+DATA.encode('hex'),
                "gas": str(10000),
                "gasPrice": str(10**12),
                "origin": tx.sender,
                "value": str(VAL)
            }
            pb.enable_debug()
            success, gas, o = pb.apply_msg(s.block, tx, msg, CODE)
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
        "out": o
    }

if __name__ == "__main__":
    o = gen_test()
    print json.dumps({sys.argv[1]: o}, indent=4)
