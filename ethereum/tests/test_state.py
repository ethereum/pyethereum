import json
import sys
import ethereum.testutils as testutils
import ethereum.new_statetest_utils as new_statetest_utils

from ethereum.slogging import get_logger, configure_logging
logger = get_logger()
# customize VM log output to your needs
# hint: use 'py.test' with the '-s' option to dump logs to the console
if '--trace' in sys.argv:  # not default
    configure_logging(':trace')
    sys.argv.remove('--trace')

if '--old' in sys.argv:  # not default
    checker = lambda x: testutils.check_state_test(testutils.fixture_to_bytes(x))
    place_to_check = 'StateTests'
    sys.argv.remove('--old')
else:
    checker = new_statetest_utils.verify_state_test
    place_to_check = 'GeneralStateTests'


def test_state(filename, testname, testdata):
    logger.debug('running test:%r in %r' % (testname, filename))
    checker(testdata)


def pytest_generate_tests(metafunc):
    testutils.generate_test_params(
        place_to_check,
        metafunc,
        exclude_func=lambda filename, _, __: (
            'stQuadraticComplexityTest' in filename or
            'stMemoryStressTest' in filename or
            'stMemoryTest' in filename or
            'CALLCODE_Bounds3.json' in filename or
            'stPreCompiledContractsTransaction.json' in filename or
            'MLOAD_Bounds.json' in filename
        )
    )


def main():
    global fixtures, filename, tests, testname, testdata
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
                checker(testdata)


if __name__ == '__main__':
    main()
