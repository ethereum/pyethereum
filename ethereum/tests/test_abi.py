import os
import ethereum.testutils as testutils
from ethereum.slogging import get_logger
import ethereum.abi as abi
logger = get_logger()


def test_abi_encode_var_sized_array():
    abi.encode_abi(['address[]'], [[b'\x00' * 20] * 3])


def test_abi_encode_fixed_size_array():
    abi.encode_abi(['uint16[2]'], [[5, 6]])


def test_abi_encode_signed_int():
    assert abi.decode_abi(['int8'], abi.encode_abi(['int8'], [1]))[0] == 1
    assert abi.decode_abi(['int8'], abi.encode_abi(['int8'], [-1]))[0] == -1


# Will be parametrized fron json fixtures
def test_state(filename, testname, testdata):
    testutils.check_abi_test(testutils.fixture_to_bytes(testdata))


def pytest_generate_tests(metafunc):
    testutils.generate_test_params('ABITests', metafunc)
