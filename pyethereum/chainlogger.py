import logging
import time
import struct

logger = logging.getLogger(__name__)
fh = logging.FileHandler('blocks.log')
fh.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(message)s')
fh.setFormatter(formatter)
# add the handlers to the logger
logger.addHandler(fh)

def log_block(block):
	logger.info('BLOCK:%r', block.to_dict())
	for tx in block.get_transactions():
		logger.info('TX:%r', tx.to_dict())
