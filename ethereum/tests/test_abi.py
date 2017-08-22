import os
import pytest
import ethereum.tools.testutils as testutils
from ethereum.slogging import get_logger
import ethereum.abi as abi
from ethereum.utils import zpad

logger = get_logger()


def test_abi_encode_var_sized_array():
    abi.encode_abi(['address[]'], [[b'\x00' * 20] * 3])


def test_abi_encode_fixed_size_array():
    abi.encode_abi(['uint16[2]'], [[5, 6]])


def test_abi_encode_signed_int():
    assert abi.decode_abi(['int8'], abi.encode_abi(['int8'], [1]))[0] == 1
    assert abi.decode_abi(['int8'], abi.encode_abi(['int8'], [-1]))[0] == -1


def test_abi_encode_single_int():
    assert abi.encode_single(['int', '256', []], -2 **
                             255) == (b'\x80' + b'\x00' * 31)
    assert abi.encode_single(
        ['int', '256', []], (b'\x80' + b'\x00' * 31)) == (b'\x80' + b'\x00' * 31)

    assert abi.encode_single(['int', '8', []], -128)[-1:] == b'\x80'
    with pytest.raises(abi.ValueOutOfBounds):
        assert abi.encode_single(['int', '8', []], -129)

    assert abi.encode_single(['int', '8', []], 127) == zpad(b'\x7f', 32)
    with pytest.raises(abi.ValueOutOfBounds):
        assert abi.encode_single(['int', '8', []], 128)


def test_abi_encode_single_ufixed():
    assert abi.encode_single(['ufixed', '128x128', []], 0) == (b'\x00' * 32)
    assert abi.encode_single(['ufixed', '128x128', []], 1.125) == (
        b'\x00' * 15 + b'\x01\x20' + b'\x00' * 15)
    assert abi.encode_single(['ufixed', '128x128', []], 2 **
                             127 - 1) == (b'\x7f' + b'\xff' * 15 + b'\x00' * 16)


def test_abi_encode_single_fixed():
    assert abi.encode_single(['fixed', '128x128', []], 1.125) == (
        b'\x00' * 15 + b'\x01\x20' + b'\x00' * 15)
    assert abi.encode_single(['fixed', '128x128', []], -
                             1.125) == (b'\xff' *
                                        15 +
                                        b'\xfe' +
                                        b'\xe0' +
                                        b'\x00' *
                                        15)


def test_abi_encode_single_hash():
    assert abi.encode_single(['hash', '8', []], b'\x00' * 8) == b'\x00' * 32
    assert abi.encode_single(['hash', '8', []], '00' * 8) == b'\x00' * 32


def test_abi_decode_single_hash():
    typ = ['hash', '8', []]
    assert b'\x01' * \
        8 == abi.decode_single(typ, abi.encode_single(typ, b'\x01' * 8))


def test_abi_decode_single_bytes():
    typ = ['bytes', '8', []]
    assert (
        b'\x01\x02' +
        b'\x00' *
        6) == abi.decode_single(
        typ,
        abi.encode_single(
            typ,
            b'\x01\x02'))

    typ = ['bytes', '', []]
    assert b'\x01\x02' == abi.decode_single(
        typ, abi.encode_single(typ, b'\x01\x02'))


def test_abi_encode_single_prefixed_address():
    prefixed_address = '0x' + '0' * 40
    assert abi.encode_single(
        ['address', '', []], prefixed_address) == b'\x00' * 32


def test_abi_decode_single_fixed():
    fixed_data = abi.encode_single(['fixed', '128x128', []], 1)
    assert abi.decode_single(['fixed', '128x128', []], fixed_data) == 1

    fixed_data = abi.encode_single(['fixed', '128x128', []], 2**127 - 1)
    assert abi.decode_single(['fixed', '128x128', []],
                             fixed_data) == (2**127 - 1) * 1.0

    fixed_data = abi.encode_single(['fixed', '128x128', []], -1)
    assert abi.decode_single(['fixed', '128x128', []], fixed_data) == -1

    fixed_data = abi.encode_single(['fixed', '128x128', []], -2**127)
    assert abi.decode_single(['fixed', '128x128', []], fixed_data) == -2**127


# Will be parametrized fron json fixtures
def test_state(filename, testname, testdata):
    print(testdata)
    testutils.check_abi_test(testdata)


def pytest_generate_tests(metafunc):
    testutils.generate_test_params('ABITests', metafunc)
