"""
patch to fetch write raw blocks to a file

create a file pyethereum/monkeypatch.py
and import tihis file

configure to connect to one peer, no mine

"""
print('IMPORTED BLOCKFETCHERPATCH')
fn = 'tests/raw_remote_blocks_hex.txt'


import pyethereum.config
import tempfile


def read_config(fn=None):
    print "Read config called"
    cfg = pyethereum.config.get_default_config()
    # set to 2 as, the bootsrapping server does not talk 'eth'
    cfg.set('network', 'num_peers', '1')
    #cfg.set('network', 'remote_host', '77.101.50.246')
    cfg.set('misc', 'data_dir', tempfile.mktemp())
    cfg.set('misc', 'mining', '0')
    return cfg

pyethereum.config.read_config = read_config

##############
import sys

from operator import attrgetter
from pyethereum.peer import idec
from pyethereum.packeter import packeter
import pyethereum.chainmanager as chainmanager
import pyethereum.utils as utils
import pyethereum.blocks as blocks
import pyethereum.rlp as rlp
import pyethereum.peer as peer

MIN_BLOCKS = 2
NUM_BLOCKS_PER_REQUEST = 200

fh = open(fn, 'w')
peer.Peer.blk_counter = 0
peer.Peer.blk_requested = set()

collected_blocks = []
peer.Peer.lowest_block = None


def _recv_Blocks(self, data):
    print("RECEIVED BLOCKS", len(data))
    if len(data) < MIN_BLOCKS:
        return
    assert blocks.TransientBlock(rlp.encode(data[0])).number >= blocks.TransientBlock(
        rlp.encode(data[-1])).number
    for x in data:
        enc = rlp.encode(x)
        tb = blocks.TransientBlock(enc)
        print tb
        self.blk_counter += 1
        if self.lowest_block is None:
            self.lowest_block = tb.number
        else:
            if self.lowest_block - 1 == tb.number:
                self.lowest_block = tb.number
            else:  # i.e. newly mined block sent
                return
        if tb not in collected_blocks:
            collected_blocks.append(tb)
        # exit if we are at the genesis
        if tb.number == 1:
            print 'done'
            for tb in sorted(collected_blocks, key=attrgetter('number')):
                print 'writing', tb
                fh.write(tb.rlpdata.encode('hex') + '\n')  # LOG line
            sys.exit(0)
    # fetch more
    print("ASKING FOR MORE HASHES", tb.hash.encode('hex'), tb.number)
    self.send_GetBlockHashes(tb.hash, NUM_BLOCKS_PER_REQUEST)

peer.Peer._recv_Blocks = _recv_Blocks

old_status = peer.Peer._recv_Status


def _recv_Status(self, data):
    #old_status(self, data)
    h = blocks.genesis().hash
    print('Status RECEIVED')
    head_hash = data[3]
    print "head_hash", head_hash.encode('hex')
    print "head difficulty", idec(data[2])
    assert not len(collected_blocks)
    self.send_GetBlockHashes(head_hash, NUM_BLOCKS_PER_REQUEST)


peer.Peer._recv_Status = _recv_Status


def _recv_BlockHashes(self, data):
    print("RECEIVED BLOCKHASHES", len(data))  # youngest to oldest
    # print [x.encode('hex') for x in data]
    block_hashes = data  # youngest to oldest
    self.send_GetBlocks(block_hashes)

peer.Peer._recv_BlockHashes = _recv_BlockHashes


def mine(self):
    pass

chainmanager.ChainManager.mine = mine
