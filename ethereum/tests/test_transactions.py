from operator import attrgetter
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


def test_eip155_transaction():
    """Replicate the example from https://github.com/ethereum/eips/issues/155
    and ensure old style tx fails and new style transaction validates.
    """
    nonce = 9
    gasprice = 20 * 10 ** 9
    startgas = 21000
    to = "3535353535353535353535353535353535353535"
    value = 10 ** 18
    data = ''
    private_key = "4646464646464646464646464646464646464646464646464646464646464646"
    sender = utils.privtoaddr(private_key)
    old_style = transactions.Transaction(nonce, gasprice, startgas, to, value, data)
    new_style = transactions.EIP155Transaction(nonce, gasprice, startgas, to, value, data)

    new_signing_data = "ec098504a817c800825208943535353535353535353535353535353535353535880de0b6b3a764000080128080"

    new_signing_data_sedes = transactions.Transaction(
            new_style.nonce,
            new_style.gasprice,
            new_style.startgas,
            new_style.to,
            new_style.value,
            new_style.data,
            18,
            0,
            0
            )

    assert rlp.encode(new_signing_data_sedes, transactions.EIP155Transaction) == decode_hex(new_signing_data)

    new_signing_hash = "ac9813f00ec955e65a50cc778243f6c22dcfe9d64253462b16187f1c99e0a8fa"

    assert encode_hex(utils.sha3(rlp.encode(new_signing_data_sedes, transactions.Transaction))) == new_signing_hash

    new_v, new_r, new_s = (
            38,
            11616088462479929722209511590713166362238170772128436772837473395614974864269L,
            19832642777361886450959973766490059191918327598807281226090984148355472235004L
            )

    new_style_signed = "f86e098504a817c800825208943535353535353535353535353535353535353535880de0b6b3a7640000801ca1a019ae791bb8378a38bb83f5b930fe78a0320cec27d86e5e258c69f0fa9541eb8da1a02bd8e0c5bde4c0800238ce5a59d2f3ce723f1e84a62cab53d961fe3b019d19fc"
    new_deserialized = rlp.decode(decode_hex(new_style_signed), transactions.EIP155Transaction)

    old_style = old_style.sign(private_key)
    new_style = new_style.sign(private_key)

    assert not encode_hex(rlp.encode(old_style, transactions.Transaction)) == new_style_signed

    # Check roundtrip serialization
    roundtrip = rlp.decode(
            decode_hex(
                encode_hex(
                    rlp.encode(new_style, transactions.EIP155Transaction)
                    )
                ), transactions.EIP155Transaction)
    for field, _ in transactions.EIP155Transaction.fields:
        getter = attrgetter(field)
        assert getter(new_style) == getter(roundtrip), field

    # Check object values
    assert new_style.v == new_v
    assert new_style.r == new_r
    assert new_style.s == new_s

    # Check hex rlp against provided hex
    assert encode_hex(rlp.encode(new_style, transactions.EIP155Transaction)) == new_style_signed

    # Check against deserialized values
    assert new_deserialized.v == new_style.v
    assert new_deserialized.r == new_style.r
    assert new_deserialized.s == new_style.s

    # Test sender recovery
    assert old_style.sender == sender
    assert new_style.sender == sender
    assert new_deserialized.sender == sender

    # Check rlp against deserialized
    new_rlp = rlp.decode(rlp.encode(new_style, transactions.EIP155Transaction))
    deserialized_rlp = rlp.decode(decode_hex(new_style_signed))
    assert len(new_rlp) == len(deserialized_rlp)

    for num, assert_ in enumerate(
            [new_rlp[i] == deserialized_rlp[i] for i in range(len(new_rlp))]):
        assert assert_, (new_rlp[num], deserialized_rlp[num], num)

    # Check hex rlp against provided hex
    assert encode_hex(rlp.encode(new_style, transactions.EIP155Transaction)) == new_style_signed

    # TODO: test deserialize new style rlp fails with old_style Transaction class


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
    except Exception as e:
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
