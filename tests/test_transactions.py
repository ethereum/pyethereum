import pytest
import pyethereum.processblock as processblock
import pyethereum.opcodes as opcodes
import pyethereum.blocks as blocks
import pyethereum.transactions as transactions
import pyethereum.utils as utils
import rlp
import pyethereum.testutils as testutils
from tests.utils import new_db
import serpent
import sys
import json
import os

from pyethereum.slogging import get_logger, configure_logging
logger = get_logger()
# customize VM log output to your needs
# hint: use 'py.test' with the '-s' option to dump logs to the console
configure_logging(':trace')


def run_test(filename, testname, testdata):
    rlpdata = testdata["rlp"][2:].decode('hex')
    o = {}
    try:
        tx = transactions.Transaction.deserialize(rlpdata)
        o["sender"] = tx.sender
        o["transaction"] = {
            "data": '0x' * (len(tx.data) > 0) + tx.data.encode('hex'),
            "gasLimit": str(tx.startgas),
            "gasPrice": str(tx.gasprice),
            "nonce": str(tx.nonce),
            "r": '0x'+utils.zpad(utils.int_to_big_endian(tx.r), 32).encode('hex'),
            "s": '0x'+utils.zpad(utils.int_to_big_endian(tx.s), 32).encode('hex'),
            "v": str(tx.v),
            "value": str(tx.value),
            "to": str(tx.to),
        }
    except:
        pass
    assert o.get("transaction", None) == testdata.get("transaction", None)
    assert o.get("sender", None) == testdata.get("sender", None)


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
        os.path.join('fixtures', 'TransactionTests'))
    for filename, tests in fixtures.items():
        if 'stQuadraticComplexityTest.json' in filename or \
                'stMemoryStressTest.json' in filename:
            continue
        for testname, testdata in tests.items():
            func_name = 'test_%s_%s' % (filename, testname)
            globals()[func_name] = lambda: run_test(filename, testname, testdata)
