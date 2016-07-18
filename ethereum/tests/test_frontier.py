from ethereum import parse_genesis_declaration, db
from ethereum.block import Block, BlockHeader
from ethereum.config import Env
import ethereum.state_transition as state_transition
from ethereum import chain
import rlp
import json
import os
import sys
import time

# from ethereum.slogging import LogRecorder, configure_logging, set_level
# config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace,eth.pb.msg:trace,eth.pb.tx:debug'
# configure_logging(config_string=config_string)

state_transition.SKIP_MEDSTATES = False
state_transition.SKIP_RECEIPT_ROOT_VALIDATION = False
assert not state_transition.SKIP_MEDSTATES or state_transition.SKIP_RECEIPT_ROOT_VALIDATION

STATE_STORE_FN = 'saved_state.json'
STATE_SNAPSHOT_FN = 'saved_snapshot_{}k.json'

if STATE_STORE_FN in os.listdir(os.getcwd()):
    print 'loading state from saved_state.json ...'
    c = chain.Chain(json.load(open(STATE_STORE_FN)), Env())
    print 'loaded.'
elif 'genesis_frontier.json' not in os.listdir(os.getcwd()):
    print 'Please download genesis_frontier.json from' + \
        'http://vitalik.ca/files/genesis_frontier.json'
    sys.exit()
else:
    c = chain.Chain(json.load(open('genesis_frontier.json')), Env())
    assert c.state.trie.root_hash.encode('hex') == \
        'd7f8974fb5ac78d9ac099b9ad5018bedc2ce0a72dad1827a1709da30580f0544'
    assert c.state.prev_headers[0].hash.encode('hex') == \
        'd4e56740f876aef8c010b86a40d5f56745a118d0906a34e69aec8c0db1cb8fa3'
    print 'state generated from genesis'
if '200kblocks.rlp' not in os.listdir(os.getcwd()):
    print 'Please download 200kblocks.rlp from http://vitalik.ca/files/200kblocks.rlp' + \
          'and put it in this directory to continue the test'
    sys.exit()

batch_size = 1024 * 10240  # approximately 10000 blocks
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
        block_rlps = block_rlps[skip - count:]
        count = skip
        break
print "skipped %d processed blocks" % skip


def check_snapshot_consistency(snapshot, env=None):
    if env:
        c = chain.Chain(env=env)
    else:
        c = chain.Chain(snapshot, Env())
    snapshot2 = c.state.to_snapshot()
    if snapshot != snapshot2:  # FIXME
        for i, ss in enumerate([snapshot, snapshot2]):
            fn = '/tmp/{}_{}'.format(STATE_STORE_FN, i)
            open(fn, 'w').write(json.dumps(snapshot))
        raise Exception("snapshot difference, see {}*".format(fn[:-1]))

REPORT_INTERVAL = 1000
SAVE_INTERVAL = 10 * 1000
SNAPSHOT_INTERVAL = 100 * 1000

MANUAL_SNAPSHOTS = [909330]

# don't check pow
BlockHeader.check_pow = lambda *args: True

# process blocks
while len(block_rlps) > 0:
    st = time.time()
    num_txs = 0
    gas_used = 0
    for block in block_rlps:
        # print 'prevh:', s.prev_headers
        block = rlp.decode(block.strip().decode('hex'), Block)
        assert c.add_block(block)
        num_txs += len(block.transactions)
        gas_used += block.gas_used
        num_blocks = block.header.number + 1
        if num_blocks % REPORT_INTERVAL == 0:
            # report
            elapsed = time.time() - st
            tps = num_txs / elapsed
            bps = REPORT_INTERVAL / elapsed
            gps = gas_used / elapsed
            print 'elapsed:%d bps:%d tps:%d gps:%d' % (elapsed, bps, tps, gps)
            st = time.time()
            num_txs = 0
            gas_used = 0
        if num_blocks % SAVE_INTERVAL == 0 or num_blocks in MANUAL_SNAPSHOTS:
            # snapshot
            print 'creating snapshot'
            snapshot = c.state.to_snapshot()
            if (num_blocks / SAVE_INTERVAL) % 2 == 1:
                check_snapshot_consistency(snapshot, env=None)
            else:
                check_snapshot_consistency(snapshot, env=c.env)
            # store checkpoint
            if num_blocks % SNAPSHOT_INTERVAL == 0:
                fn = STATE_SNAPSHOT_FN.format(num_blocks / 1000)
            elif num_blocks in MANUAL_SNAPSHOTS:
                fn = STATE_SNAPSHOT_FN.format(num_blocks)
            else:
                fn = STATE_STORE_FN
            open(fn, 'w').write(json.dumps(snapshot, indent=4))
            st = time.time()
    block_rlps = f.readlines(batch_size)

print 'Test successful'
