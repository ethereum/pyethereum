import os
import ethereum.testutils as testutils
import ethereum.utils as utils
from ethereum.slogging import get_logger
import ethereum.keys as keys
logger = get_logger()


# SETUP TESTS IN GLOBAL NAME SPACE
def gen_func(filename, testname, testdata):
    return lambda: do_test_key(filename, testname, testdata)


def do_test_key(filename, testname=None, testdata=None, limit=99999999):
    logger.debug('running test:%r in %r' % (testname, filename))
    assert keys.check_keystore_json(testdata["json"])
    privkey = keys.decode_keystore_json(testdata["json"], testdata["password"])
    assert utils.encode_hex(privkey) == utils.to_string(testdata["priv"])

fixtures = testutils.get_tests_from_file_or_dir(
    os.path.join(testutils.fixture_path, 'KeyStoreTests'))

filenames = sorted(list(fixtures.keys()))
for filename in filenames:
    tests = fixtures[filename]
    for testname, testdata in list(tests.items()):
        func_name = 'test_%s_%s' % (filename, testname)
        globals()[func_name] = gen_func(filename, testname, testdata)
