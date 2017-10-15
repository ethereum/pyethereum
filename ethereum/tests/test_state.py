import json
import sys
import ethereum.tools.new_statetest_utils as new_statetest_utils
import ethereum.tools.testutils as testutils

from ethereum.slogging import get_logger, configure_logging
logger = get_logger()
# customize VM log output to your needs
# hint: use 'py.test' with the '-s' option to dump logs to the console
if '--trace' in sys.argv:  # not default
    configure_logging(':trace')
    sys.argv.remove('--trace')

checker = new_statetest_utils.verify_state_test
place_to_check = 'GeneralStateTests'


def test_state(filename, testname, testdata):
    logger.debug('running test:%r in %r' % (testname, filename))
    try:
        checker(testdata)
    except new_statetest_utils.EnvNotFoundException:
        pass


def pytest_generate_tests(metafunc):
    testutils.generate_test_params(
        place_to_check,
        metafunc,
        exclude_func=lambda filename, _, __: (
            'stQuadraticComplexityTest' in filename or  # Takes too long
            'stMemoryStressTest' in filename or  # We run out of memory
            'MLOAD_Bounds.json' in filename or  # We run out of memory
            # we know how to pass: force address 3 to get deleted. TODO confer
            # with c++ best path foward.
            'failed_tx_xcf416c53' in filename or
            # we know how to pass: delete contract's code. Looks like c++
            # issue.
            'RevertDepthCreateAddressCollision.json' in filename or
            'pairingTest.json' in filename or  # definitely a c++ issue
            'createJS_ExampleContract' in filename  # definitely a c++ issue
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
        except BaseException:
            fixtures = {'stdin': json.loads(sys.argv[1])}
    for filename, tests in list(fixtures.items()):
        for testname, testdata in list(tests.items()):
            if len(sys.argv) < 3 or testname == sys.argv[2]:
                print("Testing: %s %s" % (filename, testname))
                # try:
                checker(testdata)
                # except new_statetest_utils.EnvNotFoundException:
                #     pass


if __name__ == '__main__':
    main()
