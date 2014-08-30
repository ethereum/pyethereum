"""
patch to fetch write raw blocks to a file

create a file pyethereum/monkeypatch.py
and import tihis file

configure to connect to one peer, no mine

"""
print('IMPORTED BLOCKFETCHERPATCH')
fn = 'blocks.1-1137.poc6.p28.hexdata'


NUM_BLOCKS_PER_REQUEST = 200

##############
import sys
from operator import attrgetter
from pyethereum.packeter import packeter
import pyethereum.chainmanager as chainmanager
import pyethereum.utils as utils
import pyethereum.blocks as blocks
import pyethereum.rlp as rlp
import pyethereum.peer as peer

assert chainmanager.NUM_BLOCKS_PER_REQUEST
chainmanager.NUM_BLOCKS_PER_REQUEST = NUM_BLOCKS_PER_REQUEST


fh = open(fn,'w')
peer.Peer.blk_counter = 0
peer.Peer.blk_requested = set()

collected_blocks = []
peer.Peer.lowest_block = None

def _recv_Blocks(self, data):
    print("RECEIVED BLOCKS", len(data)) # youngest (highest blk) to oldest (lowest blk)
    assert blocks.TransientBlock(rlp.encode(data[0])).number >= blocks.TransientBlock(rlp.encode(data[-1])).number
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
            else: # i.e. newly mined block sent
                return
        if tb not in collected_blocks:
            collected_blocks.append(tb)
        # exit if we are at the genesis
        if tb.number == 1:
            print 'done'
            for tb in sorted(collected_blocks, key=attrgetter('number')):
                print 'writing', tb
                fh.write(tb.rlpdata.encode('hex') + '\n') # LOG line
            sys.exit(0)
    # fetch more
    print("ASKING FOR MORE HASHES", tb.hash.encode('hex'), tb.number)
    self.send_GetBlockHashes(tb.hash, NUM_BLOCKS_PER_REQUEST)

peer.Peer._recv_Blocks = _recv_Blocks

old_hello = peer.Peer._recv_Hello
def _recv_Hello(self, data):
    old_hello(self, data)
    h = blocks.genesis().hash
    print('HELLO RECEIVED')
    head_hash = data[7]
    print "head_hash", head_hash.encode('hex')
    from peer import idec
    print "head difficulty", idec(data[6])
    #self.send_GetBlocks([head_hash])
    assert not len(collected_blocks)
    self.send_GetBlockHashes(head_hash, NUM_BLOCKS_PER_REQUEST)


peer.Peer._recv_Hello = _recv_Hello

def _recv_BlockHashes(self, data):
    print("RECEIVED BLOCKHASHES", len(data)) # youngest to oldest
    #print [x.encode('hex') for x in data]
    block_hashes = data # youngest to oldest
    self.send_GetBlocks(block_hashes)

peer.Peer._recv_BlockHashes = _recv_BlockHashes



def mine(self):
    pass

chainmanager.ChainManager.mine = mine