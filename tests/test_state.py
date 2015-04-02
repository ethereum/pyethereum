import json
import os
import sys
import pytest
import pyethereum.testutils as testutils

from pyethereum.slogging import get_logger, configure_logging
logger = get_logger()
# customize VM log output to your needs
# hint: use 'py.test' with the '-s' option to dump logs to the console
if '--notrace' not in sys.argv:
    pass  #configure_logging(':trace')
else:
    sys.argv.remove('--notrace')


# SETUP TESTS IN GLOBAL NAME SPACE
def gen_func(filename, testname, testdata):
    return lambda: do_test_state(filename, testname, testdata)


def do_test_state(filename, testname=None, testdata=None, limit=99999999):
    logger.debug('running test:%r in %r' % (testname, filename))
    testutils.check_state_test(testutils.fixture_to_bytes(testdata))


if __name__ == '__main__':
    if len(sys.argv) == 1:
        # read fixture from stdin
        fixtures = {'stdin': json.load(sys.stdin)}
    else:
        # load fixtures from specified file or dir
        try:
            fixtures = testutils.get_tests_from_file_or_dir(sys.argv[1])
        except:
            fixtures = {'stdin': json.loads(sys.argv[1])}
    for filename, tests in list(fixtures.items()):
        for testname, testdata in list(tests.items()):
            if len(sys.argv) < 3 or testname == sys.argv[2]:
                print("Testing: %s %s" % (filename, testname))
                testutils.check_state_test(testdata)
else:
    fixtures = testutils.get_tests_from_file_or_dir(
        os.path.join('fixtures', 'StateTests'))

    # TODO: tests fail if not in correct order
    filenames = sorted(list(fixtures.keys()))
    filenames.reverse()
    for filename in filenames:
        tests = fixtures[filename]
        if 'stQuadraticComplexityTest.json' in filename or \
                'stMemoryStressTest.json' in filename:
            continue
        testnames = sorted(list(tests.keys()))
        for testname in testnames:
            testdata = tests[testname]
            func_name = 'test_%s_%s' % (filename, testname)
            globals()[func_name] = gen_func(filename, testname, testdata)
