import pytest
import pyethereum.processblock as processblock
import pyethereum.opcodes as opcodes
import pyethereum.blocks as blocks
import pyethereum.transactions as transactions
import pyethereum.utils as utils
import rlp
from rlp.utils import decode_hex, encode_hex, str_to_bytes
import pyethereum.testutils as testutils
from pyethereum.testutils import fixture_to_bytes
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
    testdata = fixture_to_bytes(testdata)
    rlpdata = decode_hex(testdata["rlp"][2:])
    o = {}
    tx = rlp.decode(rlpdata, transactions.Transaction)
    o["sender"] = tx.sender
    o["transaction"] = {
        "data": b'0x' * (len(tx.data) > 0) + encode_hex(tx.data),
        "gasLimit": str_to_bytes(str(tx.startgas)),
        "gasPrice": str_to_bytes(str(tx.gasprice)),
        "nonce": str_to_bytes(str(tx.nonce)),
        "r": b'0x'+encode_hex(utils.zpad(utils.int_to_big_endian(tx.r), 32)),
        "s": b'0x'+encode_hex(utils.zpad(utils.int_to_big_endian(tx.s), 32)),
        "v": str_to_bytes(str(tx.v)),
        "value": str_to_bytes(str(tx.value)),
        "to": encode_hex(tx.to),
    }
    assert o.get("transaction", None) == testdata.get("transaction", None)
    assert encode_hex(o.get("sender", None)) == testdata.get("sender", None)


if __name__ == '__main__':
    if len(sys.argv) == 1:
        # read fixture from stdin
        fixtures = {'stdin': json.load(sys.stdin)}
    else:
        # load fixtures from specified file or dir
        fixtures = testutils.get_tests_from_file_or_dir(sys.argv[1])
    for filename, tests in list(fixtures.items()):
        for testname, testdata in list(tests.items()):
            if len(sys.argv) < 3 or testname == sys.argv[2]:
                print("Testing: %s %s" % (filename, testname))
                testutils.check_state_test(testdata)
else:
    fixtures = testutils.get_tests_from_file_or_dir(
        os.path.join('fixtures', 'TransactionTests'))
    for filename, tests in list(fixtures.items()):
        if 'stQuadraticComplexityTest.json' in filename or \
                'stMemoryStressTest.json' in filename:
            continue
        for testname, testdata in list(tests.items()):
            func_name = 'test_%s_%s' % (filename, testname)
            globals()[func_name] = lambda: run_test(filename, testname, testdata)

