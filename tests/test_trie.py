
import pytest
import json
import tempfile
import pyethereum.trie as trie

import logging
logging.basicConfig(level=logging.DEBUG, format='%(message)s')
logger = logging.getLogger()




def check_testdata(data_keys, expected_keys):
    assert set(data_keys) == set(expected_keys), \
        "test data changed, please adjust tests"


def load_tests():
    try:
        fixture = json.load(open('fixtures/TrieTests/trietest.json', 'r'))
    except IOError:
        raise IOError("Could not read trietests.json from fixtures",
            "Make sure you did 'git submodule init'")
    expected_keys = set([u'jeff', u'emptyValues'])
    assert set(fixture.keys()) == expected_keys, ("test data changed!", fixture.keys())
    return fixture


def run_test(name):

    logger.debug('testing %s', name)
    t = trie.Trie(tempfile.mktemp())
    pairs = load_tests()[name]

    def _dec(x):
        if isinstance(x, (str, unicode)) and x.startswith('0x'):
            return x[2:].decode('hex')
        return x

    for k, v in pairs['in']:
        k, v = _dec(k), _dec(v)
        logger.debug('updating with (%s, %s)', k, v)
        if v is not None:
            t.update(k, v)
        else:
            t.delete(k)
    assert pairs['root'] == '0x'+t.root_hash.encode('hex')


def test_emptyValues():
    run_test('emptyValues')

def test_jeff():
    run_test('jeff')
