"""
patch to fetch write raw blocks to a file

create a file pyethereum/monkeypatch.py
and import tihis file

configure to connect to one peer, no mine

"""
print('IMPORTED BLOCKFETCHERPATCH')
fn = 'blocks.0-20k.p23.hexdata'


NUM_BLOCKS_PER_REQUEST = 256

##############

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

def request(self, blk_hash):
    print('asking for children of %r' % blk_hash.encode('hex'))
    self.send_packet(packeter.dump_GetChain([blk_hash], count=NUM_BLOCKS_PER_REQUEST))

def _recv_Blocks(self, data):
    print("RECEIVED", len(data))
    for x in reversed(data):
        enc = rlp.encode(x)
        #tb = blocks.TransientBlock(enc)
        #print tb
        self.blk_counter += 1
        fh.write(enc.encode('hex') + '\n') # LOG line
        h = utils.sha3(enc)
        print('received block %s %d' % (h.encode('hex'), self.blk_counter))
    request(self,h)

peer.Peer._recv_Blocks = _recv_Blocks

old_hello = peer.Peer._recv_Hello
def _recv_Hello(self, data):
    old_hello(self, data)
    h = blocks.genesis().hash
    print('HELLO RECEIVED')
    #request(self, h)




peer.Peer._recv_Hello = _recv_Hello

def mine(self):
    pass

chainmanager.ChainManager.mine = mine