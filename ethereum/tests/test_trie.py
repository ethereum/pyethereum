import json
import ethereum.trie as trie
import ethereum.db as db
import itertools
from ethereum.slogging import get_logger, configure_logging
from rlp.utils import decode_hex, encode_hex
from ethereum.abi import is_string
from ethereum.testutils import fixture_to_bytes
logger = get_logger()

# customize VM log output to your needs
# hint: use 'py.test' with the '-s' option to dump logs to the console
configure_logging(':trace')


def check_testdata(data_keys, expected_keys):
    assert set(data_keys) == set(expected_keys), \
        "test data changed, please adjust tests"


def load_tests():
    try:
        fixture = json.load(open('fixtures/TrieTests/trietest.json', 'r'))
    except IOError:
        raise IOError("Could not read trietests.json from fixtures",
                      "Make sure you did 'git submodule init'")
    expected_keys = set(['jeff', 'emptyValues', 'branchingTests'])
    assert set(fixture.keys()) == expected_keys, ("test data changed!", list(fixture.keys()))
    return fixture_to_bytes(fixture)


def run_test(name):

    logger.debug('testing %s' % name)
    pairs = load_tests()[name]

    def _dec(x):
        if is_string(x) and x.startswith(b'0x'):
            return decode_hex(x[2:])
        return x

    pairs['in'] = [(_dec(k), _dec(v)) for k, v in pairs['in']]
    deletes = [(k, v) for k, v in pairs['in'] if v is None]

    N_PERMUTATIONS = 1000
    for i, permut in enumerate(itertools.permutations(pairs['in'])):
        if i > N_PERMUTATIONS:
            break
        t = trie.Trie(db.EphemDB())
        for k, v in permut:
            #logger.debug('updating with (%s, %s)' %(k, v))
            if v is not None:
                t.update(k, v)
            else:
                t.delete(k)
        # make sure we have deletes at the end
        for k, v in deletes:
            t.delete(k)
        assert pairs['root'] == b'0x' + encode_hex(t.root_hash), (i, list(permut) + deletes)


def test_emptyValues():
    run_test('emptyValues')


def test_jeff():
    run_test('jeff')
