from ethereum.tools import tester
from ethereum import opcodes
from ethereum.utils import int_to_big_endian, encode_int32, big_endian_to_int
from ethereum.tools import new_statetest_utils
import json
import py_pairing
from ethereum.opcodes import GPAIRINGBASE as GPB
from ethereum.opcodes import GPAIRINGPERPOINT as GPP

c = tester.Chain(env='metropolis')
c.head_state.gas_limit = 10**8

kode = """
h: bytes32

def foo(x: bytes <= 1920) -> bytes <= 32:
    o = raw_call(0x0000000000000000000000000000000000000008, x, gas=99999999, outsize=32)
    self.h = sha3(o)
    return o
"""

x1 = c.contract(kode, language='viper')

# Generate a point on the G2 curve, but not in the correct subgroup
fake_point = None
FQ2_one = py_pairing.FQ2.one()
big_order = py_pairing.curve_order * \
    (py_pairing.field_modulus * 2 - py_pairing.curve_order)
G1_zero = (py_pairing.FQ.one(), py_pairing.FQ.one(), py_pairing.FQ.zero())
G2_zero = (FQ2_one, FQ2_one, py_pairing.FQ2.zero())
for i in range(200):
    x = py_pairing.FQ2([8, i])
    ysquared = x ** 3 + py_pairing.b2
    y = ysquared ** ((py_pairing.field_modulus ** 2 + 15) // 32)
    if y ** 2 == ysquared:
        assert py_pairing.multiply((x, y, FQ2_one), big_order) == G2_zero
        assert py_pairing.multiply(
            (x, y, FQ2_one), py_pairing.curve_order) != G2_zero
    fake_point = (x, y, FQ2_one)
    break


def mk_ecpairing_data(pts):
    o = b''
    for p, q in pts:
        np, nq = py_pairing.normalize(p), py_pairing.normalize(q)
        o += encode_int32(np[0].n) + encode_int32(np[1].n) + \
            encode_int32(nq[0].coeffs[1]) + encode_int32(nq[0].coeffs[0]) + \
            encode_int32(nq[1].coeffs[1]) + encode_int32(nq[1].coeffs[0])
    return o


def perturb(inp, pos, by):
    return inp[:pos] + \
        encode_int32(big_endian_to_int(
            inp[pos: pos + 32]) + by) + inp[pos + 32:]


def intrinsic_gas_of_data(d):
    return opcodes.GTXDATAZERO * \
        d.count(0) + opcodes.GTXDATANONZERO * (len(d) - d.count(0))


def mk_test(encoded, execgas, expect):
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
    except tester.TransactionFailed:
        o = False
    if o is False:
        if expect != 'error':
            raise Exception('OOG')
    elif o == encode_int32(1):
        if expect != 'yes':
            raise Exception('False positive')
    elif o == encode_int32(0):
        if expect != 'no':
            raise Exception('False negative')
    else:
        raise Exception("wtf: %r" % o)
    o = tester.mk_state_test_postfill(c, pre)
    o2 = tester.mk_state_test_postfill(c, pre, filler_mode=True)
    assert new_statetest_utils.verify_state_test(o)
    return o, o2


tests = []
G1, G2 = py_pairing.G1, py_pairing.G2
m = py_pairing.multiply
co = py_pairing.curve_order
fm = py_pairing.field_modulus
tests.append((b'', GPB - 1, 'error', 'empty_data_insufficient_gas'))
tests.append((b'', GPB + 30000, 'yes', 'empty_data'))
tests.append((mk_ecpairing_data([(G1, G2)]), GPB +
              30000, 'error', 'one_point_insufficient_gas'))
tests.append((mk_ecpairing_data([(G1, G2)]),
              GPB + GPP + 30000, 'no', 'one_point_fail'))
tests.append((mk_ecpairing_data([(G1_zero, G2)]),
              GPB + GPP + 30000, 'yes', 'one_point_with_g1_zero'))
tests.append((mk_ecpairing_data([(G1, G2_zero)]),
              GPB + GPP + 30000, 'yes', 'one_point_with_g2_zero'))
tests.append((mk_ecpairing_data([(G1, G2)])[
             :191], GPB + GPP + 30000, 'error', 'bad_length_191'))
tests.append((mk_ecpairing_data([(G1, G2)]) +
              b'\x00', GPB +
              GPP +
              30000, 'error', 'bad_length_193'))
tests.append((mk_ecpairing_data([(G1, G2), (G1, G2)]),
              GPB + GPP * 2 + 30000, 'no', 'two_point_fail_1'))
tests.append((mk_ecpairing_data([(G1, G2_zero), (G1, G2)]),
              GPB + GPP * 2 + 30000, 'no', 'two_points_with_one_g2_zero'))
tests.append((mk_ecpairing_data([(G1, G2), (m(G1, co - 1), G2)]),
              GPB + GPP * 2 + 30000, 'yes', 'two_point_match_1'))
tests.append((mk_ecpairing_data(
    [(G1, G2), (m(G1, co - 1), G2)]), GPB + GPP + 30000, 'error', 'two_point_oog'))
tests.append((mk_ecpairing_data([(G1, G2), (G1, m(G2, co - 1))]),
              GPB + GPP * 2 + 30000, 'yes', 'two_point_match_2'))
tests.append((mk_ecpairing_data([(G1, m(G2, 2)), (m(
    G1, co - 2), G2)]), GPB + GPP * 2 + 30000, 'yes', 'two_point_match_3'))
tests.append((mk_ecpairing_data([(m(G1, 27), m(G2, 37)), (G1, m(
    G2, co - 999))]), GPB + GPP * 2 + 30000, 'yes', 'two_point_match_4'))
tests.append((mk_ecpairing_data([(m(G1, 27), m(G2, 37)), (G1, m(
    G2, 998))]), GPB + GPP * 2 + 30000, 'no', 'two_point_fail_2'))
tests.append((mk_ecpairing_data([(G1, G2_zero), (G1_zero, G2)]),
              GPB + GPP * 2 + 30000, 'yes', 'two_point_match_5'))
tests.append((mk_ecpairing_data([(m(G1, 27), m(G2, 37)), (G1, m(G2, co - 999)), (G1, G2_zero)]),
              GPB + GPP * 3 + 30000, 'yes', 'three_point_match_1'))
tests.append((mk_ecpairing_data([(m(G1, 27), m(G2, 37)), (G1, m(G2, 999)), (G1, G2)]),
              GPB + GPP * 3 + 30000, 'no', 'three_point_fail_1'))
tests.append((mk_ecpairing_data([(G1_zero, fake_point)]),
              GPB + GPP + 30000, 'error', 'one_point_not_in_subgroup'))
tests.append((perturb(mk_ecpairing_data(
    [(G1_zero, G2)]), 0, 1), GPB + GPP + 30000, 'error', 'perturb_zeropoint_by_one'))
tests.append((perturb(mk_ecpairing_data(
    [(G1_zero, G2)]), 0, co), GPB + GPP + 30000, 'error', 'perturb_zeropoint_by_curve_order'))
tests.append((perturb(mk_ecpairing_data([(G1_zero, G2)]), 0, fm),
              GPB + GPP + 30000, 'error', 'perturb_zeropoint_by_field_modulus'))
tests.append((perturb(mk_ecpairing_data(
    [(G1_zero, G2)]), 64, 1), GPB + GPP + 30000, 'error', 'perturb_g2_by_one'))
tests.append((perturb(mk_ecpairing_data(
    [(G1_zero, G2)]), 96, co), GPB + GPP + 30000, 'error', 'perturb_g2_by_curve_order'))
tests.append((perturb(mk_ecpairing_data(
    [(G1_zero, G2)]), 128, fm), GPB + GPP + 30000, 'error', 'perturb_g2_by_field_modulus'))
tests.append((perturb(mk_ecpairing_data([(G1_zero, G2)]), 160, fm),
              GPB + GPP + 30000, 'error', 'perturb_g2_by_field_modulus_again'))

testout = {}
testout_filler = {}

for encoded, execgas, expect, desc in tests:
    print('testing', encoded, execgas, expect, desc)
    o1, o2 = mk_test(encoded, execgas, expect)
    testout["ecpairing_" + desc] = o1
    o2["explanation"] = "Puts the given data into the ECPAIRING precompile"
    testout_filler["ecpairing_" + desc] = o2
open('ecpairing_tests.json', 'w').write(json.dumps(testout, indent=4))
open(
    'ecpairing_tests_filler.json',
    'w').write(
        json.dumps(
            testout_filler,
            indent=4))
