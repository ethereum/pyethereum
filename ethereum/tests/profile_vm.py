import json
import os
import sys
import ethereum.testutils as testutils
import cProfile
import pstats
import StringIO
import time
from ethereum.utils import sha3_call_counter, sha3
from ethereum.slogging import get_logger, configure_logging, get_configuration
logger = get_logger()
import sys


def do_test_vm(filename, testname=None, testdata=None, limit=99999999, profiler=None):
    logger.debug('running test:%r in %r' % (testname, filename))
    testutils.run_vm_test(testutils.fixture_to_bytes(testdata), testutils.VERIFY, profiler=profiler)

if __name__ == '__main__':
    num = 5000
    print 'loading tests'
    fixtures = testutils.get_tests_from_file_or_dir(
        os.path.join(testutils.fixture_path, 'VMTests'))

    def run(profiler=None):
        print 'running'
        i = 0
        seen = b''
        for filename, tests in fixtures.items():
            for testname, testdata in tests.items():
                if i == num:
                    break
                do_test_vm(filename, testname, testdata, profiler=profiler)
                seen += str(testname)
                i += 1
        print 'ran %d tests' % i
        print 'test key', sha3(seen).encode('hex')

    if len(sys.argv) == 2:
        pr = cProfile.Profile()
        run(pr)
        s = StringIO.StringIO()
        sortby = 'tottime'
        ps = pstats.Stats(pr, stream=s).sort_stats(sortby)
        ps.print_stats(50)
        print s.getvalue()
    else:
        st = time.time()
        run()
        print
        print 'took total', time.time() - st
        print 'took w/o sha3', time.time() - st - sha3_call_counter[3]
