import ethereum.transactions as transactions
import ethereum.utils as utils
import rlp
from ethereum.utils import decode_hex, encode_hex, str_to_bytes
from ethereum.tools import testutils
from ethereum.messages import config_fork_specific_validation, null_address
import ethereum.config as config
import sys
import json
import copy
konfig = copy.copy(config.default_config)
konfig['METROPOLIS_FORK_BLKNUM'] = 3000000

from ethereum.slogging import get_logger
logger = get_logger()
# customize VM log output to your needs
# hint: use 'py.test' with the '-s' option to dump logs to the console
# configure_logging(':trace')


def test_transaction(filename, testname, testdata):

    try:
        rlpdata = decode_hex(testdata["rlp"][2:])
        o = {}
        tx = rlp.decode(rlpdata, transactions.Transaction)
        blknum = int(testdata["blocknumber"])
        # if blknum >= config.default_config["HOMESTEAD_FORK_BLKNUM"]:
        #    tx.check_low_s_homestead()
        assert config_fork_specific_validation(konfig, blknum, tx)
        assert tx.startgas >= tx.intrinsic_gas_used
        if tx.sender == null_address:
            assert tx.value == 0 and tx.gasprice == 0 and tx.nonce == 0
        o["sender"] = tx.sender
        o["transaction"] = {
            "data": '0x' * (len(tx.data) > 0) + encode_hex(tx.data),
            "gasLimit": str(tx.startgas),
            "gasPrice": str(tx.gasprice),
            "nonce": str(tx.nonce),
            "r": '0x' + encode_hex(utils.zpad(utils.int_to_big_endian(tx.r), 32)),
            "s": '0x' + encode_hex(utils.zpad(utils.int_to_big_endian(tx.s), 32)),
            "v": str(tx.v),
            "value": str(tx.value),
            "to": encode_hex(tx.to),
        }
    except Exception as e:
        tx = None
        sys.stderr.write(str(e))
    if 'transaction' not in testdata:  # expected to fail
        # print(tx.to_dict(), testdata)
        assert tx is None
    else:
        assert set(
            o['transaction'].keys()) == set(
            testdata.get(
                "transaction",
                dict()).keys())
        o.get("transaction", None) == testdata.get("transaction", None)
        assert str_to_bytes(
            encode_hex(
                o.get(
                    "sender",
                    ''))) == str_to_bytes(
            testdata.get(
                "sender",
                ''))


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
