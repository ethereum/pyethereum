from pyethereum import blocks
from pyethereum import rlp
from test_chain import set_db, get_chainmanager
from remoteblocksdata import data_poc5v23_1
import logging
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
	for b in transient_blocks:
		print b
	chain_manager.receive_chain(transient_blocks)
	print chain_manager.head


def test_import_remote_chain_blk_128_contract():
	# contract creation
	# error in blk #119
	#do_test(data_poc5v23_1)
	do_test(load_raw())
