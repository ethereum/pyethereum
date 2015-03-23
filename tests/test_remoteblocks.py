from pyethereum import blocks
from pyethereum import processblock
import rlp
from rlp.utils import decode_hex, encode_hex
from pyethereum import transactions
from pyethereum.config import get_default_config
from pyethereum.db import DB
import pyethereum.utils as utils
import logging
import pytest
import tempfile
from tests.utils import new_chainmanager
from pyethereum.slogging import get_logger, configure_logging
import sys
logger = get_logger()
# customize VM log output to your needs
# hint: use 'py.test' with the '-s' option to dump logs to the console
configure_logging(':trace')


def import_chain_data(raw_blocks_fn, test_db_path, skip=0):
    db = DB(test_db_path)
    chain_manager = utils.get_chainmanager(db, blocks.genesis(db))

    fh = open(raw_blocks_fn)
    for i in range(skip):
        fh.readline()
    tot = sum([int(y["balance"]) for x, y in
               list(chain_manager.head.to_dict(True)["state"].items())])

    safe = {x: y["balance"] for x, y in 
            list(chain_manager.head.to_dict(True)["state"].items())}
    for hex_rlp_encoded_data in fh:
        hexdata = decode_hex(hex_rlp_encoded_data.strip())
        blk = blocks.TransientBlock(hexdata)
        print(blk.number, encode_hex(blk.hash), \
            '%d txs' % len(blk.transaction_list))
        head = chain_manager.head
        assert blocks.check_header_pow(blk.header_args)
        chain_manager.receive_chain([blk])
        newhead = chain_manager.head
        newtot = sum([int(y["balance"]) for x, y in
                      list(newhead.to_dict(True)["state"].items())])
        if newtot != tot + newhead.ether_delta:
            raise Exception("Ether balance sum mismatch: %d %d" %
                            (newtot, tot + newhead.ether_delta))
        for tx in blk.get_transactions():
            safe[tx.sender] = max(safe.get(tx.sender, 0) - tx.value, 0)
        tot = newtot
        if blk.hash not in chain_manager:
            print('block could not be added')
            assert head == chain_manager.head
            chain_manager.head.deserialize_child(blk.rlpdata)
            assert blk.hash in chain_manager
        print(safe)

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("usage:%s <raw_blocks_fn> <db_path> <skip>" % sys.argv[0])
        sys.exit(1)
    raw_blocks_fn = sys.argv[1]
    test_db_path = sys.argv[2]
    skip = int(sys.argv[3])
    import_chain_data(raw_blocks_fn, test_db_path, skip)
