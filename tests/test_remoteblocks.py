from pyethereum import blocks
from pyethereum import rlp
from test_chain import set_db, get_chainmanager
from remoteblocksdata import data_poc5v23_1, data_poc5v23_2
import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()




def do_test(hex_rlp_encoded_data):
	set_db()
	chain_manager = get_chainmanager()
	data = rlp.decode(hex_rlp_encoded_data.decode('hex'))
	transient_blocks = [blocks.TransientBlock(rlp.encode(b)) for b in data]
	chain_manager.receive_chain(transient_blocks)



def test_import_local_cpp_chain_blk_5_tx():
	# simple transaction
	do_test(data_poc5v23_2)

def test_import_remote_chain_blk_11_contract():
	# contract creation
	do_test(data_poc5v23_1)
