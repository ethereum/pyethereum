from ethereum import genesis_helpers, db
from ethereum.block import Block, BlockHeader
from ethereum.config import Env
import ethereum.messages as messages
import ethereum.common as common
from pyethapp.leveldb_service import LevelDB
from ethereum.pow import chain
import rlp
import json
import os
import sys
import time
import random

from ethereum.slogging import LogRecorder, configure_logging, set_level
config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace,eth.pb.msg:trace,eth.pb.tx:debug'
# configure_logging(config_string=config_string)

messages.SKIP_MEDSTATES = True
common.SKIP_RECEIPT_ROOT_VALIDATION = True
# assert not state_transition.SKIP_MEDSTATES or state_transition.SKIP_RECEIPT_ROOT_VALIDATION

STATE_LOAD_FN = 'saved_state.json'
STATE_STORE_FN = 'saved_state.json'
STATE_SNAPSHOT_FN = 'saved_snapshot_{}k.json'

if '--saved_state' in sys.argv:
    STATE_LOAD_FN = sys.argv[sys.argv.index('--saved_state') + 1]

RLP_BLOCKS_FILE = '1700kblocks.rlp'

if '--rlp_blocks' in sys.argv:
    RLP_BLOCKS_FILE = sys.argv[sys.argv.index('--rlp_blocks') + 1]

BENCHMARK = 0
if '--benchmark' in sys.argv:
    BENCHMARK = int(sys.argv[sys.argv.index('--benchmark') + 1])

DB_DIR = '/tmp/%d' % random.randrange(int(time.time() * 1000000))
if '--db' in sys.argv:
    DB_DIR = int(sys.argv[sys.argv.index('--db') + 1])

_path, _file = os.path.split(STATE_LOAD_FN)
if _file in os.listdir(os.path.join(os.getcwd(), _path)):
    print('loading state from %s ...' % STATE_LOAD_FN)
    c = chain.Chain(json.load(open(STATE_LOAD_FN)), Env())
    print('loaded.')
elif 'genesis_frontier.json' not in os.listdir(os.getcwd()):
    print('Please download genesis_frontier.json from ' +
          'http://vitalik.ca/files/genesis_frontier.json')
    sys.exit()
else:
    c = chain.Chain(
        json.load(
            open('genesis_frontier.json')), Env(
            LevelDB(DB_DIR)))
    assert c.state.trie.root_hash.encode('hex') == \
        'd7f8974fb5ac78d9ac099b9ad5018bedc2ce0a72dad1827a1709da30580f0544'
    assert c.state.prev_headers[0].hash.encode('hex') == \
        'd4e56740f876aef8c010b86a40d5f56745a118d0906a34e69aec8c0db1cb8fa3'
    print('state generated from genesis')
print('Attempting to open %s' % RLP_BLOCKS_FILE)
_path, _file = os.path.split(RLP_BLOCKS_FILE)
if not _path or _file not in os.listdir(_path):
    print('Please download 200kblocks.rlp from http://vitalik.ca/files/200kblocks.rlp ' +
          'and put it in this directory to continue the test')
    sys.exit()

f = open(RLP_BLOCKS_FILE)

pos = 0
block_source_data = f.read()
block_rlps = []
while pos < len(block_source_data):
    _, l1, l2 = rlp.codec.consume_length_prefix(block_source_data, pos)
    block_rlps.append(block_source_data[pos: l1 + l2])
    pos = l1 + l2


def report(st, num_blks, num_txs, gas_used):
    now = time.time()
    elapsed = now - st
    tps = num_txs / elapsed
    bps = num_blks / elapsed
    gps = gas_used / elapsed
    print('%.2f >>> elapsed:%d blocks:%d txs:%d gas:%d bps:%d tps:%d gps:%d' %
          (now, elapsed, num_blks, num_txs, gas_used, bps, tps, gps))


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


def snapshot(c, num_blocks):
    print('creating snapshot')
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


REPORT_INTERVAL = 1000
SAVE_INTERVAL = 999999
SNAPSHOT_INTERVAL = 999999

# MANUAL_SNAPSHOTS = [68000, 68382, 68666, 69000, 909330]
MANUAL_SNAPSHOTS = []

# don't check pow
BlockHeader.check_pow = lambda *args: True

# print(block_rlps[116525].encode('hex'))
# sys.exit()

# process blocks
st = time.time()
num_blks = 0
num_txs = 0
gas_used = 0
for i, block in list(enumerate(block_rlps))[1:250000]:
    # print 'prevh:', s.prev_headers
    block = rlp.decode(block, Block)
    # if i == 116525:
    #    configure_logging(config_string=config_string)
    assert c.add_block(block)
    num_blks += 1
    num_txs += len(block.transactions)
    gas_used += block.gas_used
    if BENCHMARK > 0:
        report(st, num_blks, num_txs, gas_used)
        if num_blks == BENCHMARK:
            print("Benchmark completed (%d blocks)." % num_blks)
            sys.exit()
    else:
        num_blocks = block.header.number + 1
        if num_blocks % REPORT_INTERVAL == 0 or num_blocks in MANUAL_SNAPSHOTS:
            report(st, REPORT_INTERVAL, num_txs, gas_used)
            st = time.time()
            num_blks = 0
            num_txs = 0
            gas_used = 0
        if num_blocks % SAVE_INTERVAL == 0 or num_blocks in MANUAL_SNAPSHOTS:
            snapshot(c, num_blocks)
            st = time.time()
            num_blks = 0
            num_txs = 0
            gas_used = 0

print('Test successful')
