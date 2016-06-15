import os
import sys
import ethereum.testutils as testutils
import cProfile
import pstats
import time
from rlp.utils import encode_hex
from ethereum.utils import sha3, to_string
from ethereum.slogging import get_logger
logger = get_logger()


if sys.version_info.major == 2:
    from io import BytesIO as StringIO
else:
    from io import StringIO


def do_test_vm(filename, testname=None, testdata=None, limit=99999999, profiler=None):
    logger.debug('running test:%r in %r' % (testname, filename))
    testutils.run_vm_test(testutils.fixture_to_bytes(testdata), testutils.VERIFY, profiler=profiler)

if __name__ == '__main__':
    num = 5000
    print('profile_vm.py [no_cprofile]')
    print('loading tests')
    fixtures = testutils.get_tests_from_file_or_dir(
        os.path.join(testutils.fixture_path, 'VMTests'))

    def run(profiler=None):
        print('running')
        i = 0
        seen = b''
        for filename, tests in fixtures.items():
            for testname, testdata in tests.items():
                if i == num:
                    break
                do_test_vm(filename, testname, testdata, profiler=profiler)
                seen += to_string(testname)
                i += 1
        print('ran %d tests' % i)
        print('test key', encode_hex(sha3(seen)))

    if len(sys.argv) == 1:
        pr = cProfile.Profile()
        run(pr)
        s = StringIO()
        sortby = 'tottime'
        ps = pstats.Stats(pr, stream=s).sort_stats(sortby)
        ps.print_stats(50)
        print(s.getvalue())
    else:
        # pypy version
        st = time.time()
        run()
        print('took total', time.time() - st)
        try:  # pypy branch
            from ethereum.utils import sha3_call_counter
            print('took w/o sha3', time.time() - st - sha3_call_counter[3])
        except ImportError:
            pass
