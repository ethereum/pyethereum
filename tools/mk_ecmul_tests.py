from ethereum.tools import tester
from ethereum import opcodes
from ethereum.utils import int_to_big_endian, encode_int32, big_endian_to_int
from ethereum.tools import new_statetest_utils
import json
import py_pairing

c = tester.Chain(env='metropolis')
c.head_state.gas_limit = 10**8

kode = """
h: bytes32

def foo(x: bytes <= 192) -> bytes <= 64:
    o = raw_call(0x0000000000000000000000000000000000000007, x, gas=99999999, outsize=64)
    self.h = sha3(o)
    return o
"""

x1 = c.contract(kode, language='viper')


def mk_ecmul_data(p1, m):
    if isinstance(p1[0], py_pairing.FQ):
        p1 = py_pairing.normalize(p1)
        p1 = (p1[0].n, p1[1].n)
    return encode_int32(p1[0]) + encode_int32(p1[1]) + encode_int32(m)


def intrinsic_gas_of_data(d):
    return opcodes.GTXDATAZERO * \
        d.count(0) + opcodes.GTXDATANONZERO * (len(d) - d.count(0))


def mk_test(p1, m, execgas, datarestrict=96):
    encoded = mk_ecmul_data(p1, m)[:datarestrict] + \
        b'\x00' * max(datarestrict - 96, 0)
    pre = tester.mk_state_test_prefill(c)
    try:
        o = x1.foo(
            encoded,
            startgas=21000 +
            intrinsic_gas_of_data(
                x1.translator.encode(
                    'foo',
                    [encoded])) +
            execgas)
        x, y = big_endian_to_int(o[:32]), big_endian_to_int(o[32:])
        if py_pairing.normalize(py_pairing.multiply(p1, m)) != (
                py_pairing.FQ(x), py_pairing.FQ(y)):
            raise Exception("Mismatch! %r %r %d, expected %r computed %r" %
                            (p1, m, datarestrict, py_pairing.normalize(py_pairing.multiply(p1, m)), (x, y)))
        print('Succeeded! %r %d %d %r' % (p1, m, datarestrict, (x, y)))
    except tester.TransactionFailed:
        print('OOG %r %d %d %d' % (p1, m, datarestrict, execgas))
    o = tester.mk_state_test_postfill(c, pre)
    o2 = tester.mk_state_test_postfill(c, pre, filler_mode=True)
    assert new_statetest_utils.verify_state_test(o)
    return o, o2


zero = (py_pairing.FQ(1), py_pairing.FQ(1), py_pairing.FQ(0))

wrong1 = (py_pairing.FQ(1), py_pairing.FQ(3), py_pairing.FQ(1))
wrong2 = (py_pairing.FQ(0), py_pairing.FQ(3), py_pairing.FQ(1))

gaslimits = [21000, 28000]
mults = [
    0,
    1,
    2,
    9,
    2**128,
    py_pairing.curve_order -
    1,
    py_pairing.curve_order,
    2**256 -
    1]
pts = [
    zero,
    py_pairing.G1,
    py_pairing.multiply(
        py_pairing.G1,
        98723629835235),
    wrong1,
    wrong2]

tests = []
for g in gaslimits:
    for m in mults:
        for pt in pts:
            tests.append((pt, m, g, 96))
            tests.append((pt, m, g, 128))
            if m == 0:
                tests.append((pt, m, g, 64))
            if not m % 2**128:
                tests.append((pt, m, g, 80))
            if m == 0 and pt == zero:
                tests.append((pt, m, g, 0))
                tests.append((pt, m, g, 40))

testout = {}
testout_filler = {}

for test in tests:
    o1, o2 = mk_test(*test)
    n = py_pairing.normalize(test[0])
    testout["ecmul_%r-%r_%d_%d_%d" %
            (n[0], n[1], test[1], test[2], test[3])] = o1
    o2["explanation"] = "Puts the point %r and the factor %d into the ECMUL precompile, truncating or expanding the input data to %d bytes. Gives the execution %d bytes" % (
        n, test[1], test[3], test[2])
    testout_filler["ecmul_%r-%r_%d_%d_%d" %
                   (n[0], n[1], test[1], test[2], test[3])] = o2
open('ecmul_tests.json', 'w').write(json.dumps(testout, indent=4))
open(
    'ecmul_tests_filler.json',
    'w').write(
        json.dumps(
            testout_filler,
            indent=4))
