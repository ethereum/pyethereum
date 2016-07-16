from ethereum import parse_genesis_declaration, db
from ethereum.block import Block
from ethereum.config import Env
from ethereum.state_transition import apply_block
from ethereum import chain
import rlp
import json
import os
import sys

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

# process blocks
while len(block_rlps) > 0:
    for block in block_rlps:
        # print 'prevh:', s.prev_headers
        block = rlp.decode(block.strip().decode('hex'), Block)
        assert c.add_block(block)
        if (block.header.number+1) % 10000 == 0:
            snapshot = c.state.to_snapshot()
            if (block.header.number+1) % 20000 == 0:
                c = chain.Chain(env=c.env)
            else:
                c = chain.Chain(snapshot, Env())
            snapshot2 = c.state.to_snapshot()
            if snapshot != snapshot2:
                open('/tmp/1', 'w').write(json.dumps(snapshot))
                open('/tmp/2', 'w').write(json.dumps(snapshot2))
                raise Exception("snapshot difference")
            open('saved_state.json', 'w').write(json.dumps(snapshot, indent=4))
    block_rlps = f.readlines(batch_size)

print 'Test successful'
