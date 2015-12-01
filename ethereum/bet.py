import time
from abi import ContractTranslator
from utils import address, int256, trie_root, hash32, to_string, \
    sha3, zpad, normalize_address, int_to_addr, big_endian_to_int, \
    encode_int32, safe_ord
from rlp.sedes import big_endian_int, Binary, binary, CountableList
from serenity_blocks import tx_state_transition, BLKNUMBER, \
    block_state_transition, Block, apply_msg, EmptyVMExt, State
from serenity_transactions import Transaction
from ecdsa_accounts import sign_block, privtoaddr, sign_bet
from config import CASPER, BLKTIME, RNGSEEDS, NULL_SENDER, GENESIS_TIME
from db import OverlayDB
import vm
import serpent
import rlp
import sys
import random
import math

NM_BLOCK = 1

class NetworkMessage(rlp.Serializable):
    fields = [
        ('typ', big_endian_int),
        ('args', CountableList(binary))
    ]

    def __init__(self, typ, args):
        self.typ = typ
        self.args = args


def encode_prob(p):
    q = p / (1.0 - p)
    exp = int(math.log(q) / math.log(2))
    mantissa = int(min(1, q / 2**exp) * 8 - 8)
    return chr(max(0, min(255, exp * 8 + 128 + mantissa)))


class Bet():
    def __init__(self, index, max_height, probs, blockhashes, stateroots, prevhash, seq, sig):
        self.index = index
        self.max_height = max_height
        self.probs = probs
        self.blockhashes = blockhashes
        self.stateroots = stateroots
        self.prevhash = prevhash
        self.seq = seq
        self.sig = sig
        self.hash = sha3(str([max_height, probs, blockhashes, stateroots, prevhash, seq, sig]))

    # def submitBet(index:uint256, max_height:uint256, prob:bytes, blockhashes:bytes32[], stateroots:bytes32[], prevhash:bytes, seqnum:uint256, sig:bytes):

    def serialize(self):
        return casper_ct.encode('submitBet', [self.index, self.max_height, ''.join(map(encode_prob, self.probs)), self.blockhashes, self.stateroots, self.prevhash, self.seq, self.sig])


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
    desired_block_number = big_endian_to_int(state.get_storage(BLKNUMBER, '\x00' * 32)) + 1
    # Check block proposer correctness
    if block.proposer != normalize_address(validator_address):
        sys.stderr.write('Block proposer check failed: actual %s desired %s\n' %
                         (block.proposer.encode('hex'), normalize_address(validator_address.encode('hex'))))
        return False
    # Check signature correctness
    message_data = vm.CallData([safe_ord(x) for x in (sha3(encode_int32(block.number) + block.txroot) + block.sig)], 0, 32 + len(block.sig))
    message = vm.Message(NULL_SENDER, '\x00' * 20, 0, 1000000, message_data)
    _, _, signature_check_result = apply_msg(EmptyVMExt, message, validator_code)
    if signature_check_result != [0] * 31 + [1]:
        sys.stderr.write('Block signature check failed. Actual result: %s\n' % str(signature_check_result))
        return False
    print 'Block validation successful'
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
        self.prevhash = '\x00' * 32
        self.seq = 0
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
                self.max_finalized_heights[i] = -1
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
        if block.hash in self.objects:
            return
        print 'Received block: %d %s' % (block.number, block.hash.encode('hex')[:16])
        while len(self.blocks) <= block.number:
            self.blocks.append(None)
            self.stateroots.append(None)
            self.probs.append(0.5)
        self.objects[block.hash] = block
        self.time_received[block.hash] = time.time()
        check_state = State(self.stateroots[block.number - 10000], self.db) if block.number >= 10000 else self.genesis_state
        if not is_block_valid(check_state, block):
            sys.stderr.write("ERR: Received invalid block: %s\n" % block.hash.encode('hex')[:16])
            return
        self.blocks[block.number] = block
        print "Received good block! "+block.hash.encode('hex')
        self.mkbet()
        self.network.broadcast(self, rlp.encode(NetworkMessage(NM_BLOCK, [rlp.encode(block)])))
        bet = self.mkbet()

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
        scheduled_time = BLKTIME * blk_number + self.genesis_time
        received_time = self.time_received.get(blk_hash, None)
        if received_time:
            time_delta = abs(received_time * 0.98 + time.time() * 0.02 - scheduled_time)
            prob = 1 if time_delta < BLKTIME * 2 else 4.0 / (4.0 + time_delta / BLKTIME)
            print 'Voting, block received. Time delta: %.2f, prob: %.2f' % (time_delta, prob)
            return 0.7 if random.random() < prob else 0.3
        else:
            time_delta = time.time() - scheduled_time
            prob = 1 if time_delta < BLKTIME * 2 else 4.0 / (4.0 + time_delta / BLKTIME)
            print 'Voting, block not received. Time delta: %.2f, prob: %.2f' % (time_delta, prob)
            return 0.5 if random.random() < prob else 0.3

    # Vote based on others' votes
    def vote(self, blk_number, blk_hash):
        probs = [self.opinions[k].probs[blk_number] for k in self.opinions.keys() if blk_number < len(self.opinions[k].probs)]
        probs += [self.default_vote(blk_number, blk_hash)] * (len(self.opinions) - len(probs))
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
        print 'Betting', self.max_finalized_heights
        sign_from = max(0, self.max_finalized_heights[self.id] - 3)
        print 'Signing from:', sign_from
        blockhashes = []
        lowest_changed = len(self.blocks)
        for h in range(sign_from, len(self.blocks)):
            prob = self.vote(h, self.blocks[h].hash if self.blocks[h] else None)
            if (prob - 0.5) * (self.probs[h] - 0.5) <= 0:
                lowest_changed = min(lowest_changed, h)
            self.probs[h] = prob
            if prob < 0.0001 and h == self.my_max_finalized_height + 1:
                while len(self.finalized_hashes) < h:
                    self.finalized_hashes.append(None)
                self.finalized_hashes[h] = self.blocks[h].hash if p > 0.9999 else False
            blockhashes.append(self.blocks[h].hash if self.blocks[h] else None)
        for h in range(lowest_changed, len(self.blocks)):
            run_state = State(self.stateroots[h-1], self.db) if h else self.genesis_state
            block_state_transition(run_state, self.blocks[h] if self.probs[h] > 0.5 else None)
            self.stateroots[h] = run_state.root
        print 'Making bet with probabilities:', self.probs
        o = sign_bet(Bet(self.id, len(self.blocks), self.probs[sign_from:][::-1], [x.hash if x else '\x00' * 32 for x in self.blocks[sign_from:]][::-1], self.stateroots[sign_from:][::-1], self.prevhash, self.seq, ''), self.key)
        self.prevhash = o.hash
        self.seq += 1
        return o

    def on_receive(self, objdata):
        obj = rlp.decode(objdata, NetworkMessage)
        # print 'Received network message of type:', obj.typ
        if obj.typ == NM_BLOCK:
            blk = rlp.decode(obj.args[0], Block)
            self.receive_block(blk)           

    # Run every tick
    def tick(self):
        mytime = time.time()
        target_time = self.genesis_time + BLKTIME * self.next_block_to_produce
        # print 'Node %d ticking. Time: %.2f. Target time: %d (block %d)' % (self.id, mytime, target_time, self.next_block_to_produce)
        if mytime >= target_time:
            o = sign_block(Block(transactions=[], number=self.next_block_to_produce, proposer=self.addr), self.key)
            self.last_block_produced = self.next_block_to_produce
            self.add_proposers()
            print 'Node %d making block: %d %s' % (self.id, o.number, o.hash.encode('hex')[:16])
            self.network.broadcast(self, rlp.encode(NetworkMessage(NM_BLOCK, [rlp.encode(o)])))
            while len(self.blocks) <= o.number:
                self.blocks.append(None)
                self.stateroots.append(None)
                self.probs.append(0.5)
            self.blocks[o.number] = o
            self.objects[o.hash] = o
            self.time_received[o.hash] = mytime
            return o
