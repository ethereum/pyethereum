import logging
import time
import struct

logger = logging.getLogger(__name__)

def log_block(block):
	logger.info('log_block' + '0'*40)
	logger.info(block.to_dict())