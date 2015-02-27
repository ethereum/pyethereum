import pytest, os, sys
import pyethereum.testutils as testutils

from pyethereum.slogging import get_logger, configure_logging
logger = get_logger()
# customize VM log output to your needs
# hint: use 'py.test' with the '-s' option to dump logs to the console
if '--notrace' not in sys.argv:
    configure_logging(':trace')


# SETUP TESTS IN GLOBAL NAME SPACE
def gen_func(filename, testname, testdata):
    return lambda: do_test_vm(filename, testname, testdata)


def do_test_vm(filename, testname=None, testdata=None, limit=99999999):
    logger.debug('running test:%r in %r' % (testname, filename))
    testutils.check_state_test(testdata)


if __name__ == '__main__':
    assert len(sys.argv) >= 2, "Please specify file or dir name"
    fixtures = testutils.get_tests_from_file_or_dir(sys.argv[1])
    for filename, tests in fixtures.items():
        for testname, testdata in tests.items():
            testutils.check_state_test(testdata)
else:
    fixtures = testutils.get_tests_from_file_or_dir(
        os.path.join('fixtures', 'StateTests'))
    for filename, tests in fixtures.items():
        for testname, testdata in tests.items():
            func_name = 'test_%s_%s' % (filename, testname)
            globals()[func_name] = gen_func(filename, testname, testdata)
