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
    o = raw_call(0x0000000000000000000000000000000000000006, x, gas=99999999, outsize=64)
    self.h = sha3(o)
    return o
"""

x1 = c.contract(kode, language='viper')


def mk_ecadd_data(p1, p2):
    if isinstance(p1[0], py_pairing.FQ):
        p1 = py_pairing.normalize(p1)
        p1 = (p1[0].n, p1[1].n)
    if isinstance(p2[0], py_pairing.FQ):
        p2 = py_pairing.normalize(p2)
        p2 = (p2[0].n, p2[1].n)
    return encode_int32(p1[0]) + encode_int32(p1[1]) + \
        encode_int32(p2[0]) + encode_int32(p2[1])


def intrinsic_gas_of_data(d):
    return opcodes.GTXDATAZERO * \
        d.count(0) + opcodes.GTXDATANONZERO * (len(d) - d.count(0))


def mk_test(p1, p2, execgas, datarestrict=128):
    encoded = mk_ecadd_data(p1, p2)[:datarestrict] + \
        b'\x00' * max(datarestrict - 128, 0)
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
        if py_pairing.normalize(py_pairing.add(p1, p2)) != (
                py_pairing.FQ(x), py_pairing.FQ(y)):
            raise Exception("Mismatch! %r %r %d, expected %r computed %r" %
                            (p1, p2, datarestrict, py_pairing.normalize(py_pairing.add(p1, p2)), (x, y)))
        print('Succeeded! %r %r %d %r' % (p1, p2, datarestrict, (x, y)))
    except tester.TransactionFailed:
        print('OOG %r %r %d %d' % (p1, p2, datarestrict, execgas))
    o = tester.mk_state_test_postfill(c, pre)
    o2 = tester.mk_state_test_postfill(c, pre, filler_mode=True)
    assert new_statetest_utils.verify_state_test(o)
    return o, o2


gaslimits = [21000, 25000]

zero = (py_pairing.FQ(1), py_pairing.FQ(1), py_pairing.FQ(0))

wrong1 = (py_pairing.FQ(1), py_pairing.FQ(3), py_pairing.FQ(1))
wrong2 = (py_pairing.FQ(0), py_pairing.FQ(3), py_pairing.FQ(1))
wrong3 = (py_pairing.FQ(6), py_pairing.FQ(9), py_pairing.FQ(1))
wrong4 = (py_pairing.FQ(19274124), py_pairing.FQ(124124), py_pairing.FQ(1))

tests = []
for g in gaslimits:
    tests.append((zero, zero, g, 128))
    tests.append((zero, zero, g, 64))
    tests.append((zero, zero, g, 80))
    tests.append((zero, zero, g, 0))
    tests.append((zero, zero, g, 192))
    tests.append((zero, py_pairing.G1, g, 128))
    tests.append((zero, py_pairing.G1, g, 192))
    tests.append((py_pairing.G1, zero, g, 64))
    tests.append((py_pairing.G1, zero, g, 128))
    tests.append((py_pairing.G1, zero, g, 192))
    tests.append((py_pairing.G1, py_pairing.G1, g, 128))
    tests.append((py_pairing.G1, py_pairing.G1, g, 192))
    tests.append(
        (py_pairing.multiply(
            py_pairing.G1, 5), py_pairing.multiply(
            py_pairing.G1, 9), g, 128))
    tests.append(
        (py_pairing.multiply(
            py_pairing.G1, 5), py_pairing.multiply(
            py_pairing.G1, py_pairing.curve_order - 5), g, 192))
    tests.append((zero, wrong1, g, 128))
    tests.append((wrong1, zero, g, 80))
    tests.append((wrong2, py_pairing.G1, g, 128))
    tests.append((wrong3, wrong4, g, 128))

testout = {}
testout_filler = {}

for test in tests:
    o1, o2 = mk_test(*test)
    n1, n2 = py_pairing.normalize(test[0]), py_pairing.normalize(test[1])
    testout["ecadd_%r-%r_%r-%r_%d_%d" %
            (n1[0], n1[1], n2[0], n2[1], test[2], test[3])] = o1
    o2["explanation"] = "Puts the points %r and %r into the ECADD precompile, truncating or expanding the input data to %d bytes. Gives the execution %d bytes" % (
        n1, n2, test[3], test[2])
    testout_filler["ecadd_%r-%r_%r-%r_%d_%d" %
                   (n1[0], n1[1], n2[0], n2[1], test[2], test[3])] = o2
open('ecadd_tests.json', 'w').write(json.dumps(testout, indent=4))
open(
    'ecadd_tests_filler.json',
    'w').write(
        json.dumps(
            testout_filler,
            indent=4))
