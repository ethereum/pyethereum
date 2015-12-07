import time
from abi import ContractTranslator, decode_abi
from utils import address, int256, trie_root, hash32, to_string, \
    sha3, zpad, normalize_address, int_to_addr, big_endian_to_int, \
    encode_int32, safe_ord, encode_int
from rlp.sedes import big_endian_int, Binary, binary, CountableList
from serenity_blocks import tx_state_transition, BLKNUMBER, \
    block_state_transition, Block, apply_msg, EmptyVMExt, State, VMExt
from serenity_transactions import Transaction
from ecdsa_accounts import sign_block, privtoaddr, sign_bet
from config import CASPER, BLKTIME, RNGSEEDS, NULL_SENDER, GENESIS_TIME, ENTER_EXIT_DELAY, GASLIMIT, LOG, BET_INCENTIVIZER, ETHER
from db import OverlayDB
import vm
import serpent
import rlp
import sys
import random
import math

def log(text, condition):
    if condition:
        print text

NM_LIST = 0
NM_BLOCK = 1
NM_BET = 2
NM_BET_REQUEST = 3
NM_TRANSACTION = 4
NM_GETBLOCK = 5
NM_GETBLOCKS = 6
NM_BLOCKS = 7

class NetworkMessage(rlp.Serializable):
    fields = [
        ('typ', big_endian_int),
        ('args', CountableList(binary))
    ]

    def __init__(self, typ, args):
        self.typ = typ
        self.args = args

# Call a method of a function with no effect
def call_method(state, addr, ct, fun, args, gas=1000000):
    data = ct.encode(fun, args)
    message_data = vm.CallData([safe_ord(x) for x in data], 0, len(data))
    message = vm.Message(NULL_SENDER, addr, 0, gas, message_data)
    result, gas_remained, data = apply_msg(VMExt(state.clone()), message, state.get_storage(addr, b''))
    output = ''.join(map(chr, data))
    return ct.decode(fun, output)[0]


bet_incentivizer_code = """
extern casper.se.py: [getUserAddress:[uint256]:address]
macro CASPER: ~sub(0, %d)
macro ETHER: ~sub(0, %d)
data accounts[2**100](balance, gasprice)

def deposit(index):
    self.accounts[index].balance += msg.value
    return(1:bool)

def withdraw(index, val):
    if self.accounts[index].balance >= val and msg.sender == CASPER.getUserAddress(index):
        send(msg.sender, val)
        self.accounts[index].balance -= val
        return(1:bool)
    else:
        return(0:bool)

def setGasprice(index, price):
    if msg.sender == CASPER.getUserAddress(index):
        self.accounts[index].gasprice = price
        return(1:bool)
    else:
        return(0:bool)

def submitBet(bet:bytes):
    gasprice = self.accounts[index].gasprice
    if self.accounts[~mload(bet + 4)].balance > gasprice * ~txexecgas():
        output = 0
        ~call(msg.gas - 40000, CASPER, 0, bet, len(bet), ref(output), 32)
        if output:
            with fee = gasprice * (~txexecgas() - msg.gas + 50000):
                ~call(12000, ETHER, 0, [block.coinbase, fee], 64, 0, 0)
                self.accounts[~mload(bet + 4)].balance -= fee

""" % (2**160 - big_endian_to_int(CASPER), 2**160 - big_endian_to_int(ETHER))

bet_incentivizer_ct = ContractTranslator(serpent.mk_full_signature(bet_incentivizer_code))


# Convert probability from a number to one-byte encoded form
# using scientific notation on odds with a 3-bit mantissa;
# 0 = 65536:1 odds = 0.0015%, 128 = 1:1 odds = 50%, 255 =
# 1:61440 = 99.9984%
def encode_prob(p):
    lastv = '\x00'
    while 1:
        q = p / (1.0 - p)
        exp = int(math.floor(math.log(q) / math.log(2)))
        mantissa = int(max(1, q / 2.0**exp) * 8 - 8)
        v = chr(max(0, min(255, exp * 8 + 128 + mantissa)))
        if v == lastv:
            return v
        p = decode_prob(v)
        lastv = v


# Convert probability from one-byte encoded form to a number
def decode_prob(c):
    c = ord(c)
    q = 2.0**((c - 128) // 8) * (1 + 0.125 * (c % 8))
    return q / (1.0 + q)


invhash = {}


# An object that stores a bet made by a validator
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
        self._hash = None

    def serialize(self):
        o = casper_ct.encode('submitBet', [self.index, self.max_height, ''.join(map(encode_prob, self.probs)), self.blockhashes, self.stateroots, self.prevhash, self.seq, self.sig])
        self._hash = sha3(o)
        return o

    @classmethod
    def deserialize(self, betdata):
        params = decode_abi(casper_ct.function_data['submitBet']['encode_types'], betdata[4:])
        o = Bet(params[0], params[1], map(decode_prob, params[2]), params[3], params[4], params[5], params[6], params[7])
        o._hash = sha3(betdata)
        return o

    @property
    def hash(self):
        if not self._hash:
            self._hash = sha3(self.serialize())
        return self._hash


# An object that stores the "current opinion" of a validator, as computed
# from their chain of bets
class Opinion():
    def __init__(self, validation_code, index, prevhash, seq, induction_height):
        self.validation_code = validation_code
        self.index = index
        self.blockhashes = []
        self.stateroots = []
        self.probs = []
        self.stateroot_probs = []
        self.prevhash = prevhash
        self.seq = seq
        self.induction_height = induction_height
        self.withdrawal_height = 2**255
        self.withdrawn = False

    def process_bet(self, bet):
        # TODO: check crypto and hash
        if bet.seq != self.seq:
            # print 'Bet sequence number does not match expectation: actual %d desired %d' % (bet.seq, self.seq)
            return False
        if self.withdrawn:
            raise Exception("Bet made after withdrawal! Slashing condition triggered!")
        self.seq = bet.seq + 1
        if bet.max_height == 2**255 - 1:
            self.withdrawn = True
            return True
        while len(self.probs) <= bet.max_height:
            self.probs.append(None)
            self.blockhashes.append(None)
            self.stateroots.append(None)
        for i in range(len(bet.probs)):
            self.probs[bet.max_height - i] = bet.probs[i]
        for i in range(len(bet.blockhashes)):
            self.blockhashes[bet.max_height - i] = bet.blockhashes[i]
        for i in range(len(bet.stateroots))[::-1]:
            self.stateroots[bet.max_height - i] = bet.stateroots[i]
        start_index = bet.max_height - 1
        while start_index > 0 and (self.probs[start_index] is None or 0.0001 < self.probs[start_index] < 0.9999):
            start_index -= 1
        stateprobs = [0.9999]
        for i in range(start_index, bet.max_height + 1):
            stateprobs.append(stateprobs[-1] * (max(self.probs[i], 1 - self.probs[i]) if self.probs[i] is not None else 0.5))
        self.stateroot_probs = self.stateroot_probs[:start_index] + stateprobs[1:][::-1]
        # print 'Processed bet from index %d with seq %d. Probs are: %r' % (bet.index, bet.seq, self.probs)
        return True

    def get_prob(self, h):
        return self.probs[h] if h < len(self.probs) else None

    def get_blockhash(self, h):
        return self.blockhashes[h] if h < len(self.probs) else None

    def get_stateroot(self, h):
        return self.stateroots[h] if h < len(self.probs) else None

    @property
    def max_height(self):
        return len(self.probs) - 1

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
                         (block.proposer.encode('hex'), validator_address))
        return False
    # Check signature correctness
    message_data = vm.CallData([safe_ord(x) for x in (sha3(encode_int32(block.number) + block.txroot) + block.sig)], 0, 32 + len(block.sig))
    message = vm.Message(NULL_SENDER, '\x00' * 20, 0, 1000000, message_data)
    _, _, signature_check_result = apply_msg(EmptyVMExt, message, validator_code)
    if signature_check_result != [0] * 31 + [1]:
        sys.stderr.write('Block signature check failed. Actual result: %s\n' % str(signature_check_result))
        return False
    return True

gvi_cache = {}

def get_validator_index(state, blknumber):
    if blknumber not in gvi_cache:
        preseed = state.get_storage(RNGSEEDS, blknumber - ENTER_EXIT_DELAY if blknumber >= ENTER_EXIT_DELAY else 2**256 - 1)
        gvi_cache[blknumber] = call_casper(state, 'sampleValidator', [preseed, blknumber])
    return gvi_cache[blknumber]

next_id = [0]

class defaultBetStrategy():
    def __init__(self, genesis_state, key):
        log("Initializing betting strategy", True)
        self.id = next_id[0]
        next_id[0] += 1
        self.key = key
        self.addr = privtoaddr(key)
        self.db = genesis_state.db
        nextUserId = call_casper(genesis_state, 'getNextUserId', [])
        self.validators_last_updated = call_casper(genesis_state, 'getValidatorsLastUpdated', [])
        log('Found %d validators in genesis' % nextUserId, True)
        self.opinions = {}
        self.bets = {}
        self.highest_bet_processed = {}
        self.time_received = {}
        self.objects = {}
        self.blocks = []
        self.last_asked_for_block = {}
        self.last_asked_for_bets = {}
        self.txpool = {}
        self.txindex = {}
        self.finalized_txindex = {}
        self.last_bet_made = 0
        self.index = -1
        self.genesis_state = genesis_state
        self.genesis_time = big_endian_to_int(genesis_state.get_storage(GENESIS_TIME, '\x00' * 32))
        self.last_block_produced = -1
        self.next_block_to_produce = -1
        self.prevhash = '\x00' * 32
        self.seq = 0
        self.calc_state_roots_from = 2**255
        log("My address: %s" % self.addr.encode('hex'), True)
        for i in range(nextUserId):
            exists = (call_casper(self.genesis_state, 'getUserStatus', [i]) == 2)
            if exists:
                valaddr = call_casper(self.genesis_state, 'getUserAddress', [i])
                valcode = call_casper(self.genesis_state, 'getUserValidationCode', [i])
                assert valcode
                assert valaddr
                self.opinions[i] = Opinion(valcode, i, '\x00' * 32, 0, 0)
                self.bets[i] = {}
                self.highest_bet_processed[i] = -1
                if valaddr == self.addr.encode('hex'):
                    self.index = i
        self.induction_height = call_casper(self.genesis_state, 'getUserInductionHeight', [self.index]) if self.index >= 0 else 2**255
        log("My index: %d" % self.index, True)
        log("My induction height: %d" % self.induction_height, True)
        self.my_max_finalized_height = -1
        self.probs = []
        self.finalized_hashes = []
        self.stateroots = []
        self.proposers = []
        self.add_proposers()
        log('Proposers: %r' % self.proposers, True)

    def add_proposers(self):
        maxh = len(self.finalized_hashes) + ENTER_EXIT_DELAY - 1
        for h in range(len(self.proposers), maxh):
            if h < ENTER_EXIT_DELAY:
                state = self.genesis_state
            else:
                if self.stateroots[h - ENTER_EXIT_DELAY] in (None, '\x00' * 32):
                    self.next_block_to_produce = None
                    return
                state = State(self.stateroots[h - ENTER_EXIT_DELAY], OverlayDB(self.db))
            self.proposers.append(get_validator_index(state, h))
            if self.proposers[-1] == self.index:
                self.next_block_to_produce = h
                return
        self.next_block_to_produce = None

    def receive_block(self, block):
        if block.hash in self.objects:
            return
        log('Received block: %d %s' % (block.number, block.hash.encode('hex')[:16]), self.index == 0 or self.index == 12)
        while len(self.blocks) <= block.number:
            self.blocks.append(None)
            self.stateroots.append(None)
            self.finalized_hashes.append(None)
            self.probs.append(0.5)
        for i, tx in enumerate(block.transactions):
            if tx.hash not in self.finalized_txindex:
                if tx.hash not in self.txindex:
                    self.txindex[tx.hash] = (tx, [])
                self.txindex[tx.hash][1].append((block.number, i))
        self.objects[block.hash] = block
        self.time_received[block.hash] = time.time()
        notsynced = False
        if block.number - ENTER_EXIT_DELAY + 1 >= len(self.stateroots):
            notsynced = True
        elif block.number - ENTER_EXIT_DELAY + 1 >= 0 and self.stateroots[block.number - ENTER_EXIT_DELAY + 1] in (None, '\x00' * 32):
            notsynced = True
        if notsynced:
            sys.stderr.write('Not sufficiently synced to receive this block')
            self.network.send_to_one(self, rlp.encode(NetworkMessage(NM_GETBLOCKS, [rlp.encode(self.my_max_finalized_height)])))
            return
        check_state = State(self.stateroots[block.number - ENTER_EXIT_DELAY + 1], self.db) if block.number >= ENTER_EXIT_DELAY - 1 else self.genesis_state
        if not is_block_valid(check_state, block):
            sys.stderr.write("ERR: Received invalid block: %s\n" % block.hash.encode('hex')[:16])
            return
        if self.my_max_finalized_height >= 0 and self.stateroots[self.my_max_finalized_height] not in (None, '\x00' * 32):
            check_state2 = State(self.stateroots[self.my_max_finalized_height], self.db)
            vlu = call_casper(check_state2, 'getValidatorsLastUpdated', [])
            if vlu > self.validators_last_updated:
                self.validators_last_updated = vlu
                print '#' * 80 + '\n' * 10
                self.update_validator_set(check_state2)
        self.blocks[block.number] = block
        time_delay = time.time() - (self.genesis_time + BLKTIME * block.number)
        log("Received good block at height %d with delay %.2f: %s" % (block.number, time_delay, block.hash.encode('hex')[:16]), self.index == 0)
        self.network.broadcast(self, rlp.encode(NetworkMessage(NM_BLOCK, [rlp.encode(block)])))
        self.mkbet()

    def update_validator_set(self, check_state):
        print 'Updating the validator set'
        for i in range(call_casper(check_state, 'getNextUserId', [])):
            ih = call_casper(check_state, 'getUserInductionHeight', [i])
            wh = call_casper(check_state, 'getUserWithdrawalHeight', [i])
            if i not in self.opinions:
                valaddr = call_casper(check_state, 'getUserAddress', [i])
                valcode = call_casper(check_state, 'getUserValidationCode', [i])
                prevhash = call_casper(check_state, 'getUserPrevhash', [i])
                seq = call_casper(check_state, 'getUserSeq', [i])
                self.opinions[i] = Opinion(valcode, i, prevhash, seq, ih)
                print 'Validator inducted at index %d with address %s' % (i, valaddr)
                print 'Validator address: %s, my address: %s' % (valaddr, self.addr.encode('hex'))
                if i not in self.bets:
                    self.bets[i] = {}
                    self.highest_bet_processed[i] = -1
                if valaddr == self.addr.encode('hex'):
                    self.index = i
                    self.add_proposers()
                    self.induction_height = ih
                    self.withdrawal_height = wh
                    print '#' * 80
                    print 'I have been inducted! id=%d' % self.index
            else:
                self.opinions[i].withdrawal_height = wh
        print 'Have %d opinions' % len(self.opinions)

    def receive_bet(self, bet):
        if bet.hash in self.objects or bet.index not in self.opinions:
            return
        log('Node %d receiving bet from node %d with seq %d, max height %d and probs %r' % (self.index, bet.index, bet.seq, bet.max_height, bet.probs), self.index > 6 or bet.index > 6)
        self.objects[bet.hash] = bet
        self.time_received[bet.hash] = time.time()
        self.network.broadcast(self, rlp.encode(NetworkMessage(NM_BET, [bet.serialize()])))
        if bet.index not in self.bets:
            self.bets[bet.index] = {}
        if bet.index not in self.highest_bet_processed:
            self.highest_bet_processed[bet.index] = -1
        self.bets[bet.index][bet.seq] = bet
        self.add_transaction(Transaction(BET_INCENTIVIZER, 600000, bet_incentivizer_ct.encode('submitBet', [bet.serialize()])))
        proc = 0
        while (self.highest_bet_processed[bet.index] + 1) in self.bets[bet.index]:
            assert self.opinions[bet.index].process_bet(self.bets[bet.index][self.highest_bet_processed[bet.index] + 1])
            self.highest_bet_processed[bet.index] += 1
            proc += 1
        for i in range(0, self.highest_bet_processed[bet.index] + 1):
            assert i in self.bets[bet.index]
        if not proc and self.last_asked_for_bets.get(bet.index, 0) < time.time() + 10:
            self.network.send_to_one(self, rlp.encode(NetworkMessage(NM_BET_REQUEST, map(encode_int, [bet.index, self.highest_bet_processed[bet.index] + 1]))))
            self.last_asked_for_bets[bet.index] = time.time()
        # print 'Block holding status:', ''.join(['1' if self.blocks[i] else '0' for i in range(len(self.blocks))])
        # print 'Time deltas:', [self.time_received[self.blocks[i].hash] - self.genesis_time - BLKTIME * i if self.blocks[i] else None for i in range(len(self.blocks))]
        # print 'broadcasting bet from index %d seq %d as node %d' % (bet.index, bet.seq, self.index)

    # Make a default vote on a block based on when you received it
    def default_vote(self, blk_number, blk_hash):
        scheduled_time = BLKTIME * blk_number + self.genesis_time
        received_time = self.time_received.get(blk_hash, None)
        if received_time:
            time_delta = abs(received_time * 0.98 + time.time() * 0.02 - scheduled_time)
            prob = 1 if time_delta < BLKTIME * 2 else 4.0 / (4.0 + time_delta / BLKTIME)
            log('Voting, block received. Time delta: %.2f, prob: %.2f' % (time_delta, prob), self.index == 0)
            return 0.7 if random.random() < prob else 0.3
        else:
            time_delta = time.time() - scheduled_time
            prob = 1 if time_delta < BLKTIME * 2 else 4.0 / (4.0 + time_delta / BLKTIME)
            log('Voting, block not received. Time delta: %.2f, prob: %.2f' % (time_delta, prob), self.index == 0)
            return 0.5 if random.random() < prob else 0.3

    # Vote based on others' votes
    def vote(self, blk_number, blk_hash):
        probs = []
        default_vote = self.default_vote(blk_number, blk_hash)
        opinion_count = 0
        for i in self.opinions.keys():
            if self.opinions[i].induction_height <= blk_number < self.opinions[i].withdrawal_height:
                p = self.opinions[i].get_prob(blk_number)
                probs.append(p if p is not None else default_vote)
                opinion_count += (1 if p is not None else 0)
            if probs[-1] == default_vote:
                p = self.opinions[i].get_prob(blk_number)
                # print 'Vote disallowed: (%d, %r), %d <= %d < %d required. Voter max height: %d' % (i, p, self.opinions[i].induction_height, blk_number, self.opinions[i].withdrawal_height, self.opinions[i].max_height)
        log('source probs on block %d: %r with %d opinions out of %d' % (blk_number, probs, opinion_count, len(self.opinions)), self.index == 0)
        probs = sorted(probs)
        have_block = blk_hash and blk_hash in self.objects
        if probs[len(probs)/3] > 0.8:
            o = 0.8 + probs[len(probs)/3] * 0.2
        elif probs[len(probs)*2/3] < 0.2:
            o = probs[len(probs)*2/3] * 0.2
        else:
            o = min(0.85, max(0.15, probs[len(probs)/2] * 3 - (0.8 if have_block else 1.2)))
        if o > 0.99 and not have_block:
            if blk_number not in self.last_asked_for_block or self.last_asked_for_block[blk_number] < time.time() + 12:
                print 'Suspiciously missing a block: %d. Asking for it explicitly.' % blk_number
                self.network.broadcast(self, rlp.encode(NetworkMessage(NM_GETBLOCK, [encode_int(blk_number)])))
                self.last_asked_for_block[blk_number] = time.time()
        res = min(o, 1 if have_block else 0.7)
        log('result prob: %.5f %s'% (res, ('have block' if blk_hash in self.objects else 'no block')), self.index == 0)
        return res
        
    # Construct a bet
    def mkbet(self):
        # Bet at most once every two seconds to save on computational costs
        if time.time() < self.last_bet_made + 2:
            return
        self.last_bet_made = time.time()
        sign_from = max(0, self.my_max_finalized_height)
        log('Bet status: %r' % {k: (self.highest_bet_processed[k], self.bets[k][self.highest_bet_processed[k]].probs[sign_from:] if self.highest_bet_processed[k] >= 0 else None) for k in self.bets}, self.index == 0)
        log('My highest bet(%d): %d' % (self.index, self.seq), self.index == 0)
        log('Opinion status: %r' % [[v.probs[i] for v in self.opinions.values() if len(v.probs) > i] for i in range(sign_from, len(self.blocks))], self.index == 0)
        log('Signing from: %r' % sign_from, self.index == 0)
        blockhashes = []
        lowest_changed = min(len(self.blocks), self.calc_state_roots_from)
        log('Making probs from %d to %d non-inclusive' % (sign_from, len(self.blocks)), self.index >= 6)
        for h in range(sign_from, len(self.blocks)):
            prob = self.vote(h, self.blocks[h].hash if self.blocks[h] else None)
            if (prob - 0.5) * (self.probs[h] - 0.5) <= 0:
                lowest_changed = min(lowest_changed, h)
            self.probs[h] = prob
            if prob < 0.0001 or prob > 0.9999:
                log('prob in finality bounds. Current mfh: %d height %d' % (self.my_max_finalized_height, h), self.index == 0)
                self.finalized_hashes[h] = self.blocks[h].hash if prob > 0.9999 else '\x00' * 32
                if h == self.my_max_finalized_height + 1:
                    self.my_max_finalized_height = h
                    log('Increasing max finalized height to %d' % h, self.index == 0)
                assert self.finalized_hashes[h] is not None
            blockhashes.append(self.blocks[h].hash if self.blocks[h] else None)
        log('Lowest changed: %r, reprocessing %d blocks' % (lowest_changed, len(self.blocks) - lowest_changed), self.index == 0)
        log('Recalculating %d out of %d state roots' % (min(len(self.blocks) - lowest_changed, 5), len(self.blocks) - lowest_changed), self.index == 0)
        for h in range(lowest_changed, len(self.blocks))[:5]:
            run_state = State(self.stateroots[h-1] if h else self.genesis_state.root, self.db)
            prevblknum = big_endian_to_int(run_state.get_storage(BLKNUMBER, '\x00' * 32))
            block_state_transition(run_state, self.blocks[h] if self.probs[h] > 0.5 else None)
            self.stateroots[h] = run_state.root
            blknum = big_endian_to_int(run_state.get_storage(BLKNUMBER, '\x00' * 32))
            assert blknum == h + 1, "Prev: %d, block %r, wanted: %d, actual: %d" % (prevblknum, self.blocks[h] if self.probs[h] > 0.5 else None, h + 1, blknum)
        for h in range(lowest_changed + 5, len(self.blocks)):
            self.stateroots[h] = '\x00' * 32
        if lowest_changed + 5 < len(self.blocks):
            self.calc_state_roots_from = lowest_changed + 5
        log('Node %d making bet %d with probabilities from height %d: %r' % (self.index, self.seq, sign_from, self.probs[sign_from:]), self.index == 0 or self.index > 6)
        assert len(self.probs) == len(self.blocks) == len(self.stateroots)
        if self.index >= 0:
            lowest_blockadjust_height = max(sign_from, self.induction_height)
            while lowest_blockadjust_height < len(self.blocks) and \
                    (self.blocks[lowest_blockadjust_height].hash if self.blocks[lowest_blockadjust_height] else '\x00' * 32) == self.opinions[self.index].get_blockhash(lowest_blockadjust_height):
                lowest_blockadjust_height += 1
            log('Changing %d block hashes' % (len(self.blocks) - lowest_blockadjust_height), self.index == 0)
            lowest_stateadjust_height = max(sign_from, self.induction_height)
            while lowest_stateadjust_height < len(self.stateroots) and \
                    self.stateroots[lowest_stateadjust_height] == self.opinions[self.index].get_stateroot(lowest_stateadjust_height):
                lowest_stateadjust_height += 1
            log('Changing %d state roots' % (len(self.stateroots) - lowest_stateadjust_height), self.index == 0)
            o = sign_bet(Bet(self.index, len(self.blocks) - 1, self.probs[max(sign_from, self.induction_height):][::-1], [x.hash if x else '\x00' * 32 for x in self.blocks[sign_from:]][::-1], self.stateroots[lowest_stateadjust_height:][::-1], self.prevhash, self.seq, ''), self.key)
            log('> making bet with induction height %d, signing from %d, max height %d and probabilities: %r' % (self.induction_height, sign_from, o.max_height, o.probs), self.index > 6)
            self.prevhash = o.hash
            self.seq += 1
            payload = rlp.encode(NetworkMessage(NM_BET, [o.serialize()]))
            self.network.broadcast(self, payload)
            self.receive_bet(o)

    def on_receive(self, objdata, sender_id):
        obj = rlp.decode(objdata, NetworkMessage)
        # print 'Received network message of type:', obj.typ
        if obj.typ == NM_BLOCK:
            blk = rlp.decode(obj.args[0], Block)
            self.receive_block(blk)
        elif obj.typ == NM_BET:
            bet = Bet.deserialize(obj.args[0])
            self.receive_bet(bet)           
        elif obj.typ == NM_BET_REQUEST:
            index = big_endian_to_int(obj.args[0])
            seq = big_endian_to_int(obj.args[1])
            if index not in self.bets:
                return
            bets = [self.bets[index][x] for x in range(seq, self.highest_bet_processed[index] + 1)]
            if len(bets):
                messages = [rlp.encode(NetworkMessage(NM_BET, [bet.serialize()])) for bet in bets]
                # print 'Direct sending a response with %d items to %d' % (len(messages), sender_id)
                self.network.direct_send(self, sender_id, rlp.encode(NetworkMessage(NM_LIST, messages)))
        elif obj.typ == NM_TRANSACTION:
            tx = rlp.decode(obj.args[0], Transaction)
            self.add_transaction(tx)
        elif obj.typ == NM_GETBLOCK:
            blknum = big_endian_to_int(obj.args[0])
            if blknum < len(self.blocks) and self.blocks[blknum]:
                self.network.direct_send(self, sender_id, rlp.encode(NetworkMessage(NM_BLOCK, [rlp.encode(self.blocks[blknum])])))
        elif obj.typ == NM_GETBLOCKS:
            blknum = big_endian_to_int(obj.args[0])
            messages = []
            for h in range(blknum, len(self.blocks)):
                if self.blocks[h]:
                    messages.append(rlp.encode(NetworkMessage(NM_BLOCK, [rlp.encode(self.blocks[h])])))
            self.network.direct_send(self, sender_id, rlp.encode(NetworkMessage(NM_LIST, messages)))
            if blknum < len(self.blocks) and self.blocks[blknum]:
                self.network.direct_send(self, sender_id, rlp.encode(NetworkMessage(NM_BLOCK, [rlp.encode(self.blocks[blknum])])))
        elif obj.typ == NM_LIST:
            # print 'Receiving list with %d items' % len(obj.args)
            for x in obj.args:
                self.on_receive(x, sender_id)

    def add_transaction(self, tx):
        if tx.hash not in self.objects:
            log('Received transaction: %s' % tx.hash.encode('hex'), self.index == 0)
            self.objects[tx.hash] = tx
            self.time_received[tx.hash] = time.time()
            self.txpool[tx.hash] = tx
            self.network.broadcast(self, rlp.encode(NetworkMessage(NM_TRANSACTION, [rlp.encode(tx)])))

    def make_block(self):
        # Transaction inclusion algorithm
        gas = GASLIMIT
        txs = []
        # Try to include transactions in txpool
        for h, tx in self.txpool.items():
            if h not in self.txindex and h not in self.finalized_txindex:
                log('Adding transaction: %s' % tx.hash.encode('hex'), self.index == 0)
                if tx.gas > gas:
                    break
                txs.append(tx)
                gas -= tx.gas
        for h, (tx, positions) in self.txindex.items():
            i = 0
            while i < len(positions):
                blknum, index = positions[i]
                if self.stateroots[blknum] in (None, '\x00' * 32):
                    i += 1
                    continue
                logresult = big_endian_to_int(State(self.stateroots[blknum], self.db).get_storage(LOG, index)[:32])
                p = self.probs[blknum]
                if p > 0.999 and logresult != 0:
                    log('Transaction finalized, hash %s at blknum %d with index %d' % (tx.hash.encode('hex'), blknum, index), self.index == 0)
                    if h in self.txpool:
                        del self.txpool[h]
                    if h not in self.finalized_txindex:
                        self.finalized_txindex[h] = (tx, [])
                    self.finalized_txindex[h][1].append((blknum, index))
                    positions.pop(i)
                elif p < 0.001 or (p > 0.999 and logresult == 0):
                    positions.pop(i)
                else:
                    i += 1
            if len(positions) == 0:
                del self.txindex[h]
        print [self.txindex.get(tx.hash, None) for tx in txs]
        b = sign_block(Block(transactions=txs, number=self.next_block_to_produce, proposer=self.addr), self.key)
        time_delay = time.time() - (self.genesis_time + BLKTIME * b.number)
        self.last_block_produced = self.next_block_to_produce
        self.add_proposers()
        log('>> Node %d making block: %d %s with time delay %.2f' % (self.index, b.number, b.hash.encode('hex')[:16], time_delay), True)
        self.network.broadcast(self, rlp.encode(NetworkMessage(NM_BLOCK, [rlp.encode(b)])))
        self.receive_block(b)
        return b

    # Run every tick
    def tick(self):
        mytime = time.time()
        if self.index >= 0 and self.next_block_to_produce is not None:
            target_time = self.genesis_time + BLKTIME * self.next_block_to_produce
            # print 'Node %d ticking. Time: %.2f. Target time: %d (block %d)' % (self.index, mytime, target_time, self.next_block_to_produce)
            if mytime >= target_time:
                self.make_block()
        elif self.next_block_to_produce is None:
            self.add_proposers()
        # max_block = int((time.time() - self.genesis_time) / BLKTIME)
        # for i, opinion in self.opinions.items():
        #     if opinion.max_height < max_block - 15:
        #         self.network.broadcast(self, rlp.encode(NetworkMessage(NM_BET_REQUEST, map(encode_int, [i, self.highest_bet_processed[bet.index] + 1]))))
