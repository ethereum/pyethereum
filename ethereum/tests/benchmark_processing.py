from ethereum import parse_genesis_declaration, db
from ethereum.block import Block
from ethereum.config import Env
from ethereum import chain
from ethereum import state_transition
import rlp
import json
import os
import sys
import time

# from ethereum.slogging import LogRecorder, configure_logging, set_level
# config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace,eth.pb.msg:trace,eth.pb.tx:debug'
# configure_logging(config_string=config_string)

if 'saved_state.json' in os.listdir(os.getcwd()):
    print 'loading state from saved_state.json ...'
    c = chain.Chain(json.load(open('saved_state.json')), Env())
    print 'loaded.'
elif 'genesis_frontier.json' not in os.listdir(os.getcwd()):
    print 'Please download genesis_frontier.json from http://vitalik.ca/files/genesis_frontier.json'
    sys.exit()
else:
    c = chain.Chain(json.load(open('genesis_frontier.json')), Env())
    assert c.state.trie.root_hash.encode('hex') == 'd7f8974fb5ac78d9ac099b9ad5018bedc2ce0a72dad1827a1709da30580f0544'
    assert c.state.prev_headers[0].hash.encode('hex') == 'd4e56740f876aef8c010b86a40d5f56745a118d0906a34e69aec8c0db1cb8fa3'
    print 'state generated from genesis'
if '200kblocks.rlp' not in os.listdir(os.getcwd()):
    print 'Please download 200kblocks.rlp from http://vitalik.ca/files/200kblocks.rlp and put it in this directory to continue the test'
    sys.exit()

batch_size = 1024 * 10240 # approximately 10000 blocks
f = open('1700kblocks.rlp')

# skip already processed blocks
skip = c.state.block_number + 1
count = 0
block_rlps = f.readlines(batch_size)
while len(block_rlps) > 0:
    if len(block_rlps) + count <= skip:
        count += len(block_rlps)
        block_rlps = f.readlines(batch_size)
    else:
        block_rlps = block_rlps[skip-count:]
        count = skip
        break
print "skipped %d processed blocks" % skip

include_db_commit = os.environ.get('INCLUDE_DB_COMMIT', '0') == '1'
if not include_db_commit:
    def commit(self):
        pass
    setattr(c.env.db.__class__, 'commit', commit)

validate_receipt_root = os.environ.get('VALIDATE_RECEIPT_ROOT', '0') == '1'
if not validate_receipt_root:
    def validate_receipt_root(block, receipts):
        return True
    state_transition.validate_receipt_root = validate_receipt_root

processed_blocks = 0
processed_txs = 0
processed_gas = 0
t = time.time()

while len(block_rlps) > 0:
    for block in block_rlps:
        # print 'prevh:', s.prev_headers
        block = rlp.decode(block.strip().decode('hex'), Block)
        assert c.add_block(block)

        processed_blocks += 1
        processed_txs += len(block.transactions)
        processed_gas += block.gas_used
        elapsed = time.time() - t
        print "%s >>> processed %d blocks, %d txs, %d gas, avg. %.2fbps, %.2ftps %.2fgps" % \
            (elapsed,
             processed_blocks, processed_txs, processed_gas,
             processed_blocks/elapsed, processed_txs/elapsed, processed_gas/elapsed)
    block_rlps = f.readlines(batch_size)

