import json
import os
import sys
import pytest
from rlp.utils import str_to_bytes
import pyethereum.testutils as testutils
from pyethereum.slogging import get_logger, configure_logging
logger = get_logger()
# customize VM log output to your needs
# hint: use 'py.test' with the '-s' option to dump logs to the console
if '--notrace' not in sys.argv:
    configure_logging(':trace')
else:
    sys.argv.remove('--notrace')


def to_bytes(value):
    if isinstance(value, str):
        return str_to_bytes(value)
    elif isinstance(value, list):
        return [to_bytes(v) for v in value]
    elif isinstance(value, dict):
        ret = {}
        for k, v in list(value.items()):
            key = str_to_bytes(k) if len(k) == 40 and isinstance(k, str) else k
            ret[key] = to_bytes(v)
        return ret
    else:
        return value

def do_test_vm(filename, testname=None, testdata=None, limit=99999999):
    logger.debug('running test:%r in %r' % (testname, filename))
    testutils.check_vm_test(to_bytes(testdata))


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
                testutils.check_vm_test(testdata)
else:
    fixtures = testutils.get_tests_from_file_or_dir(
        os.path.join('fixtures', 'VMTests'))
    for filename, tests in list(fixtures.items()):
        for testname, testdata in list(tests.items())[:500]:
            func_name = 'test_%s_%s' % (filename, testname)
            globals()[func_name] = lambda: do_test_vm(filename, testname, testdata)

