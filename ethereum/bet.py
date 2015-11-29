import time
from abi import ContractTranslator
from ethereum.utils import address, int256, trie_root, hash32, to_string, \
    sha3, zpad, normalize_address, int_to_addr, big_endian_to_int
from serenity_blocks import tx_state_transition, BLKNUMBER, \
    block_state_transition
from config import CASPER
BLKTIME = 5

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
        self.blockhashes
        self.stateroots
        self.probs
        self.stateroot_probs
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


def call_method(state, ct, fun, args):
    tx = Transaction(CASPER_ADDRESS, 100000, ct.encode(fun, args))
    return ct.decode(fun, tx_state_transition(state, tx))
        

class defaultBetStrategy():
    def __init__(self, genesis_state, my_index, genesis_time):
        self.opinions = {}
        self.ct = ContractTranslator([])
        nextUserId = call_method(genesis_state.clone(), self.ct, 'getNextUserId', [])
        self.opinions = {}
        self.times_received = {}
        self.max_finalized_heights = {}
        self.blocks = []
        self.my_index = my_index
        self.genesis_time = genesis_time
        for i in range(nextUserId):
            exists = (call_method(state.clone(), self.ct, 'getUserStatus', [i]) == 1)
            if exists:
                validators[i] = {
                    "address": call_method(state.clone(), self.ct, 'getUserAddress', [i]),
                    "valcode": call_method(state.clone(), self.ct, 'getValidationCode', [i]),
                    "seq": 0,
                    "prevhash": '\x00' * 32,
                }
                self.opinions[i] = Opinion(validators[i]["valcode"], i, '\x00' * 32, 0)
                self.max_finalized_heights[i] = state.get(BLKNUMBER, '\x00' * 32)
        self.my_max_finalized_height = 0
        self.probs = []
        self.finalized_hashes = []
        self.stateroots = []

    def receive_block(self, block):
        # TODO: crypto validation
        while len(self.blocks) < block.number:
            self.blocks.append(None)
        if not self.blocks[block.number]:
            self.blocks[block.number] = block
            self.times_received[block.hash] == time.time()
            self.mkbet()

    def receive_bet(self, bet):
        if bet not in self.times_received:
            self.opinions[bet.index].process_bet(bet)
            self.times_received[bet] = time.time()
            while self.max_finalized_heights[bet.index] < self.opinions[bet.index].max_height:
                p = self.opinions[bet.index].probs[self.max_finalized_heights[bet.index] + 1]
                if p < 0.0001 or p > 0.9999:
                    self.max_finalized_heights[bet.index] += 1
                else:
                    break

    # Make a default vote on a block based on when you received it
    def default_vote(self, blk_number, blk_hash):
        scheduled_time = BLKTIME * blk_number + genesis_time
        received_time = self.times_received.get(blk_hash, None)
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
        return min(o, 1 if blk_hash and blk_hash in self.times_received else 0.7)
        
    # Construct a bet
    def mkbet(self):
        sign_from = max(0, self.max_finalized_heights[my_index] - 3)
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
