import pytest

from ethereum import utils, db
from ethereum.pow import chain
from ethereum.exceptions import VerificationFailed, InvalidTransaction, InvalidNonce
from ethereum.block import Block
from ethereum.config import Env
from ethereum.genesis_helpers import state_from_genesis_declaration
import rlp
from rlp.utils import decode_hex, encode_hex, str_to_bytes
from rlp import DecodingError, DeserializationError
import os
import sys
import ethereum.tools.testutils as testutils
import copy

from ethereum.slogging import get_logger, configure_logging
logger = get_logger()

if '--trace' in sys.argv:  # not default
    configure_logging(':trace')
    sys.argv.remove('--trace')

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


def run_block_test(params, config_overrides=None):
    if config_overrides is None:
        config_overrides = {}
    env = Env(db.EphemDB())
    genesis_decl = {}
    for param in ("bloom", "timestamp", "nonce", "extraData",
                  "gasLimit", "coinbase", "difficulty",
                  "parentHash", "mixHash", "gasUsed"):
        genesis_decl[param] = params["genesisBlockHeader"][param]
    genesis_decl["alloc"] = params["pre"]

    old_config = copy.deepcopy(env.config)
    for k, v in config_overrides.items():
        env.config[k] = v

    # print('overrides', config_overrides)
    s = state_from_genesis_declaration(genesis_decl, env, allow_empties=True)
    c = chain.Chain(genesis=s, localtime=2**99)
    # print('h', encode_hex(c.state.prev_headers[0].state_root))
    # print(c.state.to_dict())
    # print(params["pre"])
    assert c.state.env == env
    assert c.state.prev_headers[0].state_root == safe_decode(params["genesisBlockHeader"]["stateRoot"]), (encode_hex(c.state.prev_headers[0].state_root), params["genesisBlockHeader"]["stateRoot"])
    assert c.state.trie.root_hash == safe_decode(params["genesisBlockHeader"]["stateRoot"])
    assert c.state.prev_headers[0].hash == safe_decode(params["genesisBlockHeader"]["hash"])


    for blk in params["blocks"]:
        if 'blockHeader' not in blk:
            success = True
            try:
                rlpdata = safe_decode(blk["rlp"][2:])
                success = c.add_block(rlp.decode(rlpdata, Block))
            except (ValueError, TypeError, AttributeError, VerificationFailed,
                    DecodingError, DeserializationError, InvalidTransaction, 
                    InvalidNonce, KeyError) as e:
                success = False
            assert not success
        else:
            rlpdata = safe_decode(blk["rlp"][2:])
            assert c.add_block(rlp.decode(rlpdata, Block))
    env.config = old_config

def get_config_overrides(filename, testname):
    o = {}
    if 'TestNetwork' in filename:
        o['HOMESTEAD_FORK_BLKNUM'] = 5
        # o['DAO_FORK_BLKNUM'] = 8
        o['ANTI_DOS_FORK_BLKNUM'] = 10
        o['CLEARING_FORK_BLKNUM'] = 14
        o['METROPOLIS_FORK_BLKNUM'] = 16
    elif 'EIP150' in filename or 'EIP150' in testname:
        o['HOMESTEAD_FORK_BLKNUM'] = 0
        o['DAO_FORK_BLKNUM'] = 2**99
        o['ANTI_DOS_FORK_BLKNUM'] = 0
    elif 'Homestead' in filename or 'Homestead' in testname:
        o['HOMESTEAD_FORK_BLKNUM'] = 0
    elif 'EIP158' in testname:
        o['HOMESTEAD_FORK_BLKNUM'] = 0
        o['DAO_FORK_BLKNUM'] = 2**99
        o['ANTI_DOS_FORK_BLKNUM'] = 0
        o['CLEARING_FORK_BLKNUM'] = 0
    elif 'Metropolis' in testname:
        o['HOMESTEAD_FORK_BLKNUM'] = 0
        o['DAO_FORK_BLKNUM'] = 2**99
        o['ANTI_DOS_FORK_BLKNUM'] = 0
        o['CLEARING_FORK_BLKNUM'] = 0
        o['METROPOLIS_FORK_BLKNUM'] = 0
    if 'bcTheDaoTest' in filename:
        o['DAO_FORK_BLKNUM'] = 8
    return o


def test_block(filename, testname, testdata):
    run_block_test(testdata, get_config_overrides(filename, testname))


skips = {
    ('bcWalletTest.json', u'walletReorganizeOwners'),
    ('bl10251623GO.json', u'randomBlockTest'),
    ('bl201507071825GO.json', u'randomBlockTest'),
    ('call_OOG_additionalGasCosts2.json', 'call_OOG_additionalGasCosts2_d0g0v0_EIP158'),
}

def exclude(filename, testname, _):
    if 'MemoryStressTest' in filename or 'QuadraticComplexityTest' in filename:
        return True
    if 'Metropolis' in testname or 'Frontier' in testname or 'Homestead' in testname or 'EIP150' in testname:
        return True
    return False


def pytest_generate_tests(metafunc):
    testutils.generate_test_params(
        'BlockchainTests',
        metafunc,
        skip_func=lambda filename, testname, _: (filename.split('/')[-1], testname) in skips,
        exclude_func=exclude,
    )


def main():
    assert len(sys.argv) >= 2, "Please specify file or dir name"
    fixtures = testutils.get_tests_from_file_or_dir(sys.argv[1])
    if len(sys.argv) >= 3:
        for filename, tests in list(fixtures.items()):
            for testname, testdata in list(tests.items()):
                if testname == sys.argv[2]:
                    print("Testing: %s %s" % (filename, testname))
                    run_block_test(testdata, get_config_overrides(filename, testname))
    else:
        for filename, tests in list(fixtures.items()):
            for testname, testdata in list(tests.items()):
                if (filename.split('/')[-1], testname) not in skips:
                    print("Testing: %s %s" % (filename, testname))
                    run_block_test(testdata, get_config_overrides(filename, testname))


if __name__ == '__main__':
    main()
