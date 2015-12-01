import time
from abi import ContractTranslator
from utils import address, int256, trie_root, hash32, to_string, \
    sha3, zpad, normalize_address, int_to_addr, big_endian_to_int, \
    encode_int32
from rlp.sedes import big_endian_int, Binary, binary, CountableList
from serenity_blocks import tx_state_transition, BLKNUMBER, \
    block_state_transition, Block, apply_msg, EmptyVMExt
from serenity_transactions import Transaction
from ecdsa_accounts import sign_block, privtoaddr
from config import CASPER, BLKTIME, RNGSEEDS, NULL_SENDER, GENESIS_TIME
from db import OverlayDB
import vm
import serpent
import rlp

NM_BLOCK = 1

class NetworkMessage(rlp.Serializable):
    fields = [
        ('typ', big_endian_int),
        ('args', CountableList(binary))
    ]

    def __init__(self, typ, args):
        self.typ = typ
        self.args = args

class Bet():
    def __init__(self, max_height, probs, blockhashes, stateroots, prevhash, seq, sig):
        self.max_height = max_height
        self.probs = probs
        self.blockhashes = blockhashes
        self.stateroots = stateroots
        self.prevhash = prevhash
        self.seq = seq
        self.sig = sig
        self.hash = sha3(str([max_height, probs, blockhashes, stateroots, prevhash, seq, sig]))


class Opinion():
    def __init__(self, validation_code, index, prevhash, seq):
        self.validation_code = validation_code
        self.index = index
        self.blockhashes = []
        self.stateroots = []
        self.probs = []
        self.stateroot_probs = []
        self.prevhash = prevhash
        self.seq = seq

    def process_bet(self, bet):
        # TODO: check crypto and hash
        if bet.seq != self.seq:
            return False
        self.seq = bet.seq + 1
        while len(self.probs) <= bet.max_height:
            self.probs.append(0.5)
            self.blockhashes.append('\x00' * 32)
            self.stateroots.append('\x00' * 32)
        for i in range(len(bet.probs)):
            self.probs[bet.max_height - i] = bet.probs[i]
        for i in range(len(bet.blockhashes)):
            self.blockhashes[bet.max_height - i] = bet.blockhashes[i]
        for i in range(len(bet.stateroots))[::-1]:
            self.stateroots[bet.max_height - i] = bet.stateroots[i]
        start_index = bet.max_height - 1
        while start_index > 0 and 0.0001 < self.probs[start_index] < 0.9999:
            start_index -= 1
        stateprobs = [0.9999]
        for i in range(start_index, bet.max_height + 1):
            stateprobs.append(stateprobs[i] * max(self.probs[i], 1 - self.probs[i]))
        self.stateroot_probs = self.stateroot_probs[:start_index] + stateprobs[1:][::-1]
        return True

    @property
    def max_height():
        return len(self.probs) - 1


# Call a method of a function with no effect
def call_method(state, addr, ct, fun, args):
    tx = Transaction(addr, 1000000, ct.encode(fun, args))
    return ct.decode(fun, ''.join(map(chr, tx_state_transition(state.clone(), tx, 0))))[0]

casper_ct = ContractTranslator(serpent.mk_full_signature('casper.se.py'))

def call_casper(state, fun, args):
    return call_method(state, CASPER, casper_ct, fun, args)

# Accepts any state less than 10000 blocks old
def is_block_valid(state, block):
    validator_index = get_validator_index(state, block.number)
    validator_address = call_casper(state, 'getUserAddress', [validator_index])
    validator_code = call_casper(state, 'getUserValidationCode', [validator_index])
    if block.number != state.get_storage(BLKNUMBER, '\x00' * 32):
        return False
    if block.proposer != normalize_address(validator_address):
        return False
    message_data = vm.CallData([safe_ord(x) for x in (sha3(encode_int32(block.number) + block.txroot) + block.sig)], 0, len(tx.data))
    message = vm.Message(NULL_SENDER, '\x00' * 20, 0, 1000000, message_data)
    if apply_msg(EmptyVMExt, message, validator_code) != [0] * 31 + [1]:
        return False
    return True

def get_validator_index(state, blknumber):
    preseed = state.get_storage(RNGSEEDS, blknumber - 10000 if blknumber >= 10000 else 2**256 - 1)
    return call_casper(state, 'sampleValidator', [preseed, blknumber])

class defaultBetStrategy():
    def __init__(self, genesis_state, key):
        print "Initializing betting strategy"
        self.key = key
        self.addr = privtoaddr(key)
        self.opinions = {}
        self.db = genesis_state.db
        nextUserId = call_casper(genesis_state.clone(), 'getNextUserId', [])
        print 'Found %d validators in genesis' % nextUserId
        self.opinions = {}
        self.time_received = {}
        self.objects = {}
        self.max_finalized_heights = {}
        self.blocks = []
        self.id = -1
        self.genesis_state = genesis_state
        self.genesis_time = big_endian_to_int(genesis_state.get_storage(GENESIS_TIME, '\x00' * 32))
        self.validators = {}
        self.last_block_produced = -1
        self.next_block_to_produce = -1
        print "My address", self.addr.encode('hex')
        for i in range(nextUserId):
            exists = (call_casper(self.genesis_state, 'getUserStatus', [i]) == 2)
            if exists:
                self.validators[i] = {
                    "address": call_casper(self.genesis_state, 'getUserAddress', [i]),
                    "valcode": call_casper(self.genesis_state, 'getUserValidationCode', [i]),
                    "seq": 0,
                    "prevhash": '\x00' * 32,
                }
                assert self.validators[i]["valcode"], self.validators[i]["address"]
                self.opinions[i] = Opinion(self.validators[i]["valcode"], i, '\x00' * 32, 0)
                self.max_finalized_heights[i] = self.genesis_state.get_storage(BLKNUMBER, '\x00' * 32)
                if self.validators[i]["address"] == self.addr.encode('hex'):
                    self.id = i
        assert self.id >= 0
        print "My index", self.id
        self.my_max_finalized_height = 0
        self.probs = []
        self.finalized_hashes = []
        self.stateroots = []
        self.proposers = []
        self.add_proposers()
        print 'Proposers: ', self.proposers

    def add_proposers(self):
        maxh = len(self.finalized_hashes) + 9999
        for h in range(len(self.proposers), maxh):
            if h < 10000:
                state = self.genesis_state
            else:
                state = State(self.stateroots[h], OverlayDB(self.db))
            self.proposers.append(get_validator_index(state, h))
            if self.proposers[-1] == self.id:
                self.next_block_to_produce = h
                return
        self.next_block_to_produce = None

    def receive_block(self, block):
        while len(self.blocks) < block.number:
            self.blocks.append(None)
            self.stateroots.append(None)
        if not self.blocks[block.number]:
            if is_block_valid(State(self.stateroots[max(block.number - 10000, 0)], self.db), block.number):
                self.blocks[block.number] = block
                self.time_received[block.hash] == time.time()
                sys.stderr.write("Received good block! "+block.hash.encode('hex'))
                self.mkbet()
            else:
                sys.stderr.write("ERR: Received invalid block "+block.hash.encode('hex'))

    def receive_bet(self, bet):
        if bet not in self.time_received:
            self.opinions[bet.index].process_bet(bet)
            self.time_received[bet] = time.time()
            while self.max_finalized_heights[bet.index] < self.opinions[bet.index].max_height:
                p = self.opinions[bet.index].probs[self.max_finalized_heights[bet.index] + 1]
                if p < 0.0001 or p > 0.9999:
                    self.max_finalized_heights[bet.index] += 1
                else:
                    break

    # Make a default vote on a block based on when you received it
    def default_vote(self, blk_number, blk_hash):
        scheduled_time = BLKTIME * blk_number + genesis_time
        received_time = self.time_received.get(blk_hash, None)
        if received_time:
            time_delta = abs(received_time * 0.98 + time.time() * 0.02 - scheduled_time)
            prob = 1 if time_delta < BLKTIME * 2 else 4.0 / (4.0 + time_delta / BLKTIME)
            return 0.3 if random.random() < prob else 0.7
        else:
            time_delta = time.time() - scheduled_time
            prob = 1 if time_delta < BLKTIME * 2 else 4.0 / (4.0 + time_delta / BLKTIME)
            return 0.5 if random.random() < prob else 0.7

    # Vote based on others' votes
    def vote(self, blk_number, blk_hash):
        probs = [self.opinions[k].probs[blk_number] for k in self.opinions.keys() if blk_number < len(self.opinions[k].probs)]
        probs += [default_vote(blk)] * (len(self.opinions) - len(probs))
        probs = sorted(probs)
        if probs[len(probs)/3] > 0.7:
            o = 0.7 + probs[len(probs)/3] * 0.3
        elif probs[len(probs)*2/3] < 0.3:
            o = probs[len(probs)/3] * 0.3
        else:
            o = probs[len(probs)/2]
        return min(o, 1 if blk_hash and blk_hash in self.time_received else 0.7)
        
    # Construct a bet
    def mkbet(self):
        sign_from = max(0, self.max_finalized_heights[self.id] - 3)
        blockhashes = []
        lowest_changed = len(self.blocks)
        for h in range(sign_from, len(self.blocks)):
            prob = self.vote(h, self.blocks[h].hash if self.blocks[h] else None)
            if (vote - 0.5) * (self.probs[h] - 0.5) <= 0:
                lowest_changed = min(lowest_changed, h)
            probs.append(vote)
            if prob < 0.0001 and h == self.my_max_finalized_height + 1:
                while len(self.finalized_hashes) < h:
                    self.finalized_hashes.append(None)
                self.finalized_hashes[h] = self.blocks[h].hash if p > 0.9999 else False
                self.states[h] = block_state_transition(self.states[h-1] if h else genesis_state, self.blocks[h])
            blockhashes.append(self.blocks[h].hash if self.blocks[h] else None)
        for h in range(lowest_changed + 1, len(self.blocks)):
            self.states[h] = block_state_transition(self.states[h-1] if h else genesis_state, self.blocks[h])
        o = Bet(len(self.blocks), self.probs[sign_from:][::-1], [x.root for x in self.states[sign_from:]][::-1], self.prevhash, self.seq, '')
        self.prevhash = o.hash
        self.seq += 1

    def on_receive(self, objdata):
        obj = rlp.decode(objdata, NetworkMessage)
        # print 'Received network message of type:', obj.typ
        if obj.typ == NM_BLOCK:
            blk = rlp.decode(obj.args[0], Block)
            if blk.hash in self.objects:
                return
            print 'Received block: %d %s' % (blk.number, blk.hash.encode('hex')[:16])
            self.objects[blk.hash] = blk
            self.network.broadcast(self, objdata)
            

    # Run every tick
    def tick(self):
        mytime = time.time()
        target_time = self.genesis_time + BLKTIME * self.next_block_to_produce
        # print 'Node %d ticking. Time: %.2f. Target time: %d (block %d)' % (self.id, mytime, target_time, self.next_block_to_produce)
        if mytime >= target_time:
            o = sign_block(Block(transactions=[], number=self.next_block_to_produce), self.key)
            self.last_block_produced = self.next_block_to_produce
            self.add_proposers()
            print 'Node %d making block: %d %s' % (self.id, o.number, o.hash.encode('hex')[:16])
            self.network.broadcast(self, rlp.encode(NetworkMessage(NM_BLOCK, [rlp.encode(o)])))
            while len(self.blocks) <= o.number:
                self.blocks.append(None)
                self.stateroots.append(None)
            self.blocks[o.number] = o
            self.objects[o.hash] = o
            self.time_received[o.hash] = mytime
            return o
