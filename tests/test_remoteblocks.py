from pyethereum import blocks
from pyethereum import rlp
from test_chain import set_db, get_chainmanager
from remoteblocksdata import data_poc5v23_1
import logging
import pytest
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()


def load_raw():
    "rlp and hex encoded blocks in multiline file,"
    "each line is in wrong order, which is also expected by chainmanager"
    data = []
    for x in open('tests/raw_remote_blocks_hex.txt'):
        data.extend(reversed(rlp.decode(x.strip().decode('hex'))))
    return rlp.encode(list(reversed(data))).encode('hex')


def do_test(hex_rlp_encoded_data):
    set_db()
    chain_manager = get_chainmanager()
    data = rlp.decode(hex_rlp_encoded_data.decode('hex'))
    transient_blocks = [blocks.TransientBlock(rlp.encode(b)) for b in data]
    assert len(transient_blocks) == 128
    chain_manager.receive_chain(transient_blocks)
    print chain_manager.head


def test_import_remote_chain_blk_128_contract():
    # contract creation
    # error in blk #119
    # do_test(data_poc5v23_1)
    do_test(load_raw())


"""
run like this:
py.test -s -m profiled  tests/test_remoteblocks.py

-s reenables messages to stdout when run by py.test
"""

ACTIVATE_PROFILE_TEST = False
@pytest.mark.skipif(not ACTIVATE_PROFILE_TEST, reason='profiling needs to be activated')
@pytest.mark.profiled
def test_profiled():
    import cProfile
    import StringIO
    import pstats

    def do_cprofile(func):
        def profiled_func(*args, **kwargs):
            profile = cProfile.Profile()
            try:
                profile.enable()
                logger.setLevel(logging.CRITICAL) # don't profile logger
                result = func(*args, **kwargs)
                profile.disable()
                return result
            finally:
                s = StringIO.StringIO()
                ps = pstats.Stats(
                    profile, stream=s).sort_stats('time', 'cum')
                ps.print_stats()
                print s.getvalue()

        return profiled_func

    do_cprofile(test_import_remote_chain_blk_128_contract)()
