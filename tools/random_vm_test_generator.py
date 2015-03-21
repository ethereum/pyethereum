import json
import pyethereum
t = pyethereum.tester
pb = pyethereum.processblock
u = pyethereum.utils
import sys
import random
from rlp.utils import encode_hex, ascii_chr

def mkrndgen(seed):
    state = [0, 0]

    def rnd(n):
        if state[0] < 2**32:
            state[0] = u.big_endian_to_int(u.sha3(seed+str(state[1]+1)))
            state[1] += 1
        o = state[0] % n
        state[0] /= n
        return o
    return rnd


def gen_random_code(rnd):
    o = []
    for i in range(4):
        o.extend([96, rnd(256)])
        o.extend([99] + [rnd(256) for i in range(4)])
    ops = pyethereum.opcodes.opcodes.keys()
    o += [ops[rnd(len(ops))] for i in range(64)]
    return ''.join(map(ascii_chr, o))


# Code: serpent code
# Tx:[ val, data ]
def gen_test(seed):
    orig_apply_msg = pb.apply_msg
    apply_message_calls = []
    i = 0

    def apply_msg_wrapper(_block, _tx, msg, code):
        apply_message_calls.append(dict(gasLimit=msg.gas,
                                        value=msg.value,
                                        desgination=msg.to,
                                        data=encode_hex(msg.data)))
        result, gas_rem, out = orig_apply_msg(_block, _tx, msg, code)
        return result, gas_rem, out

    pb.apply_msg = apply_msg_wrapper

    while 1:
            CODE = gen_random_code(mkrndgen(seed+str(i)))
            DATA = gen_random_code(mkrndgen(seed+str(i+1)))
            i += 2
            VAL = 0
            s = t.state(1)
            FROM = t.keys[0]
            FROMADDR = t.accounts[0]
            TO = t.accounts[1]
            s.block.delta_balance(TO, 1)
            pre = s.block.to_dict()['state']
            env = {
                "currentCoinbase": s.block.coinbase,
                "currentDifficulty": str(s.block.difficulty),
                "currentGasLimit": str(s.block.gas_limit),
                "currentNumber": str(s.block.number),
                "currentTimestamp": str(s.block.timestamp),
                "previousHash": encode_hex(s.block.prevhash)
            }
            apply_message_calls = []

            tx = pyethereum.transactions.Transaction(1, 10**12, 10000, TO, VAL, DATA)\
                .sign(FROM)
            msg = pb.Message(FROMADDR, TO, VAL, 10000, DATA)
            exek = {
                "address": msg.to,
                "caller": msg.sender,
                "code": '0x' + encode_hex(CODE),
                "data": '0x' + encode_hex(DATA),
                "gas": str(10000),
                "gasPrice": str(10**12),
                "origin": tx.sender,
                "value": str(VAL)
            }
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
        "out": '0x' + encode_hex(''.join(map(ascii_chr, o)))
    }

if __name__ == "__main__":
    o = gen_test((sys.argv + [str(random.randrange(10**50))])[2])
    print json.dumps({sys.argv[1]: o}, indent=4)
