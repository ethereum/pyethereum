import pytest
import json
import tempfile
import pyethereum.trie as trie

import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()



def check_testdata(data_keys, expected_keys):
    assert set(data_keys) == set(expected_keys), \
        "test data changed, please adjust tests"


def load_tests():
    try:
        fixture = json.load(open('fixtures/trietest.json', 'r'))
    except IOError:
        raise IOError("Could not read trietests.json from fixtures",
            "Make sure you did 'git submodule init'")
    #logger.debug(fixture.keys())
    expected_keys = [u'foo', u'emptyValues', u'jeff', u'testy', u'singleItem',
                     u'hex', u'smallValues', u'puppy', u'dogs']
    assert fixture.keys() == expected_keys, "test data changed!"
    return fixture


def run_test(name):

    logger.debug('testing %s', name)
    t = trie.Trie(tempfile.mktemp())
    pairs = load_tests()[name]

    for k, v in pairs['in'].items():
        if k[:2] == '0x':
            k = k[2:].decode('hex')
        if v[:2] == '0x':
            v = v[2:].decode('hex')
        logger.debug('updating with (%s, %s)', k, v)
        t.update(k, v)
    assert pairs['root'] == t.root_hash.encode('hex')


def test_foo():
    run_test('foo')

def test_emptyValues():
    run_test('emptyValues')

def test_jeff():
    run_test('jeff')

def test_testy():
    run_test('testy')

def test_singleItem():
    run_test('singleItem')

def test_hex():
    run_test('hex')

def test_smallValues():
    run_test('smallValues')

def test_puppy():
    run_test('puppy')

def test_dogs():
    run_test('dogs')





