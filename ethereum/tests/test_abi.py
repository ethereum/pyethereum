import os
import pytest
import ethereum.testutils as testutils
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
    assert abi.encode_single(['int', '256', []], -2**255) == (b'\x80'+b'\x00'*31)

    assert abi.encode_single(['int', '8', []], -128) == zpad(b'\x80', 32)
    with pytest.raises(abi.ValueOutOfBounds):
        assert abi.encode_single(['int', '8', []], -129)

    assert abi.encode_single(['int', '8', []], 127) == zpad(b'\x7f', 32)
    with pytest.raises(abi.ValueOutOfBounds):
        assert abi.encode_single(['int', '8', []], 128)

def test_abi_encode_single_hash():
    assert abi.encode_single(['hash', '8', []], b'\x00'*8) == b'\x00'*32
    assert abi.encode_single(['hash', '8', []], '00'*8) == b'\x00'*32

def test_abi_decode_single_hash():
    typ = ['hash', '8', []]
    assert b'\x01'*8 == abi.decode_single(typ, abi.encode_single(typ, b'\x01'*8))

def test_abi_decode_single_bytes():
    typ = ['bytes', '8', []]
    assert (b'\x01\x02' + b'\x00'*6) == abi.decode_single(typ, abi.encode_single(typ, '\x01\x02'))

    typ = ['bytes', '', []]
    assert b'\x01\x02' == abi.decode_single(typ, abi.encode_single(typ, '\x01\x02'))

def test_abi_encode_single_prefixed_address():
    prefixed_address = '0x' + '0'*40
    assert abi.encode_single(['address', '', []], prefixed_address) == b'\x00' * 32

def test_abi_decode_single_real():
    real_data = abi.encode_single(['real', '128x128', []], 1)
    assert abi.decode_single(['real', '128x128', []], real_data) == 1

    real_data = abi.encode_single(['real', '128x128', []], 2**127-1)
    assert abi.decode_single(['real', '128x128', []], real_data) == (2**127-1)*1.0

    real_data = abi.encode_single(['real', '128x128', []], -1)
    assert abi.decode_single(['real', '128x128', []], real_data) == -1

    real_data = abi.encode_single(['real', '128x128', []], -2**127)
    assert abi.decode_single(['real', '128x128', []], real_data) == -2**127

# SETUP TESTS IN GLOBAL NAME SPACE
def gen_func(filename, testname, testdata):
    return lambda: do_test_state(filename, testname, testdata)

def do_test_state(filename, testname=None, testdata=None, limit=99999999):
    logger.debug('running test:%r in %r' % (testname, filename))
    testutils.check_abi_test(testutils.fixture_to_bytes(testdata))

fixtures = testutils.get_tests_from_file_or_dir(
    os.path.join(testutils.fixture_path, 'ABITests'))

filenames = sorted(list(fixtures.keys()))
for filename in filenames:
    tests = fixtures[filename]
    for testname, testdata in list(tests.items()):
        func_name = 'test_%s_%s' % (filename, testname)
        globals()[func_name] = gen_func(filename, testname, testdata)
