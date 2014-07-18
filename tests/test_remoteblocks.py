from pyethereum import blocks
from pyethereum import rlp
from test_chain import set_db, get_chainmanager
from remoteblocksdata import data as hex_rlp_encoded_data
import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()

set_db()
chain_manager = get_chainmanager()

def test_import_chain():
	data = rlp.decode(hex_rlp_encoded_data.decode('hex'))
	transient_blocks = [blocks.TransientBlock(rlp.encode(b)) for b in data]
	chain_manager.receive_chain(transient_blocks)


