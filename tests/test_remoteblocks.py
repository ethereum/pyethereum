from pyethereum import blocks
from pyethereum import processblock
from pyethereum import rlp
from pyethereum import transactions
from pyethereum.config import get_default_config
import pyethereum.utils as utils
import logging
import pytest
import tempfile
from tests.utils import new_chainmanager
from pyethereum.slogging import get_logger, configure_logging
logger = get_logger()
# customize VM log output to your needs
# hint: use 'py.test' with the '-s' option to dump logs to the console
configure_logging(':trace')

# xfail because data is old
@pytest.mark.xfail
def test_import_remote_chain():
    raw_blocks_fn = 'tests/raw_remote_blocks_hex.txt'
    test_db_path = tempfile.mktemp()
    import_chain_data(raw_blocks_fn, test_db_path, skip=0)


blk_poc7_v40_61 = "f902b1f90136a099b039ac72d1fed80181d3f958efffc38550f4100ef741bfee1b8923993b9c66a01dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d4934794b7576e9d314df41ec5506494293afb1bd5d3f65da0ff1f2960fe3368b902ba5dac65de8ae29d673e13bbb65e6f147b375959352932a0e6f326ebab7c730e64633e53d4581c2e5c3e5ec9ce42c80a18ddd10c4007e50ba0e92c6f6c5857b7c1f6c0f6597f8933f272bf2819696f3fff9e497ba84033db4db84000000000000008000000000000000000000000000000000202000000000000001000000000000000000000000000000000004000000000000000000000010000830212be3d8609184e72a000830e602482075684546253de80a0fe9b101ecab7ae3055136db13cd9f69264fe7ea4832beceff4f72b23a50ce6e9f90174f90171018609184e72a0008227109417fcb4420ffe7288db3dfb020d3b7ac7a8e20cd2880de0b6b3a7640000b901020000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000002000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000200000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000001ba065df6019dbfddf9e928a7f291c328231c4f365e797a68aab5ff5d16488884660a0c263a1d61767d0fd833e3548738668ade2da8a1f5796a995ba49409da1d5a698c0"

def dump_transactions(hex_rlp_encoded_data):
    "use py.test -s to get logs"
    blk = blocks.TransientBlock(hex_rlp_encoded_data.decode('hex'))
    for tx_lst_serialized in blk.transaction_list:
        tx = transactions.Transaction.create(tx_lst_serialized)
        #print tx.to_dict()

@pytest.mark.xfail
def test_dump_tx(data=blk_poc7_v40_61):
    return dump_transactions(data)

####### profiling
import cProfile
import StringIO
import pstats

def do_cprofile(func):
    def profiled_func(*args, **kwargs):
        profile = cProfile.Profile()
        try:
            configure_logging(':critical')
            profile.enable()
            result = func(*args, **kwargs)
            profile.disable()
            configure_logging(':trace')
            return result
        finally:
            s = StringIO.StringIO()
            ps = pstats.Stats(
                profile, stream=s).sort_stats('cum', 'time')
            ps.print_stats()
            print s.getvalue()

    return profiled_func


ACTIVATE_PROFILE_TEST = False
@pytest.mark.skipif(not ACTIVATE_PROFILE_TEST, reason='profiling needs to be activated')
@pytest.mark.profiled
def test_profiled():
    """
    run like this:
    py.test -s -m profiled  tests/test_remoteblocks.py

    -s reenables messages to stdout when run by py.test
    """
    do_cprofile(test_import_remote_chain_blk_128_contract)()


def import_chain_data(raw_blocks_fn, test_db_path, skip=0):
    chain_manager = new_chainmanager()
    
    fh = open(raw_blocks_fn)
    for i in range(skip):
        fh.readline()

    for hex_rlp_encoded_data in fh:
        hexdata = hex_rlp_encoded_data.strip().decode('hex')
        data = rlp.decode(hexdata)
        blk = blocks.TransientBlock(hexdata)
        print blk.number, blk.hash.encode('hex'), '%d txs' % len(blk.transaction_list)
        head = chain_manager.head
        assert blocks.check_header_pow(blk.header_args)
        chain_manager.receive_chain([blk])
        if not blk.hash in chain_manager:
            print 'block could not be added'
            assert head == chain_manager.head
            chain_manager.head.deserialize_child(blk.rlpdata)
            assert blk.hash in chain_manager

if __name__ == "__main__":
    """
    this can be run to import raw chain data to a certain db.

    python tests/test_remoteblocks.py rawdatafile testdbdir offset
    e.g.
    python tests/test_remoteblocks.py blocks.0-20k.p23.hexdata testdb 0

    make sure to rm -r the testdb

    data can be created with blockfetcherpatch.py
    """
    import sys
    if len(sys.argv) < 4:
        print "usage:%s <raw_blocks_fn> <db_path> <skip> [silent|profile]" % sys.argv[0]
        sys.exit(1)
    raw_blocks_fn = sys.argv[1]
    test_db_path = sys.argv[2]
    skip = int(sys.argv[3])

    if len(sys.argv) == 5 and sys.argv[4] == 'silent':
        logging.basicConfig(level=logging.INFO)
    if len(sys.argv) == 5 and sys.argv[4] == 'profile':
        logging.basicConfig(level=logging.INFO)
        do_cprofile(import_chain_data)(raw_blocks_fn, test_db_path, skip)
    else:
        import_chain_data(raw_blocks_fn, test_db_path, skip)




