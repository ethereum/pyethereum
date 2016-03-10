import ethereum.transactions as transactions
import ethereum.utils as utils
import rlp
from rlp.utils import decode_hex, encode_hex, str_to_bytes
import ethereum.testutils as testutils
from ethereum.testutils import fixture_to_bytes
import ethereum.config as config
import sys
import json

from ethereum.slogging import get_logger
logger = get_logger()
# customize VM log output to your needs
# hint: use 'py.test' with the '-s' option to dump logs to the console
# configure_logging(':trace')

encode_hex('')


def test_transaction(filename, testname, testdata):
    testdata = fixture_to_bytes(testdata)

    try:
        rlpdata = decode_hex(testdata["rlp"][2:])
        o = {}
        tx = rlp.decode(rlpdata, transactions.Transaction)
        blknum = int(testdata["blocknumber"])
        if blknum >= config.default_config["HOMESTEAD_FORK_BLKNUM"]:
            tx.check_low_s()
        o["sender"] = tx.sender
        o["transaction"] = {
            "data": b'0x' * (len(tx.data) > 0) + encode_hex(tx.data),
            "gasLimit": str_to_bytes(str(tx.startgas)),
            "gasPrice": str_to_bytes(str(tx.gasprice)),
            "nonce": str_to_bytes(str(tx.nonce)),
            "r": b'0x' + encode_hex(utils.zpad(utils.int_to_big_endian(tx.r), 32)),
            "s": b'0x' + encode_hex(utils.zpad(utils.int_to_big_endian(tx.s), 32)),
            "v": str_to_bytes(str(tx.v)),
            "value": str_to_bytes(str(tx.value)),
            "to": encode_hex(tx.to),
        }
    except Exception, e:
        tx = None
        sys.stderr.write(str(e))
    if 'transaction' not in testdata:  # expected to fail
        assert tx is None
    else:
        assert set(o['transaction'].keys()) == set(testdata.get("transaction", dict()).keys())
        o.get("transaction", None) == testdata.get("transaction", None)
        assert encode_hex(o.get("sender", '')) == testdata.get("sender", '')


def pytest_generate_tests(metafunc):
    testutils.generate_test_params('TransactionTests', metafunc)


def main():
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
                # testutils.check_state_test(testdata)
                test_transaction(filename, testname, testdata)


if __name__ == '__main__':
    main()
