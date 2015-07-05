from ethereum import blocks, utils, db
from ethereum.exceptions import VerificationFailed, InvalidTransaction
import rlp
from rlp.utils import decode_hex, encode_hex, str_to_bytes
from rlp import DecodingError, DeserializationError
import os
import sys
import ethereum.testutils as testutils

from ethereum.slogging import get_logger
logger = get_logger()


def translate_keys(olddict, keymap, valueconv, deletes):
    o = {}
    for k in list(olddict.keys()):
        if k not in deletes:
            o[keymap.get(k, k)] = valueconv(k, olddict[k])
    return o


e = db._EphemDB()

translator_list = {
    "extra_data": "extraData",
    "gas_limit": "gasLimit",
    "gas_used": "gasUsed",
    "mixhash": "mixHash",
    "prevhash": "parentHash",
    "receipts_root": "receiptTrie",
    "tx_list_root": "transactionsTrie",
    "uncles_hash": "uncleHash",
    "gas_price": "gasPrice",
    "header": "blockHeader",
    "uncles": "uncleHeaders"
}


def valueconv(k, v):
    if k in ['r', 's']:
        return '0x' + encode_hex(utils.int_to_big_endian(v))
    return v


def run_block_test(params):
    b = blocks.genesis(e, params["pre"])
    gbh = params["genesisBlockHeader"]
    b.bloom = utils.scanners['int256b'](gbh["bloom"])
    b.timestamp = utils.scanners['int'](gbh["timestamp"])
    b.nonce = utils.scanners['bin'](gbh["nonce"])
    b.extra_data = utils.scanners['bin'](gbh["extraData"])
    b.gas_limit = utils.scanners['int'](gbh["gasLimit"])
    b.gas_used = utils.scanners['int'](gbh["gasUsed"])
    b.coinbase = utils.scanners['addr'](decode_hex(gbh["coinbase"]))
    b.difficulty = utils.parse_int_or_hex(gbh["difficulty"])
    b.prevhash = utils.scanners['bin'](gbh["parentHash"])
    b.mixhash = utils.scanners['bin'](gbh["mixHash"])
    assert b.receipts.root_hash == \
        utils.scanners['bin'](gbh["receiptTrie"])
    assert b.transactions.root_hash == \
        utils.scanners['bin'](gbh["transactionsTrie"])
    assert utils.sha3rlp(b.uncles) == \
        utils.scanners['bin'](gbh["uncleHash"])
    h = encode_hex(b.state.root_hash)
    if h != str_to_bytes(gbh["stateRoot"]):
        raise Exception("state root mismatch")
    if b.hash != utils.scanners['bin'](gbh["hash"]):
        raise Exception("header hash mismatch")
    assert b.header.check_pow()
    blockmap = {b.hash: b}
    for blk in params["blocks"]:
        if 'blockHeader' not in blk:
            try:
                rlpdata = decode_hex(blk["rlp"][2:])
                blkparent = rlp.decode(rlp.encode(rlp.decode(rlpdata)[0]), blocks.BlockHeader).prevhash
                b2 = rlp.decode(rlpdata, blocks.Block, parent=blockmap[blkparent], db=e)
                success = True
            except (ValueError, TypeError, AttributeError, VerificationFailed,
                    DecodingError, DeserializationError, InvalidTransaction, KeyError):
                success = False
            assert not success
        else:
            rlpdata = decode_hex(blk["rlp"][2:])
            blkparent = rlp.decode(rlp.encode(rlp.decode(rlpdata)[0]), blocks.BlockHeader).prevhash
            b2 = rlp.decode(rlpdata, blocks.Block, parent=blockmap[blkparent], db=e)
            blockmap[b2.hash] = b2
        # blkdict = b.to_dict(False, True, False, True)
        # assert blk["blockHeader"] == \
        #     translate_keys(blkdict["header"], translator_list, lambda y, x: x, [])
        # assert blk["transactions"] == \
        #     [translate_keys(t, translator_list, valueconv, ['hash'])
        #      for t in blkdict["transactions"]]
        # assert blk["uncleHeader"] == \
        #     [translate_keys(u, translator_list, lambda x: x, [])
        #      for u in blkdict["uncles"]]


def do_test_block(filename, testname=None, testdata=None, limit=99999999):
    logger.debug('running test:%r in %r' % (testname, filename))
    run_block_test(testdata)

excludes = ['walletReorganizeOwners']

if __name__ == '__main__':
    assert len(sys.argv) >= 2, "Please specify file or dir name"
    fixtures = testutils.get_tests_from_file_or_dir(sys.argv[1])
    if len(sys.argv) >= 3:
        for filename, tests in list(fixtures.items()):
            for testname, testdata in list(tests.items()):
                if testname == sys.argv[2]:
                    print("Testing: %s %s" % (filename, testname))
                    run_block_test(testdata)
    else:
        for filename, tests in list(fixtures.items()):
            for testname, testdata in list(tests.items()):
                print("Testing: %s %s" % (filename, testname))
                run_block_test(testdata)
else:
    fixtures = testutils.get_tests_from_file_or_dir(
        os.path.join(testutils.fixture_path, 'BlockchainTests'))

    def mk_test_func(filename, testname, testdata):
        return lambda: do_test_block(filename, testname, testdata)

    for filename, tests in list(fixtures.items()):
        for testname, testdata in list(tests.items())[:500]:
            func_name = 'test_%s_%s' % (filename, testname)
            if testname not in excludes:
                globals()[func_name] = mk_test_func(filename, testname, testdata)
