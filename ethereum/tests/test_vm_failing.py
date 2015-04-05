import json
import os
import sys
import ethereum.testutils as testutils
from ethereum.slogging import get_logger, configure_logging
logger = get_logger()
# customize VM log output to your needs
# hint: use 'py.test' with the '-s' option to dump logs to the console


def do_test_vm(filename, testname=None, testdata=None, limit=99999999):
    logger.debug('running test:%r in %r' % (testname, filename))
    testutils.check_vm_test(testutils.fixture_to_bytes(testdata))


failing = [
    'vmSystemOperationsTest.json_ABAcallsSuicide1',
    'vmSystemOperationsTest.json_ABAcalls0',
    'vmSystemOperationsTest.json_ABAcallsSuicide0',
    'vmSystemOperationsTest.json_callcodeToReturn1',
    'vmEnvironmentalInfoTest.json_env1',
    'vmSystemOperationsTest.json_createNameRegistrator',
    'vmSystemOperationsTest.json_CallRecursiveBomb0',
    'vmSystemOperationsTest.json_CallToReturn1',
    'vmSystemOperationsTest.json_CallToPrecompiledContract',
    'vmSystemOperationsTest.json_CallToNameRegistrator0',
    'vmSystemOperationsTest.json_callcodeToNameRegistrator0'
]
failing = [x.split('_', 1)[-1] for x in failing]  # testnames


fixtures = testutils.get_tests_from_file_or_dir(
    os.path.join(testutils.fixture_path, 'VMTests'))


def mk_test_func(filename, testname, testdata):
    return lambda: do_test_vm(filename, testname, testdata)


for filename, tests in list(fixtures.items()):
    for testname, testdata in list(tests.items()):
        func_name = 'test_%s_%s' % (filename, testname)
        if testname not in failing:
            continue
        globals()[func_name] = mk_test_func(filename, testname, testdata)
