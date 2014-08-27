"""
patch to fetch write raw blocks to a file

create a file pyethereum/monkeypatch.py
and import tihis file

configure to connect to one peer, no mine

"""
print('IMPORTED BLOCKFETCHERPATCH')
fn = 'blocks.0-2k.poc6.p27.hexdata'


NUM_BLOCKS_PER_REQUEST = 1

##############
import sys
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

def _recv_Blocks(self, data):
    print("RECEIVED BLOCKS", len(data)) # youngest to oldest
    for x in reversed(data):
        enc = rlp.encode(x)
        #tb = blocks.TransientBlock(enc)
        #print tb
        self.blk_counter += 1
        fh.write(enc.encode('hex') + '\n') # LOG line
        h = utils.sha3(enc)
        print('received block %s %d' % (h.encode('hex'), self.blk_counter))

    if len(data) == NUM_BLOCKS_PER_REQUEST:
        block_hash = utils.sha3(rlp.encode(data[-1]))
        print("ASKING FOR MORE HASHES", block_hash.encode('hex'))
        print("genesis is", blocks.genesis().hex_hash())
        self.send_GetBlockHashes(block_hash, NUM_BLOCKS_PER_REQUEST)
    else:
        print 'done'
        sys.exit(0)

peer.Peer._recv_Blocks = _recv_Blocks

old_hello = peer.Peer._recv_Hello
def _recv_Hello(self, data):
    old_hello(self, data)
    h = blocks.genesis().hash
    print('HELLO RECEIVED')
    head_hash = data[7]
    print "head_hash", head_hash.encode('hex')
    self.send_GetBlockHashes(head_hash, NUM_BLOCKS_PER_REQUEST)
peer.Peer._recv_Hello = _recv_Hello

def _recv_BlockHashes(self, data):
    print("RECEIVED BLOCKHASHES", len(data)) # youngest to oldest
    block_hashes = data # youngest to oldest
    self.send_GetBlocks(block_hashes)

peer.Peer._recv_BlockHashes = _recv_BlockHashes



def mine(self):
    pass

chainmanager.ChainManager.mine = mine