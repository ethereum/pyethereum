from ethereum.tools import tester
from ethereum import opcodes
from ethereum.utils import int_to_big_endian, encode_int32, big_endian_to_int
from ethereum.tools import new_statetest_utils
import json

c = tester.Chain(alloc=tester.minimal_alloc, env='metropolis')
c.head_state.gas_limit = 10**8

kode = """
h: bytes32

def foo(x: bytes <= %d) -> bytes <= %d:
    o = raw_call(0x0000000000000000000000000000000000000005, x, gas=99999999, outsize=%d)
    self.h = sha3(o)
    return o
"""


def mk_modexp_data(b, e, m):
    benc = int_to_big_endian(b)
    eenc = int_to_big_endian(e)
    menc = int_to_big_endian(m)
    return encode_int32(len(benc)) + encode_int32(len(eenc)) + \
        encode_int32(len(menc)) + benc + eenc + menc


def intlen(o):
    return len(int_to_big_endian(o))


def intrinsic_gas_of_data(d):
    return opcodes.GTXDATAZERO * \
        d.count(0) + opcodes.GTXDATANONZERO * (len(d) - d.count(0))


def mk_test(b, e, m, execgas):
    encoded = mk_modexp_data(b, e, m)
    s = c.snapshot()
    x = c.contract(kode % (len(encoded) + 36, max(intlen(m), 1),
                           max(intlen(m), 1)), language='viper')
    pre = tester.mk_state_test_prefill(c)
    try:
        o = x.foo(
            encoded,
            startgas=21000 +
            intrinsic_gas_of_data(
                x.translator.encode(
                    'foo',
                    [encoded])) +
            execgas)
        if big_endian_to_int(o[:intlen(m)]) != (pow(b, e, m) if m else 0):
            raise Exception("Mismatch! %d %d %d expected %d computed %d" % (
                b, e, m, pow(b, e, m), big_endian_to_int(o[:intlen(m)])))
        print("Succeeded %d %d %d sg %d" % (b, e, m, execgas))
    except tester.TransactionFailed:
        print('OOG %d %d %d sg %d' % (b, e, m, execgas))
    print(c.last_sender)
    o = tester.mk_state_test_postfill(c, pre)
    o2 = tester.mk_state_test_postfill(c, pre, filler_mode=True)
    assert new_statetest_utils.verify_state_test(o)
    c.revert(s)
    return o, o2


gaslimits = [20500, 22000, 25000, 35000, 155000, 1000000]

tests = []
for g in gaslimits:
    tests.append((3, 5, 100, g))
for g in gaslimits:
    tests.append((3, 2**254, 2**256, g))
for g in gaslimits:
    tests.append((0, 3, 100, g))
for g in gaslimits:
    tests.append((0, 0, 0, g))
for g in gaslimits:
    tests.append((0, 1, 0, g))
for g in gaslimits:
    tests.append((1, 0, 0, g))
for g in gaslimits:
    tests.append((1, 0, 1, g))
for g in gaslimits:
    tests.append((2**256, 1, 3**160, g))
for g in gaslimits:
    tests.append((9, 2**1024 - 105, 2**1024 - 105, g))
for g in gaslimits:
    tests.append((2**1024 - 96, 2**1024 - 105, 2**1024 - 105, g))
for g in gaslimits:
    tests.append((2**1024 - 96, 2**1024 - 105, 97, g))
for g in gaslimits:
    tests.append((2**1024 - 96, 2**1024 - 105, 1, g))
for g in gaslimits:
    tests.append((2**1024 - 96, 2**1024 - 105, 0, g))
for g in gaslimits:
    tests.append((1, 1, 1, g))
for g in gaslimits:
    tests.append((49, 2401, 2401, g))
for g in gaslimits:
    tests.append((3**160 - 11, 3**160 - 11, 2**160 - 11, g))

testout = {}
testout_filler = {}

for test in tests:
    o1, o2 = mk_test(*test)
    testout["modexp_%d_%d_%d_%d" % test] = o1
    o2["explanation"] = "Puts the base %d, exponent %d and modulus %d into the MODEXP precompile, saves the hash of the result. Gives the execution %d gas" % test
    testout_filler["modexp_%d_%d_%d_%d" % test] = o2
open('modexp_tests.json', 'w').write(json.dumps(testout, indent=4))
open(
    'modexp_tests_filler.json',
    'w').write(
        json.dumps(
            testout_filler,
            indent=4))
