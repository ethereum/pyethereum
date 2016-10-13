import pytest

from ethereum import utils, db, chain
from ethereum.exceptions import VerificationFailed, InvalidTransaction, InvalidNonce
from ethereum.block import Block
from ethereum.config import Env
import rlp
from rlp.utils import decode_hex, encode_hex, str_to_bytes
from rlp import DecodingError, DeserializationError
import os
import sys
import ethereum.testutils as testutils
import copy

from ethereum.slogging import get_logger
logger = get_logger()

# from ethereum.slogging import LogRecorder, configure_logging, set_level
# config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace,eth.pb.msg:trace,eth.pb.tx:debug'
# configure_logging(config_string=config_string)


def translate_keys(olddict, keymap, valueconv, deletes):
    o = {}
    for k in list(olddict.keys()):
        if k not in deletes:
            o[keymap.get(k, k)] = valueconv(k, olddict[k])
    return o


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


def safe_decode(x):
    if x[:2] == '0x':
        x = x[2:]
    return decode_hex(x)


def run_block_test(params, config_overrides = {}):
    env = Env(db.EphemDB())
    genesis_decl = {}
    for param in ("bloom", "timestamp", "nonce", "extraData",
                  "gasLimit", "coinbase", "difficulty",
                  "parentHash", "mixHash", "gasUsed"):
        genesis_decl[param] = params["genesisBlockHeader"][param]
    genesis_decl["alloc"] = params["pre"]
    c = chain.Chain(genesis=genesis_decl, env=env)
    assert c.state.prev_headers[0].state_root == safe_decode(params["genesisBlockHeader"]["stateRoot"])
    assert c.state.trie.root_hash == safe_decode(params["genesisBlockHeader"]["stateRoot"])
    assert c.state.prev_headers[0].hash == safe_decode(params["genesisBlockHeader"]["hash"])


    old_config = copy.deepcopy(env.config)
    for k, v in config_overrides.items():
        env.config[k] = v


    for blk in params["blocks"]:
        if 'blockHeader' not in blk:
            success = True
            try:
                rlpdata = safe_decode(blk["rlp"][2:])
                success = c.add_block(rlp.decode(rlpdata, Block))
            except (ValueError, TypeError, AttributeError, VerificationFailed,
                    DecodingError, DeserializationError, InvalidTransaction, 
                    InvalidNonce, KeyError), e:
                success = False
            assert not success
        else:
            rlpdata = safe_decode(blk["rlp"][2:])
            assert c.add_block(rlp.decode(rlpdata, Block))
    env.config = old_config

def get_config_overrides(filename):
    o = {}
    if 'Homestead' in filename:
        o['HOMESTEAD_FORK_BLKNUM'] = 0
    if 'TestNetwork' in filename:
        o['HOMESTEAD_FORK_BLKNUM'] = 5
    if 'bcTheDaoTest' in filename:
        o['DAO_FORK_BLKNUM'] = 8
    if 'EIP150' in filename:
        o['HOMESTEAD_FORK_BLKNUM'] = 5
        o['DAO_FORK_BLKNUM'] = 8
        o['ANTI_DOS_FORK_BLKNUM'] = 10
    return o


def test_block(filename, testname, testdata):
    run_block_test(testdata, get_config_overrides(filename))


excludes = {
    ('bcWalletTest.json', u'walletReorganizeOwners'),
    ('bl10251623GO.json', u'randomBlockTest'),
    ('bl201507071825GO.json', u'randomBlockTest')
}


def pytest_generate_tests(metafunc):
    testutils.generate_test_params(
        'BlockchainTests',
        metafunc,
        lambda filename, testname, _: (filename.split('/')[-1], testname) in excludes
    )


def main():
    assert len(sys.argv) >= 2, "Please specify file or dir name"
    fixtures = testutils.get_tests_from_file_or_dir(sys.argv[1])
    if len(sys.argv) >= 3:
        for filename, tests in list(fixtures.items()):
            for testname, testdata in list(tests.items()):
                if testname == sys.argv[2]:
                    print("Testing: %s %s" % (filename, testname))
                    run_block_test(testdata, get_config_overrides(filename))
    else:
        for filename, tests in list(fixtures.items()):
            for testname, testdata in list(tests.items()):
                if (filename.split('/')[-1], testname) not in excludes:
                    print("Testing: %s %s" % (filename, testname))
                    run_block_test(testdata, get_config_overrides(filename))


if __name__ == '__main__':
    main()
