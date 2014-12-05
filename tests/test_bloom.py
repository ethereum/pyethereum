import pytest
import json
import pyethereum.processblock as pb
import pyethereum.utils as utils
import pyethereum.bloom as bloom
import os
import sys

import logging
logging.basicConfig(level=logging.DEBUG, format='%(message)s')
logger = logging.getLogger()
pblogger = pb.pblogger


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
    filenames = os.listdir(os.path.join('fixtures', 'VMTests'))
    files = [os.path.join('fixtures', 'VMTests', f) for f in filenames]
    vm_fixtures = {}
    try:
        for f, fn in zip(files, filenames):
            if f[-5:] == '.json':
                vm_fixtures[fn[:-5]] = json.load(open(f, 'r'))
    except IOError, e:
        raise IOError("Could not read vmtests.json from fixtures",
                      "Make sure you did 'git submodule init'")
    return vm_fixtures


# SETUP TESTS IN GLOBAL NAME SPACE
def gen_func(testdata):
    return lambda: do_test_bloom(testdata)

for filename, tests in vm_tests_fixtures().items():
    for testname, testdata in tests.items():
        if 'logs' not in testdata or 'log' not in testname.lower():
            continue
        func_name = 'test_%s_%s' % (filename, testname)
        globals()[func_name] = gen_func(testdata['logs'])



def decode_int_from_hex(x):
    r = utils.decode_int(x.decode('hex').lstrip("\x00"))
    return r

def encode_hex_from_int(x):
    return utils.zpad(utils.int_to_big_endian(x), 64).encode('hex')


def do_test_bloom(test_logs):
    """
    The logs sections is a mapping between the blooms and their corresponding logentries.
    Each logentry has the format:
    address: The address of the logentry.
    data: The data of the logentry.
    topics: The topics of the logentry, given as an array of values.
    """

    for test_bloom, data in test_logs.items():
#        print "TEST", dict(bloom=data)
#        print "test bits", bloom.bits_in_number(decode_int_from_hex(test_bloom))
        address = data['address']
        # Test via bloom
        b = bloom.bloom_insert(0, address.decode('hex'))
        for t in data['topics']:
            b = bloom.bloom_insert(b, t.decode('hex'))
#       print "manual bits", bloom.bits_in_number(b)
        assert test_bloom == encode_hex_from_int(b)
        # Test via Log
        topics = [decode_int_from_hex(x) for x in data['topics']]
        log = pb.Log(address, topics, '')
        #print "LOG", log.to_dict()
        log_bloom = bloom.b64(bloom.bloom_from_list(log.bloomables()))
#        print "log bits", bloom.bits_in_number(utils.decode_int(utils.zunpad(log_bloom)))
        assert log_bloom.encode('hex') == encode_hex_from_int(b)
        assert test_bloom == log_bloom.encode('hex')


def test_addressX():
    logs = {'00000000000000000000800000000000000000000000000000000880000000000000000000000000000000000000000000000000000000000000000000000000': 
    {u'topics': [], u'data': u'0x', u'address': u'0f572e5295c57f15886f9b263e2f6d2d6c7b5ec6'}}
    do_test_bloom(logs)

def test_address_dataX():
    logs = {
    "00000000000000000000800000000000000000000000000000000880000000000000000000000000000000000000000000000000000000000000000000000000" : {
    "address" : "0f572e5295c57f15886f9b263e2f6d2d6c7b5ec6",
    "data" : "0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
    "topics" : []}}
    do_test_bloom(logs)

def test_address_data_topicX():
    logs = {
    "00000000000008000000808100000000000000000000000000000880000000000000000000000000000000000000000000000000000000000000000000000000" : {
    "address" : "0f572e5295c57f15886f9b263e2f6d2d6c7b5ec6",
    "data" : "0xff00000000000000000000000000000000000000000000000000000000000000",
    "topics" : ["000000000000000000000000cd1722f3947def4cf144679da39c4c32bdc35681"]
    }}
    do_test_bloom(logs)

def test_address_all0topicX():
    logs = {"00000000000000000000800000000000000000000000000000000880000020000000000002000000000000000000080000000000000000000000000000000000" : {
    "address" : "0f572e5295c57f15886f9b263e2f6d2d6c7b5ec6",
    "data" : "0x",
    "topics" : ["0000000000000000000000000000000000000000000000000000000000000000"]
    }}
    do_test_bloom(logs)


def test_simple_bloom():
    val = '0f572e5295c57f15886f9b263e2f6d2d6c7b5ec6'
    expectedR = '00000000000000000000000000000000000000000000000000000000000000000000000002200000000000000000000000000000000200000000000000000000' 
    expected = '00000000000000000000800000000000000000000000000000000880000000000000000000000000000000000000000000000000000000000000000000000000'
    a = val.decode('hex')
    r = encode_hex_from_int(bloom.bloom(a))
    print 'expected', expected
    print 'bloom', r
    assert len(r) == len(expected)
    assert r == expected





