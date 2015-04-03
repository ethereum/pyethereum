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
from pyethereum import testutils
import sys
logger = get_logger()
# customize VM log output to your needs
# hint: use 'py.test' with the '-s' option to dump logs to the console
configure_logging(':trace')


def import_chain_data(raw_blocks_fn, test_db_path, skip=0):
    db = DB(test_db_path)
    blks = testutils.get_blocks_from_textdump(
        open(raw_blocks_fn).read().strip())
    testutils.test_chain_data(blks, db, skip)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage:%s <raw_blocks_fn> <db_path> <skip?> <formt?>"
              % sys.argv[0])
        sys.exit(1)
    raw_blocks_fn = sys.argv[1]
    test_db_path = sys.argv[2]
    skip = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    formt = sys.argv[4] if len(sys.argv) > 4 else 'lines'
    import_chain_data(raw_blocks_fn, test_db_path, skip)
