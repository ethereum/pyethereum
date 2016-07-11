import json
import sys
import ethereum.testutils as testutils

from ethereum.slogging import get_logger, configure_logging
logger = get_logger()
# customize VM log output to your needs
# hint: use 'py.test' with the '-s' option to dump logs to the console
if '--trace' in sys.argv:  # not default
    configure_logging(':trace')
    sys.argv.remove('--trace')


def test_state(filename, testname, testdata):
    logger.debug('running test:%r in %r' % (testname, filename))
    testutils.check_state_test(testutils.fixture_to_bytes(testdata))


def pytest_generate_tests(metafunc):
    testutils.generate_test_params(
        'StateTests',
        metafunc,
        lambda filename, _, __: (
            'stQuadraticComplexityTest.json' in filename or
            'stMemoryStressTest.json' in filename or
            'stPreCompiledContractsTransaction.json' in filename
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
                testutils.check_state_test(testdata)


if __name__ == '__main__':
    main()
