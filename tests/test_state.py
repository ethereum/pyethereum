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
    configure_logging(':trace')
else:
    sys.argv.remove('--notrace')


# SETUP TESTS IN GLOBAL NAME SPACE
def gen_func(filename, testname, testdata):
    return lambda: do_test_state(filename, testname, testdata)


def do_test_state(filename, testname=None, testdata=None, limit=99999999):
    logger.debug('running test:%r in %r' % (testname, filename))
    testutils.check_state_test(testdata)


if __name__ == '__main__':
    if len(sys.argv) == 1:
        # read fixture from stdin
        fixtures = {'stdin': json.load(sys.stdin)}
    else:
        # load fixtures from specified file or dir
        fixtures = testutils.get_tests_from_file_or_dir(sys.argv[1])
    for filename, tests in fixtures.items():
        for testname, testdata in tests.items():
            if len(sys.argv) < 3 or testname == sys.argv[2]:
                print "Testing: %s %s" % (filename, testname)
                testutils.check_state_test(testdata)
else:
    fixtures = testutils.get_tests_from_file_or_dir(
        os.path.join('fixtures', 'StateTests'))
    for filename, tests in fixtures.items():
        if 'stQuadraticComplexityTest.json' in filename or \
                'stMemoryStressTest.json' in filename:
            continue
        for testname, testdata in tests.items():
            func_name = 'test_%s_%s' % (filename, testname)
            globals()[func_name] = gen_func(filename, testname, testdata)
