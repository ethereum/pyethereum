import pytest
import json
import ethereum.processblock as pb
import ethereum.utils as utils
import ethereum.testutils as testutils
import ethereum.bloom as bloom
import os
from rlp.utils import decode_hex, encode_hex, str_to_bytes


def check_testdata(data_keys, expected_keys):
    assert set(data_keys) == set(expected_keys), \
        "test data changed, please adjust tests"


@pytest.fixture(scope="module")
def vm_tests_fixtures():
    """
    Read vm tests from fixtures
    fixtures/VMTests/*
    """
    # FIXME: assert that repo is uptodate
    # cd fixtures; git pull origin develop; cd ..;  git commit fixtures
    filenames = os.listdir(os.path.join(testutils.fixture_path, 'VMTests'))
    files = [os.path.join(testutils.fixture_path, 'VMTests', f) for f in filenames]
    vm_fixtures = {}
    try:
        for f, fn in zip(files, filenames):
            if f[-5:] == '.json':
                vm_fixtures[fn[:-5]] = json.load(open(f, 'r'))
    except IOError as e:
        raise IOError("Could not read vmtests.json from fixtures",
                      "Make sure you did 'git submodule init'")
    return vm_fixtures


# SETUP TESTS IN GLOBAL NAME SPACE
def gen_func(testdata):
    return lambda: do_test_bloom(testdata)

for filename, tests in list(vm_tests_fixtures().items()):
    for testname, testdata in list(tests.items()):
        if 'logs' not in testdata or 'log' not in testname.lower():
            continue
        func_name = 'test_%s_%s' % (filename, testname)
        globals()[func_name] = gen_func(testdata['logs'])


def decode_int_from_hex(x):
    r = utils.decode_int(decode_hex(x).lstrip(b"\x00"))
    return r


def encode_hex_from_int(x):
    return encode_hex(utils.zpad(utils.int_to_big_endian(x), 256))


def do_test_bloom(test_logs):
    """
    The logs sections is a mapping between the blooms and their corresponding logentries.
    Each logentry has the format:
    address: The address of the logentry.
    data: The data of the logentry.
    topics: The topics of the logentry, given as an array of values.
    """
    for data in test_logs:
        address = data['address']
        # Test via bloom
        b = bloom.bloom_insert(0, decode_hex(address))
        for t in data['topics']:
            b = bloom.bloom_insert(b, decode_hex(t))
        # Test via Log
        topics = [decode_int_from_hex(x) for x in data['topics']]
        log = pb.Log(decode_hex(address), topics, '')
        log_bloom = bloom.b64(bloom.bloom_from_list(log.bloomables()))
        assert encode_hex(log_bloom) == encode_hex_from_int(b)
        assert str_to_bytes(data['bloom']) == encode_hex(log_bloom)
