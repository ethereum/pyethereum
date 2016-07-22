# -*- coding: utf8 -*-
import pytest

from ethereum.utils import (
    big_endian_to_int, int_to_big_endian, decode_hex, encode_hex, rzpad, sha3, zpad,
)
from ethereum.abi import (
    _canonical_type, decode_abi, decode_single, decint, encode_abi,
    encode_single, event_id, normalize_name, method_id, ContractTranslator,
    EncodingError, ValueOutOfBounds,
)
import ethereum.testutils as testutils

# pylint: disable=invalid-name


def test_canonical_types():
    # https://github.com/ethereum/wiki/wiki/Ethereum-Contract-ABI#types
    assert _canonical_type('bool') == 'bool'
    assert _canonical_type('address') == 'address'

    assert _canonical_type('int') == 'int256'
    assert _canonical_type('uint') == 'uint256'
    assert _canonical_type('fixed') == 'fixed128x128'
    assert _canonical_type('ufixed') == 'ufixed128x128'

    assert _canonical_type('int[]') == 'int256[]'
    assert _canonical_type('uint[]') == 'uint256[]'
    assert _canonical_type('fixed[]') == 'fixed128x128[]'
    assert _canonical_type('ufixed[]') == 'ufixed128x128[]'

    assert _canonical_type('int[100]') == 'int256[100]'
    assert _canonical_type('uint[100]') == 'uint256[100]'
    assert _canonical_type('fixed[100]') == 'fixed128x128[100]'
    assert _canonical_type('ufixed[100]') == 'ufixed128x128[100]'


def test_function_selector():
    # https://github.com/ethereum/wiki/wiki/Ethereum-Contract-ABI#function-selector-and-argument-encoding
    baz_selector = big_endian_to_int(decode_hex('CDCD77C0'))
    bar_selector = big_endian_to_int(decode_hex('AB55044D'))
    sam_selector = big_endian_to_int(decode_hex('A5643BF2'))
    f_selector = big_endian_to_int(decode_hex('8BE65246'))

    assert big_endian_to_int(sha3('baz(uint32,bool)')[:4]) == baz_selector
    assert big_endian_to_int(sha3('bar(fixed128x128[2])')[:4]) == bar_selector
    assert big_endian_to_int(sha3('sam(bytes,bool,uint256[])')[:4]) == sam_selector
    assert big_endian_to_int(sha3('f(uint256,uint32[],bytes10,bytes)')[:4]) == f_selector

    assert method_id('baz', ['uint32', 'bool']) == baz_selector
    assert method_id('bar', ['fixed128x128[2]']) == bar_selector
    assert method_id('sam', ['bytes', 'bool', 'uint256[]']) == sam_selector
    assert method_id('f', ['uint256', 'uint32[]', 'bytes10', 'bytes']) == f_selector

    assert method_id('bar', ['fixed[2]']) == bar_selector
    assert method_id('sam', ['bytes', 'bool', 'uint[]']) == sam_selector
    assert method_id('f', ['uint', 'uint32[]', 'bytes10', 'bytes']) == f_selector


def test_event():
    event_abi = [{
        'name': 'Test',
        'anonymous': False,
        'inputs': [
            {'indexed': False, 'name': 'a', 'type': 'int256'},
            {'indexed': False, 'name': 'b', 'type': 'int256'},
        ],
        'type': 'event',
    }]

    contract_abi = ContractTranslator(event_abi)

    normalized_name = normalize_name('Test')
    encode_types = ['int256', 'int256']
    id_ = event_id(normalized_name, encode_types)

    topics = [id_]
    data = encode_abi(encode_types, [1, 2])

    result = contract_abi.decode_event(topics, data)

    assert result['_event_type'] == b'Test'
    assert result['a'] == 1
    assert result['b'] == 2


def test_decint():
    assert decint(True) == 1
    assert decint(False) == 0
    assert decint(None) == 0

    # unsigned upper boundary
    assert decint(2 ** 256 - 1, signed=False) == 2 ** 256 - 1
    assert decint(int_to_big_endian(2 ** 256 - 1), signed=False) == 2 ** 256 - 1

    with pytest.raises(EncodingError):
        decint(2 ** 256, signed=False)
        decint(int_to_big_endian(2 ** 256), signed=False)

    # unsigned lower boundary
    assert decint(0) == 0
    assert decint(int_to_big_endian(0)) == 0
    with pytest.raises(EncodingError):
        decint(-1, signed=False)
        decint(int_to_big_endian(-1), signed=False)

    # signed upper boundary
    assert decint(2 ** 255 - 1, signed=True) == 2 ** 255 - 1
    assert decint(int_to_big_endian(2 ** 255 - 1), signed=True) == 2 ** 255 - 1

    with pytest.raises(EncodingError):
        decint(2 ** 255, signed=True)
        decint(int_to_big_endian(2 ** 255), signed=True)

    # signed lower boundary
    assert decint(-2 ** 255, signed=True) == -2 ** 255
    # assert decint(int_to_big_endian(-2 ** 255), signed=True) == -2 ** 255
    with pytest.raises(EncodingError):
        decint(-2 ** 255 - 1, signed=True)
        # decint(int_to_big_endian(-2 ** 255 - 1), signed=True)


def test_encode_int():
    int8 = ('int', '8', [])
    int32 = ('int', '32', [])
    int256 = ('int', '256', [])

    int256_maximum = (
        b'\x7f\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff'
        b'\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff'
    )
    int256_minimum = (
        b'\x80\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
        b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
    )
    int256_128 = (
        b'\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff'
        b'\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\x80'
    )
    int256_2_to_31 = (
        b'\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff'
        b'\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\x80\x00\x00\x00'
    )
    int256_negative_one = (
        b'\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff'
        b'\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff'
    )

    assert encode_single(int256, int256_minimum) == int256_minimum

    assert encode_single(int8, 0) == zpad(b'\x00', 32)
    assert encode_single(int8, 2 ** 7 - 1) == zpad(b'\x7f', 32)
    assert encode_single(int8, -1) == zpad(b'\xff', 32)
    assert encode_single(int8, -2 ** 7) == zpad(b'\x80', 32)

    with pytest.raises(ValueOutOfBounds):
        encode_single(int8, 128)

    with pytest.raises(ValueOutOfBounds):
        encode_single(int8, -129)

    assert encode_single(int32, 0) == zpad(b'\x00', 32)
    assert encode_single(int32, 2 ** 7 - 1) == zpad(b'\x7f', 32)
    assert encode_single(int32, 2 ** 31 - 1) == zpad(b'\x7f\xff\xff\xff', 32)
    assert encode_single(int32, -1) == zpad(b'\xff\xff\xff\xff', 32)
    assert encode_single(int32, -2 ** 7) == zpad(b'\xff\xff\xff\x80', 32)
    assert encode_single(int32, -2 ** 31) == zpad(b'\x80\x00\x00\x00', 32)

    with pytest.raises(ValueOutOfBounds):
        encode_single(int32, 2 ** 32)

    with pytest.raises(ValueOutOfBounds):
        encode_single(int32, -(2 ** 32))

    assert encode_single(int256, 0) == zpad(b'\x00', 32)
    assert encode_single(int256, 2 ** 7 - 1) == zpad(b'\x7f', 32)
    assert encode_single(int256, 2 ** 31 - 1) == zpad(b'\x7f\xff\xff\xff', 32)
    assert encode_single(int256, 2 ** 255 - 1) == int256_maximum
    assert encode_single(int256, -1) == int256_negative_one
    assert encode_single(int256, -2 ** 7) == int256_128
    assert encode_single(int256, -2 ** 31) == int256_2_to_31
    assert encode_single(int256, -2 ** 255) == int256_minimum

    with pytest.raises(ValueOutOfBounds):
        encode_single(int256, 2 ** 256)

    with pytest.raises(ValueOutOfBounds):
        encode_single(int256, -(2 ** 256))


def test_encode_uint():
    uint8 = ('uint', '8', [])
    uint32 = ('uint', '32', [])
    uint256 = ('uint', '256', [])

    with pytest.raises(ValueOutOfBounds):
        encode_single(uint8, -1)

    with pytest.raises(ValueOutOfBounds):
        encode_single(uint32, -1)

    with pytest.raises(ValueOutOfBounds):
        encode_single(uint256, -1)

    assert encode_single(uint8, 0) == zpad(b'\x00', 32)
    assert encode_single(uint32, 0) == zpad(b'\x00', 32)
    assert encode_single(uint256, 0) == zpad(b'\x00', 32)

    assert encode_single(uint8, 1) == zpad(b'\x01', 32)
    assert encode_single(uint32, 1) == zpad(b'\x01', 32)
    assert encode_single(uint256, 1) == zpad(b'\x01', 32)

    assert encode_single(uint8, 2 ** 8 - 1) == zpad(b'\xff', 32)
    assert encode_single(uint32, 2 ** 8 - 1) == zpad(b'\xff', 32)
    assert encode_single(uint256, 2 ** 8 - 1) == zpad(b'\xff', 32)

    assert encode_single(uint32, 2 ** 32 - 1) == zpad(b'\xff\xff\xff\xff', 32)
    assert encode_single(uint256, 2 ** 32 - 1) == zpad(b'\xff\xff\xff\xff', 32)

    uint256_maximum = (
        b'\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff'
        b'\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff'
    )
    assert encode_single(uint256, 2 ** 256 - 1) == uint256_maximum


def test_encode_bool():
    bool_ = ('bool', '', [])
    uint8 = ('uint', '8', [])

    assert encode_single(bool_, True) == zpad(b'\x01', 32)
    assert encode_single(bool_, False) == zpad(b'\x00', 32)

    assert encode_single(bool_, True) == encode_single(uint8, 1)
    assert encode_single(bool_, False) == encode_single(uint8, 0)


def test_encode_fixed():
    fixed128x128 = ('fixed', '128x128', [])

    _2_125 = decode_hex(
        b'00000000000000000000000000000002'
        b'20000000000000000000000000000000'
    )

    _8_5 = decode_hex(
        b'00000000000000000000000000000008'
        b'80000000000000000000000000000000'
    )

    assert encode_single(fixed128x128, 2.125) == _2_125
    assert encode_single(fixed128x128, 8.5) == _8_5

    assert encode_single(fixed128x128, 1.125) == (b'\x00' * 15 + b'\x01\x20' + b'\x00' * 15)
    assert encode_single(fixed128x128, -1.125) == (b'\xff' * 15 + b'\xfe' + b'\xe0' + b'\x00' * 15)

    with pytest.raises(ValueOutOfBounds):
        encode_single(fixed128x128, 2 ** 127)

    with pytest.raises(ValueOutOfBounds):
        encode_single(fixed128x128, -2 ** 127 - 1)


def test_encoded_ufixed():
    ufixed128x128 = ('ufixed', '128x128', [])

    _2_125 = decode_hex(
        b'00000000000000000000000000000002'
        b'20000000000000000000000000000000'
    )

    _8_5 = decode_hex(
        b'00000000000000000000000000000008'
        b'80000000000000000000000000000000'
    )

    assert encode_single(ufixed128x128, 2.125) == _2_125
    assert encode_single(ufixed128x128, 8.5) == _8_5

    assert encode_single(ufixed128x128, 0) == (b'\x00' * 32)
    assert encode_single(ufixed128x128, 1.125) == (b'\x00' * 15 + b'\x01\x20' + b'\x00' * 15)
    assert encode_single(ufixed128x128, 2**127 - 1) == (b'\x7f' + b'\xff' * 15 + b'\x00' * 16)

    with pytest.raises(ValueOutOfBounds):
        encode_single(ufixed128x128, 2 ** 128 + 1)

    with pytest.raises(ValueOutOfBounds):
        encode_single(ufixed128x128, -1)


def test_encode_dynamic_bytes():
    dynamic_bytes = ('bytes', '', [])
    uint256 = ('uint', '256', [])

    # only the size of the bytes
    assert encode_single(dynamic_bytes, b'') == zpad(b'\x00', 32)

    a = encode_single(uint256, 1) + rzpad(b'\x61', 32)
    assert encode_single(dynamic_bytes, b'\x61') == a

    dave_bin = decode_hex(
        b'0000000000000000000000000000000000000000000000000000000000000004'
        b'6461766500000000000000000000000000000000000000000000000000000000'
    )
    dave = encode_single(uint256, 4) + rzpad(b'\x64\x61\x76\x65', 32)
    assert encode_single(dynamic_bytes, b'\x64\x61\x76\x65') == dave_bin
    assert encode_single(dynamic_bytes, b'\x64\x61\x76\x65') == dave


def test_encode_dynamic_string():
    string = ('string', '', [])
    uint256 = ('uint', '256', [])

    a = u'ã'
    a_utf8 = a.encode('utf8')

    with pytest.raises(ValueError):
        encode_single(string, a.encode('latin'))

    a_encoded = encode_single(uint256, len(a_utf8)) + rzpad(a_utf8, 32)
    assert encode_single(string, a.encode('utf8')) == a_encoded


def test_encode_hash():
    hash8 = ('hash', '8', [])

    assert encode_single(hash8, b'\x00' * 8) == b'\x00' * 32
    assert encode_single(hash8, b'00' * 8) == b'\x00' * 32


def test_encode_address():
    prefixed_address = '0x' + '0' * 40
    assert encode_single(['address', '', []], prefixed_address) == b'\x00' * 32


def test_encode_decode_int():
    int8 = ('int', '8', [])
    int32 = ('int', '32', [])
    int256 = ('int', '256', [])

    int8_values = [
        1, -1,
        127, -128,
    ]
    int32_values = [
        1, -1,
        127, -128,
        2 ** 31 - 1, -2 ** 31,
    ]
    int256_values = [
        1, -1,
        127, -128,
        2 ** 31 - 1, -2 ** 31,
        2 ** 255 - 1, -2 ** 255,
    ]

    for value in int8_values:
        assert encode_abi(['int8'], [value]) == encode_single(int8, value)
        assert decode_abi(['int8'], encode_abi(['int8'], [value]))[0] == value

    for value in int32_values:
        assert encode_abi(['int32'], [value]) == encode_single(int32, value)
        assert decode_abi(['int32'], encode_abi(['int32'], [value]))[0] == value

    for value in int256_values:
        assert encode_abi(['int256'], [value]) == encode_single(int256, value)
        assert decode_abi(['int256'], encode_abi(['int256'], [value]))[0] == value


def test_encode_decode_bool():
    assert decode_abi(['bool'], encode_abi(['bool'], [True]))[0] is True
    assert decode_abi(['bool'], encode_abi(['bool'], [False]))[0] is False


def test_encode_decode_fixed():
    fixed128x128 = ('fixed', '128x128', [])

    fixed_data = encode_single(fixed128x128, 1)
    assert decode_single(fixed128x128, fixed_data) == 1

    fixed_data = encode_single(fixed128x128, 2**127 - 1)
    assert decode_single(fixed128x128, fixed_data) == (2**127 - 1) * 1.0

    fixed_data = encode_single(fixed128x128, -1)
    assert decode_single(fixed128x128, fixed_data) == -1

    fixed_data = encode_single(fixed128x128, -2**127)
    assert decode_single(fixed128x128, fixed_data) == -2**127


def test_encode_decode_bytes():
    bytes8 = ('bytes', '8', [])
    dynamic_bytes = ('bytes', '', [])

    assert decode_single(bytes8, encode_single(bytes8, b'\x01\x02')) == (b'\x01\x02' + b'\x00' * 6)
    assert decode_single(dynamic_bytes, encode_single(dynamic_bytes, b'\x01\x02')) == b'\x01\x02'


def test_encode_decode_hash():
    hash8 = ('hash', '8', [])

    hash1 = b'\x01' * 8
    assert hash1 == decode_single(hash8, encode_single(hash8, hash1))


def test_encode_decode_address():
    address1 = b'\x11' * 20
    address2 = b'\x22' * 20
    address3 = b'\x33' * 20

    all_addresses = [
        address1,
        address2,
        address3,
    ]
    all_addresses_encoded = [
        encode_hex(address1),
        encode_hex(address2),
        encode_hex(address3),
    ]

    assert decode_abi(['address'], encode_abi(['address'], [address1]))[0] == encode_hex(address1)

    addresses_encoded_together = encode_abi(['address[]'], [all_addresses])
    assert decode_abi(['address[]'], addresses_encoded_together)[0] == all_addresses_encoded

    address_abi = ['address', 'address', 'address']
    addreses_encoded_splited = encode_abi(address_abi, all_addresses)
    assert decode_abi(address_abi, addreses_encoded_splited) == all_addresses_encoded


def test_state(filename, testname, testdata):  # pylint: disable=unused-argument
    # test data generated by testutils.generate_test_params
    testutils.check_abi_test(testutils.fixture_to_bytes(testdata))


def pytest_generate_tests(metafunc):
    testutils.generate_test_params('ABITests', metafunc)
