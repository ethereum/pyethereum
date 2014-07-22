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
        fixture = json.load(open('fixtures/trietestnextprev.json', 'r'))
    except IOError:
        raise IOError("Could not read trietests.json from fixtures",
                      "Make sure you did 'git submodule init'")
    return fixture


def run_test(name):

    logger.debug('testing %s', name)
    t = trie.Trie(tempfile.mktemp())
    data = load_tests()[name]

    for k in data['in']:
        logger.debug('updating with (%s, %s)', k, k)
        t.update(k, k)
    for point, prev, nxt in data['tests']:
        assert nxt == (t.next(point) or '')
        assert prev == (t.prev(point) or '')


def test_basic():
    run_test('basic')
