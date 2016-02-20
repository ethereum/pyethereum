import time
from abi import ContractTranslator, decode_abi
from utils import address, int256, trie_root, hash32, to_string, \
    sha3, zpad, normalize_address, int_to_addr, big_endian_to_int, \
    encode_int32, safe_ord, encode_int, shardify
from rlp.sedes import big_endian_int, Binary, binary, CountableList
from serenity_blocks import tx_state_transition, BLKNUMBER, \
    block_state_transition, Block, apply_msg, EmptyVMExt, State, VMExt, \
    get_code
from serenity_transactions import Transaction
from ecdsa_accounts import sign_block, privtoaddr, sign_bet, mk_transaction
from config import CASPER, BLKTIME, RNGSEEDS, NULL_SENDER, GENESIS_TIME, ENTER_EXIT_DELAY, GASLIMIT, LOG, BET_INCENTIVIZER, ETHER, VALIDATOR_ROUNDS, EXECUTION_STATE, TXINDEX, BLKNUMBER, ADDR_BYTES, GAS_DEPOSIT
from mandatory_account_code import mandatory_account_evm
from db import OverlayDB
import fastvm as vm
import serpent
import rlp
import sys
import random
import math
import copy

FINALITY_LOW, FINALITY_HIGH = 0.00001, 0.99999
MAX_RECALC = 9
MAX_LONG_RECALC = 14

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

rlp_dict = {}

def rlp_decode(*args):
    cache_key = str(args)
    if cache_key not in rlp_dict:
        rlp_dict[cache_key] = rlp.decode(*args)
    return copy.deepcopy(rlp_dict[cache_key])

def weighted_percentile(values, weights, frac):
    zipvals = sorted(zip(values, weights))
    target = sum(weights) * frac
    while target > zipvals[0][1]:
        target -= zipvals[0][1]
        zipvals.pop(0)
    return zipvals[0][0]

# Network message object
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
    result, gas_remained, data = apply_msg(VMExt(state.clone()), message, get_code(state, addr))
    output = ''.join(map(chr, data))
    return ct.decode(fun, output)[0]

# Convert probability from a number to one-byte encoded form
# using scientific notation on odds with a 3-bit mantissa;
# 0 = 65536:1 odds = 0.0015%, 128 = 1:1 odds = 50%, 255 =
# 1:61440 = 99.9984%
def encode_prob(p):
    lastv = '\x00'
    while 1:
        q = p / (1.0 - p)
        exp = 0
        while q < 1:
            q *= 2.0
            exp -= 1
        while q >= 2:
            q /= 2.0
            exp += 1
        mantissa = int(q * 7 - 6.9999)
        v = chr(max(0, min(255, exp * 7 + 128 + mantissa)))
        return v


# Convert probability from one-byte encoded form to a number
def decode_prob(c):
    c = ord(c)
    q = 2.0**((c - 128) // 7) * (1 + 0.142857142 * ((c - 128) % 7))
    return q / (1.0 + q)

# Be VERY careful about updating the above algorithms; if the assert below
# fails (ie. encode and decode are not inverses) then bet serialization will
# break and so casper will break
assert map(encode_prob, map(decode_prob, map(chr, range(256)))) == map(chr, range(256)), map(encode_prob, map(decode_prob, map(chr, range(256))))


invhash = {}


# An object that stores a bet made by a validator
class Bet():
    def __init__(self, index, max_height, probs, blockhashes, stateroots, stateroot_prob_from, prevhash, seq, sig):
        self.index = index
        self.max_height = max_height
        self.probs = probs
        self.blockhashes = blockhashes
        self.stateroots = stateroots
        self.stateroot_prob_from = stateroot_prob_from
        self.prevhash = prevhash
        self.seq = seq
        self.sig = sig
        self._hash = None

    # Serializes the bet into the function message which can be directly submitted
    # to the casper contract
    def serialize(self):
        o = casper_ct.encode('submitBet',
            [self.index, self.max_height, ''.join(map(encode_prob, self.probs)),
             self.blockhashes, self.stateroots, encode_prob(self.stateroot_prob_from),
             self.prevhash, self.seq, self.sig]
        )
        self._hash = sha3(o)
        return o

    # Inverse of serialization
    @classmethod
    def deserialize(self, betdata):
        params = decode_abi(casper_ct.function_data['submitBet']['encode_types'],
                            betdata[4:])
        o = Bet(params[0], params[1], map(decode_prob, params[2]), params[3],
                params[4], decode_prob(params[5]), params[6], params[7], params[8])
        o._hash = sha3(betdata)
        return o

    # Warning: edit bets very carefully! Make sure hash is always correct 
    @property
    def hash(self, recompute=False):
        if not self._hash or recompute:
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
        self.prevhash = prevhash
        self.seq = seq
        self.induction_height = induction_height
        self.withdrawal_height = 2**100
        self.withdrawn = False

    def process_bet(self, bet):
        # TODO: check crypto
        if bet.seq != self.seq:
            sys.stderr.write('Bet sequence number does not match expectation: actual %d desired %d\n' % (bet.seq, self.seq))
            return False
        if bet.prevhash != self.prevhash:
            sys.stderr.write('Bet hash does not match prevhash: actual %s desired %s. Seq: %d \n' %
                             (bet.prevhash.encode('hex'), self.prevhash.encode('hex'), bet.seq))
        if self.withdrawn:
            raise Exception("Bet made after withdrawal! Slashing condition triggered!")
        # Update seq and hash
        self.seq = bet.seq + 1
        self.prevhash = bet.hash
        # A bet with max height 2**256 - 1 signals withdrawal
        if bet.max_height == 2**256 - 1:
            self.withdrawn = True
            self.withdrawal_height = self.max_height
            log("Validator leaving!: %d" % bet.index, True)
            return True
        # Extend probs, blockhashes and state roots arrays as needed
        while len(self.probs) <= bet.max_height:
            self.probs.append(None)
            self.blockhashes.append(None)
            self.stateroots.append(None)
        # Update probabilities, blockhashes and stateroots
        for i in range(len(bet.probs)):
            self.probs[bet.max_height - i] = bet.probs[i]
        for i in range(len(bet.blockhashes)):
            self.blockhashes[bet.max_height - i] = bet.blockhashes[i]
        for i in range(len(bet.stateroots))[::-1]:
            self.stateroots[bet.max_height - i] = bet.stateroots[i]
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

# Helper method for calling Casper
casper_ct = ContractTranslator(serpent.mk_full_signature('casper.se.py'))

def call_casper(state, fun, args, gas=1000000):
    return call_method(state, CASPER, casper_ct, fun, args, gas)

# Accepts any state less than ENTER_EXIT_DELAY blocks old
def is_block_valid(state, block):
    # Determine the desired proposer address and the validation code
    validator_index = get_validator_index(state, block.number)
    validator_address = call_casper(state, 'getUserAddress', [validator_index])
    validator_code = call_casper(state, 'getUserValidationCode', [validator_index])
    assert isinstance(validator_code, (str, bytes))
    # Check block proposer correctness
    if block.proposer != normalize_address(validator_address):
        sys.stderr.write('Block proposer check for %d failed: actual %s desired %s\n' %
                         (block.number, block.proposer.encode('hex'), validator_address))
        return False
    # Check signature correctness
    message_data = vm.CallData([safe_ord(x) for x in (sha3(encode_int32(block.number) + block.txroot) + block.sig)], 0, 32 + len(block.sig))
    message = vm.Message(NULL_SENDER, '\x00' * 20, 0, 1000000, message_data)
    _, _, signature_check_result = apply_msg(EmptyVMExt, message, validator_code)
    if signature_check_result != [0] * 31 + [1]:
        sys.stderr.write('Block signature check failed. Actual result: %s\n' % str(signature_check_result))
        return False
    return True

# Helper method for getting the validator index for a particular block number
gvi_cache = {}

def get_validator_index(state, blknumber):
    if blknumber not in gvi_cache:
        preseed = state.get_storage(RNGSEEDS, blknumber - ENTER_EXIT_DELAY if blknumber >= ENTER_EXIT_DELAY else 2**256 - 1)
        gvi_cache[blknumber] = call_casper(state, 'sampleValidator', [preseed, blknumber], gas=3000000)
    return gvi_cache[blknumber]

# Helper for making an ID
next_id = [0]
def mkid():
    next_id[0] += 1
    return next_id[0] - 1

# The default betting strategy; initialize with the genesis block and a privkey
class defaultBetStrategy():
    def __init__(self, genesis_state, key, clockwrong=False, bravery=0.84,
                 crazy_bet=False, double_block_suicide=2**200, double_bet_suicide=2**200, min_gas_price=10**9):
        log("Initializing betting strategy", True)
        # An ID for purposes of the network simulator
        self.id = mkid()
        # Validator's private key
        self.key = key
        # Validator's address on the network
        self.addr = privtoaddr(key)
        # The bet strategy's database
        self.db = genesis_state.db
        # This counter is incremented every time a validator joins;
        # it allows us to re-process the validator set and refresh
        # the validators that we have
        self.validator_signups = call_casper(genesis_state, 'getValidatorSignups', [])
        # A dict of opinion objects containing the current opinions of all
        # validators
        self.opinions = {}
        # A dict of lists of bets received from validators
        self.bets = {}
        # Deposit sizes of all validators
        self.deposit_sizes = {}
        # A dict containing the highest-sequence-number bet processed for
        # each validator
        self.highest_bet_processed = {}
        # The time when you received an object
        self.time_received = {}
        # Hash lookup map; used mainly to check whether or not something has
        # already been received and processed
        self.objects = {}
        # Blocks selected for each height
        self.blocks = []
        # When you last explicitly requested to ask for a block; stored to
        # prevent excessively frequent lookups
        self.last_asked_for_block = {}
        # When you last explicitly requested to ask for bets from a given
        # validator; stored to prevent excessively frequent lookups
        self.last_asked_for_bets = {}
        # Pool of transactions worth including
        self.txpool = {}
        # Map of hash -> (tx, [(blknum, index), ...]) for transactions that
        # are in blocks that are not fully confirmed
        self.unconfirmed_txindex = {}
        # Map of hash -> (tx, [(blknum, index), ...]) for transactions that
        # are in blocks that are fully confirmed
        self.finalized_txindex = {}
        # Counter for number of times a transaction entered an exceptional
        # condition
        self.tx_exceptions = {}
        # Last time you made a bet; stored to prevent excessively
        # frequent betting
        self.last_bet_made = 0
        # Last time sent a getblocks message; stored to prevent excessively
        # frequent getting
        self.last_time_sent_getblocks = 0
        # Your validator index
        self.index = -1
        self.former_index = None
        # Store the genesis block state here
        self.genesis_state_root = genesis_state.root
        # Store the timestamp of the genesis block
        self.genesis_time = big_endian_to_int(genesis_state.get_storage(GENESIS_TIME, '\x00' * 32))
        # Last block that you produced
        self.last_block_produced = -1
        # Next height at which you are eligible to produce (could be None)
        self.next_block_to_produce = -1
        # Deliberately sabotage my clock? (for testing purposes)
        self.clockwrong = clockwrong
        # How quickly to converge toward finalization?
        self.bravery = bravery
        assert 0 < self.bravery <= 1
        # Am I making crazy bets? (for testing purposes)
        self.crazy_bet = crazy_bet
        # What block number to create two blocks at, destroying my validator
        # slot (for testing purposes; for non-byzantine nodes set to some really
        # high number)
        self.double_block_suicide = double_block_suicide
        # What seq to create two bets at (also destructively, for testing purposes)
        self.double_bet_suicide = double_bet_suicide
        # Next submission delay (should be 0 on livenet; nonzero for testing purposes)
        self.next_submission_delay = random.randrange(-BLKTIME * 2, BLKTIME * 6) if self.clockwrong else 0
        # Prevhash (for betting)
        self.prevhash = '\x00' * 32
        # Sequence number (for betting)
        self.seq = 0
        # Transactions I want to track
        self.tracked_tx_hashes = []
        # If we only partially calculate state roots, store the index at which
        # to start calculating next time you make a bet
        self.calc_state_roots_from = 0
        # Minimum gas price that I accept
        self.min_gas_price = min_gas_price
        log("My address: %s" % self.addr.encode('hex'), True)
        # Iterate over all validators in the genesis block...
        for j in range(call_casper(genesis_state, 'getNextUserPos', [])):
            i = call_casper(genesis_state, 'getUserAtPosition', [j])
            # If they are currently active...
            exists = (call_casper(genesis_state, 'getUserStatus', [i]) == 2)
            if exists:
                # Make sure they have a validation address and code
                valaddr = call_casper(genesis_state, 'getUserAddress', [i])
                valcode = call_casper(genesis_state, 'getUserValidationCode', [i])
                assert valcode
                assert valaddr
                self.deposit_sizes[i] = call_casper(genesis_state, 'getUserDeposit', [i])
                # Initialize opinion and bet objects
                self.opinions[i] = Opinion(valcode, i, '\x00' * 32, 0, 0)
                self.bets[i] = {}
                self.highest_bet_processed[i] = -1
                if valaddr == self.addr.encode('hex'):
                    self.index = i
        log('Found %d validators in genesis' % len(self.opinions), True)
        # The height at which this user is added
        self.induction_height = call_casper(genesis_state, 'getUserInductionHeight', [self.index]) if self.index >= 0 else 2**100
        log("My index: %d" % self.index, True)
        log("My induction height: %d" % self.induction_height, True)
        self.withdrawn = False
        # Max height which is finalized from your point of view
        self.my_max_finalized_height = -1
        # The probabilities that you are betting
        self.probs = []
        # Your finalized block hashes
        self.finalized_hashes = []
        # Your predicted block hashes
        self.predicted_hashes = []
        # Your state roots
        self.stateroots = []
        # Recently discovered blocks
        self.recently_discovered_blocks = []
        # List of proposers for blocks; calculated into the future just-in-time
        self.proposers = []
        self.add_proposers()
        log('Proposers: %r' % self.proposers, True)
        # When will I suicide?
        if self.double_block_suicide < 2**40:
            if self.double_block_suicide < self.next_block_to_produce:
                log("Suiciding at block %d" % self.next_block_to_produce, True)
            else:
                log("Suiciding at some block after %d" % self.double_block_suicide, True)
        # Am I byzantine?
        self.byzantine = self.crazy_bet or self.double_block_suicide < 2**80 or self.double_bet_suicide < 2**80

    # Compute as many future block proposers as possible
    def add_proposers(self):
        h = len(self.finalized_hashes) - 1
        while h >= 0 and self.stateroots[h] in (None, '\x00' * 32):
            h -= 1
        state = State(self.stateroots[h] if h >= 0 else self.genesis_state_root, self.db)
        maxh = h + ENTER_EXIT_DELAY - 1
        for h in range(len(self.proposers), maxh):
            self.proposers.append(get_validator_index(state, h))
            if self.proposers[-1] == self.index:
                self.next_block_to_produce = h
                return
        self.next_block_to_produce = None

    def receive_block(self, block):
        # If you already processed the block, return
        if block.hash in self.objects:
            return
        log('Received block: %d %s' % (block.number, block.hash.encode('hex')[:16]), self.index >= 8)
        # Update the lengths of our main lists to make sure they can store
        # the data we will be calculating
        while len(self.blocks) <= block.number:
            self.blocks.append(None)
            self.stateroots.append(None)
            self.finalized_hashes.append(None)
            self.predicted_hashes.append(None)
            self.probs.append(0.5)
        # If we are not sufficiently synced, try to sync previous blocks first
        notsynced = False
        if block.number - ENTER_EXIT_DELAY + 1 >= len(self.stateroots):
            notsynced = True
        elif block.number - ENTER_EXIT_DELAY + 1 >= 0 and self.stateroots[block.number - ENTER_EXIT_DELAY + 1] in (None, '\x00' * 32):
            notsynced = True
        if notsynced:
            sys.stderr.write('Not sufficiently synced to receive this block (%d)\n' % block.number)
            if self.last_time_sent_getblocks < time.time() - 5:
                log('asking for blocks', True)
                self.network.broadcast(self, rlp.encode(NetworkMessage(NM_GETBLOCKS, [encode_int(self.my_max_finalized_height+1)])))
                self.last_time_sent_getblocks = time.time()
            return
        # If the block is invalid, return
        check_state = State(self.stateroots[block.number - ENTER_EXIT_DELAY + 1]
                            if block.number >= ENTER_EXIT_DELAY - 1 else self.genesis_state_root, self.db)
        if not is_block_valid(check_state, block):
            sys.stderr.write("ERR: Received invalid block: %d %s\n" % (block.number, block.hash.encode('hex')[:16]))
            return
        # Try to update the set of validators
        if self.my_max_finalized_height >= 0 and self.stateroots[self.my_max_finalized_height] not in (None, '\x00' * 32):
            check_state2 = State(self.stateroots[self.my_max_finalized_height], self.db)
            vs = call_casper(check_state2, 'getValidatorSignups', [])
            if vs > self.validator_signups:
                log('updating validator signups: %d vs %d' % (vs, self.validator_signups), True)
                self.validator_signups = vs
                self.update_validator_set(check_state2)
        # Add the block to our list of blocks
        if not self.blocks[block.number]:
            self.blocks[block.number] = block
        else:
            log('Caught a double block!\n\n', True)
            bytes1 = rlp.encode(self.blocks[block.number].header)
            bytes2 = rlp.encode(block.header)
            new_tx = Transaction(CASPER, 500000 + 1000 * len(bytes1) + 1000 * len(bytes2),
                                 data=casper_ct.encode('slashBlocks', [bytes1, bytes2]))
            self.add_transaction(new_tx, track=True)
        # Store the block as having been received
        self.objects[block.hash] = block
        self.time_received[block.hash] = time.time()
        self.recently_discovered_blocks.append(block.number)
        time_delay = time.time() - (self.genesis_time + BLKTIME * block.number)
        log("Received good block at height %d with delay %.2f: %s" % (block.number, time_delay, block.hash.encode('hex')[:16]), self.index == 3)
        # Add transactions to the unconfirmed transaction index
        for i, g in enumerate(block.transaction_groups):
            for j, tx in enumerate(g):
                if tx.hash not in self.finalized_txindex:
                    if tx.hash not in self.unconfirmed_txindex:
                        self.unconfirmed_txindex[tx.hash] = (tx, [])
                    self.unconfirmed_txindex[tx.hash][1].append((block.number, block.hash, i, j))
        # Re-broadcast the block
        self.network.broadcast(self, rlp.encode(NetworkMessage(NM_BLOCK, [rlp.encode(block)])))
        # Bet
        log('maybe am going to bet: %d, block height %d' % (self.index, block.number), self.index >= 8)
        if (self.index % VALIDATOR_ROUNDS) == (block.number % VALIDATOR_ROUNDS):
            self.mkbet()

    # Try to update the set of validators
    def update_validator_set(self, check_state):
        log('Updating the validator set', True)
        for j in range(call_casper(check_state, 'getNextUserPos', [])):
            i = call_casper(check_state, 'getUserAtPosition', [j])
            # Ooh, we found a new validator
            if i not in self.opinions:
                ih = call_casper(check_state, 'getUserInductionHeight', [i])
                valaddr = call_casper(check_state, 'getUserAddress', [i])
                valcode = call_casper(check_state, 'getUserValidationCode', [i])
                self.deposit_sizes[i] = call_casper(check_state, 'getUserDeposit', [i])
                self.opinions[i] = Opinion(valcode, i, '\x00' * 32, 0, ih)
                log('Validator inducted at index %d with address %s' % (i, valaddr), True)
                log('Validator address: %s, my address: %s' % (valaddr, self.addr.encode('hex')), True)
                assert i not in self.bets
                assert i not in self.highest_bet_processed
                self.bets[i] = {}
                self.highest_bet_processed[i] = -1
                # Is the new validator me?
                if valaddr == self.addr.encode('hex'):
                    self.index = i
                    self.add_proposers()
                    self.induction_height = ih
                    log('#' * 80 + '\n' + ('I have been inducted! id=%d\n\n' % self.index), True)
        log('Have %d opinions' % len(self.opinions), True)

    def receive_bet(self, bet):
        # Do not process the bet if (i) we already processed it, or (ii) it
        # comes from a validator not in the current validator set
        if bet.hash in self.objects or bet.index not in self.opinions:
            return
        # Record when the bet came and that it came
        self.objects[bet.hash] = bet
        self.time_received[bet.hash] = time.time()
        # Re-broadcast it
        self.network.broadcast(self, rlp.encode(NetworkMessage(NM_BET, [bet.serialize()])))
        # Do we have a duplicate? If so, slash it
        if bet.seq in self.bets[bet.index]:
            log('Caught a double bet!\n\n', True)
            bytes1 = self.bets[bet.index][bet.seq].serialize()
            bytes2 = bet.serialize()
            new_tx = Transaction(CASPER, 500000 + 1000 * len(bytes1) + 1000 * len(bytes2),
                                 data=casper_ct.encode('slashBets', [bytes1, bytes2]))
            self.add_transaction(new_tx, track=True)
        # Record it
        self.bets[bet.index][bet.seq] = bet
        # If we have an unbroken chain of bets from 0 to N, and last round
        # we had an unbroken chain only from 0 to M, then process bets
        # M+1...N. For example, if we had bets 0, 1, 2, 4, 5, 7, now we
        # receive 3, then we assume bets 0, 1, 2 were already processed
        # but now process 3, 4, 5 (but NOT 7)
        log('receiving a bet: seq %d, bettor %d recipient %d' % (bet.seq, bet.index, self.index), self.id < 5)
        proc = 0
        while (self.highest_bet_processed[bet.index] + 1) in self.bets[bet.index]:
            assert self.opinions[bet.index].process_bet(self.bets[bet.index][self.highest_bet_processed[bet.index] + 1]), (self.index, bet.index, self.highest_bet_processed[bet.index], self.bets[bet.index], self.opinions[bet.index].seq)
            self.highest_bet_processed[bet.index] += 1
            proc += 1
        # Sanity check
        for i in range(0, self.highest_bet_processed[bet.index] + 1):
            assert i in self.bets[bet.index]
        assert self.opinions[bet.index].seq == self.highest_bet_processed[bet.index] + 1
        # If we did not process any bets after receiving a bet, that
        # implies that we are missing some bets. Ask for them.
        if not proc and self.last_asked_for_bets.get(bet.index, 0) < time.time() + 10:
            self.network.send_to_one(self, rlp.encode(NetworkMessage(NM_BET_REQUEST, map(encode_int, [bet.index, self.highest_bet_processed[bet.index] + 1]))))
            self.last_asked_for_bets[bet.index] = time.time()

    # Make a default vote on a block based on when you received it
    def default_vote(self, blk_number, blk_hash):
        scheduled_time = BLKTIME * blk_number + self.genesis_time
        received_time = self.time_received.get(blk_hash, None)
        # If we already received a block...
        if received_time:
            time_delta = abs(received_time * 0.96 + time.time() * 0.04 - scheduled_time)
            prob = 1 if time_delta < BLKTIME * 2 else 3.0 / (3.0 + time_delta / BLKTIME)
            log('Voting, block received. Time delta: %.2f, prob: %.2f' % (time_delta, prob), self.index == 3)
            return 0.7 if random.random() < prob else 0.3
        # If we have not yet received a block...
        else:
            time_delta = time.time() - scheduled_time
            prob = 1 if time_delta < BLKTIME * 2 else 3.0 / (3.0 + time_delta / BLKTIME)
            log('Voting, block not received. Time delta: %.2f, prob: %.2f' % (time_delta, prob), self.index == 3)
            return 0.5 if random.random() < prob else 0.3

    # Vote based on others' votes
    def vote(self, blk_number, blk_hash):
        # Do we have the block?
        have_block = blk_hash and blk_hash in self.objects
        # The list of votes to use when producing one's own vote
        probs = []
        # Weights for each validator
        weights = []
        # My default opinion based on (i) whether or not I have the block,
        # (ii) when I saw it first if I do, and (iii) the current time
        default_vote = self.default_vote(blk_number, blk_hash)
        # Go through others' opinions, check if they (i) are eligible to
        # vote, and (ii) have voted; if they have, add their vote to the
        # list of votes; otherwise, add the default vote in their place
        opinion_count = 0
        withdrawn = 0
        for i in self.opinions.keys():
            if self.opinions[i].induction_height <= blk_number < self.opinions[i].withdrawal_height and not self.opinions[i].withdrawn:
                p = self.opinions[i].get_prob(blk_number)
                # If this validator has not yet voted, then add our default vote
                if p is None:
                    probs.append(default_vote)
                # If they voted for a different block as the block hash currently being processed, then:
                # * if their probability is low, that means they are voting for the null case, so take their vote as is
                # * if their probability is high, that means that they are voting for a different block, so for this
                # block hash flip the vote as it's a vote against this particular block hash
                elif self.opinions[i].blockhashes[blk_number] != blk_hash and blk_hash is not None:
                    probs.append(min(p, max(1 - p, 0.25)))
                # If they voted for the same block as is currently being processed, then take their vote as is
                else:
                    probs.append(p)
                weights.append(self.deposit_sizes[i])
                opinion_count += (1 if p is not None else 0)
            elif self.opinions[i].withdrawn:
                withdrawn += 1
        log('source probs on block %d: %r with %d opinions out of %d with %d withdrawn' % (blk_number, probs, opinion_count, len(self.opinions), withdrawn), self.index == 3)
        # The algorithm for producing your own vote based on others' votes;
        # the intention is to converge toward 0 or 1
        p33 = weighted_percentile(probs, weights, 1/3.)
        p50 = weighted_percentile(probs, weights, 1/2.)
        p67 = weighted_percentile(probs, weights, 2/3.)
        if p33 > 0.8:
            o = self.bravery + p33 * (1 - self.bravery)
        elif p67 < 0.2:
            o = p67 * (1 - self.bravery)
        else:
            o = min(0.85, max(0.15, p50 * 3 - (0.8 if have_block else 1.2)))
        # If the probability we get is above 0.8 but we do not have the
        # block, then ask for it explicitly
        if o > 0.8 and not have_block and blk_hash not in (None, '\x00' * 32):
            if blk_hash not in self.last_asked_for_block or self.last_asked_for_block[blk_hash] < time.time() + 12:
                log('Suspiciously missing a block: %d %s. Asking for it explicitly.' %
                    (blk_number, blk_hash[:8].encode('hex')), True)
                self.network.broadcast(self, rlp.encode(NetworkMessage(NM_GETBLOCK, [blk_hash])))
                self.last_asked_for_block[blk_hash] = time.time()
        # Cap votes at 0.7 unless we know for sure that we have a block
        res = min(o, 1 if have_block else 0.7)
        if self.crazy_bet and FINALITY_LOW < res < FINALITY_HIGH:
            res = 1 / (1 + FINALITY_LOW ** (random.random() * 1.8 - 0.9))
        log('result prob: %.5f %s'% (res, ('have block' if blk_hash in self.objects else 'no block')), self.index == 3)
        # Return the resulting vote
        return res

    # Make a bet that signifies that we do not want to make any more bets
    def withdraw(self):
        o = sign_bet(Bet(self.index, 2**256 - 1, [], [], [], FINALITY_HIGH, self.prevhash, self.seq, ''), self.key)
        payload = rlp.encode(NetworkMessage(NM_BET, [o.serialize()]))
        self.prevhash = o.hash
        self.seq += 1
        self.network.broadcast(self, payload)
        self.receive_bet(o)
        self.former_index = self.index
        self.index = -1
        self.withdrawn = True

    # Take one's ether out
    def finalizeWithdrawal(self):
        txdata = casper_ct.encode('withdraw', [self.former_index])
        tx = mk_transaction(0, 1, 1000000, CASPER, 0, txdata, k, True)
        v = tx_state_transition(genesis, tx)

    def recalc_state_roots(self):
        recalc_limit = MAX_RECALC if self.calc_state_roots_from > len(self.blocks) - 20 else MAX_LONG_RECALC
        frm = self.calc_state_roots_from
        print 'recalc limit: ', recalc_limit, 'want to recalculate: ', len(self.blocks) - frm
        run_state = State(self.stateroots[frm-1] if frm else self.genesis_state_root, self.db)
        for h in range(frm, len(self.blocks))[:recalc_limit]:
            # from ethereum.slogging import LogRecorder, configure_logging, set_level
            # config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace'
            # configure_logging(config_string=config_string)
            prevblknum = big_endian_to_int(run_state.get_storage(BLKNUMBER, '\x00' * 32))
            assert prevblknum == h
            if self.probs[h] is None:
                prob = self.default_vote(h, self.blocks[h])
            else:
                prob = self.probs[h]
            self.predicted_hashes[h] = self.blocks[h].hash if prob >= 0.5 and self.blocks[h] else '\x00' * 32
            block_state_transition(run_state, self.blocks[h] if prob >= 0.5 else None)
            self.stateroots[h] = run_state.root
            blknum = big_endian_to_int(run_state.get_storage(BLKNUMBER, '\x00' * 32))
            assert blknum == h + 1
        # If there are some state roots that we have not calculated, just leave them empty
        for h in range(frm + recalc_limit, len(self.blocks)):
            self.stateroots[h] = '\x00' * 32
        # Where to calculate state roots from next time
        self.calc_state_roots_from = min(frm + recalc_limit, len(self.blocks))
        # Check integrity
        for i in range(self.calc_state_roots_from):
            assert self.stateroots[i] not in ('\x00' * 32, None)
        for i in range(min(self.calc_state_roots_from, self.my_max_finalized_height)):
            assert self.finalized_hashes[i] == self.predicted_hashes[i]
        
    # Construct a bet
    def mkbet(self):
        # Bet at most once every two seconds to save on computational costs
        if time.time() < self.last_bet_made + 2:
            return
        self.last_bet_made = time.time()
        # Height at which to start signing
        sign_from = max(0, self.my_max_finalized_height)
        # Keep track of the lowest state root that we should change
        log('Making probs from %d to %d inclusive' % (sign_from, len(self.blocks) - 1), True)
        # Vote on each height independently using our voting strategy
        for h in range(sign_from, len(self.blocks)):
            candidates = [o.blockhashes[h] for o in self.opinions.values()
                          if len(o.blockhashes) > h and o.blockhashes[h]]
            if self.blocks[h]:
                candidates.append(self.blocks[h].hash)
            elif not len(candidates):
                candidates.append(None)
            candidates = list(set(candidates))
            # Locate highest probability
            probs = [(self.vote(h, c), c) for c in candidates]
            prob, new_block_hash = sorted(probs)[-1]
            if len(probs) >= 2:
                log('Voting on multiple candidates (height %d): %r, selected %r' %
                    (h, [(a, b[:8].encode('hex')) for a, b in probs], (prob, new_block_hash[:8].encode('hex'))), True)
            if self.blocks[h] and new_block_hash != self.blocks[h].hash:
                log('Flipping block at height %d from %s to %s' %
                    (h, self.blocks[h].hash[:8].encode('hex'), new_block_hash[:8].encode('hex')), True)
                if new_block_hash not in (None, '\x00' * 32):
                    assert self.objects[new_block_hash].number == h
                    self.blocks[h] = self.objects[new_block_hash]
                    self.recently_discovered_blocks.append(h)
            # If the probability of a block flips to the other side of 0.5,
            # that means that we should recalculate the state root at least
            # from that point (and possibly earlier)
            if ((prob - 0.5) * (self.probs[h] - 0.5) <= 0 or (self.probs[h] >= 0.5 and \
                    h in self.recently_discovered_blocks)) and h < self.calc_state_roots_from:
                print 'Rewinding %d blocks' % (self.calc_state_roots_from - h)
                self.calc_state_roots_from = min(self.calc_state_roots_from, h)
            self.probs[h] = prob
            # Finalized!
            if prob < FINALITY_LOW or prob > FINALITY_HIGH:
                log('prob in finality bounds. Current mfh: %d height %d' % (self.my_max_finalized_height, h), self.index == 3)
                # Set the finalized hash
                self.finalized_hashes[h] = self.blocks[h].hash if prob > FINALITY_HIGH else '\x00' * 32
                # Try to increase the max finalized height
                while h == self.my_max_finalized_height + 1:
                    self.my_max_finalized_height = h
                    log('Increasing max finalized height to %d' % h, self.index == 3)
                    if not h % 10:
                        check_state = State(self.stateroots[self.calc_state_roots_from-1] if self.calc_state_roots_from else self.genesis_state_root, self.db)
                        for i in self.opinions.keys():
                            self.deposit_sizes[i] = call_casper(check_state, 'getUserDeposit', [i])
        # Recalculate state roots
        rootstart = max(self.calc_state_roots_from, self.induction_height)
        self.recalc_state_roots()
        # Check state root integrity
        log('Node %d making bet %d with probabilities from height %d: %r' %
            (self.index, self.seq, sign_from, self.probs[sign_from:]), self.crazy_bet)
        # Sanity check
        assert len(self.probs) == len(self.blocks) == len(self.stateroots)
        # If we are supposed to actually make a bet... (if not, all the code
        # above is simply for personal information, ie. for a listening node
        # to determine its opinion on what the correct chain is)
        if self.index >= 0 and len(self.blocks) > self.induction_height and not self.withdrawn and len(self.recently_discovered_blocks):
            # Create and sign the bet
            blockstart = max(min(self.recently_discovered_blocks), self.induction_height)
            probstart = min(max(sign_from, self.induction_height), blockstart, rootstart)
            o = sign_bet(Bet(self.index,
                             len(self.blocks) - 1,
                             self.probs[probstart:][::-1],
                             [x.hash if x else '\x00' * 32 for x in self.blocks[blockstart:]][::-1],
                             self.stateroots[rootstart:][::-1],
                             FINALITY_HIGH,
                             self.prevhash,
                             self.seq, ''),
                        self.key)
            # Reset the recently discovered blocks array, so that we do not needlessly resubmit hashes
            self.recently_discovered_blocks = []
            # Update my prevhash and seq
            self.prevhash = o.hash
            self.seq += 1
            # Send the bet over the network
            payload = rlp.encode(NetworkMessage(NM_BET, [o.serialize()]))
            self.network.broadcast(self, payload)
            # Process it myself
            self.receive_bet(o)
            # Create two bets of the same seq (for testing purposes)
            if self.seq > self.double_bet_suicide and len(o.probs):
                log('MOO HA HA DOUBLE BETTING\n\n', True)
                o.probs[0] *= 0.9
                o = sign_bet(o, self.key)
                payload = rlp.encode(NetworkMessage(NM_BET, [o.serialize()]))
                self.network.broadcast(self, payload)

    # Upon receiving any kind of network message
    # Arguments: payload, ID of the node sending the message (used to
    # direct-send replies back)
    def on_receive(self, objdata, sender_id):
        obj = rlp_decode(objdata, NetworkMessage)
        if obj.typ == NM_BLOCK:
            blk = rlp_decode(obj.args[0], Block)
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
                self.network.direct_send(self, sender_id, rlp.encode(NetworkMessage(NM_LIST, messages)))
        elif obj.typ == NM_TRANSACTION:
            tx = rlp_decode(obj.args[0], Transaction)
            if self.should_i_include_transaction(tx):
                self.add_transaction(tx)
        elif obj.typ == NM_GETBLOCK:
            # Asking for block by number:
            if len(obj.args[0]) < 32:
                blknum = big_endian_to_int(obj.args[0])
                log('Returning block by number: %d' % blknum, True)
                if blknum < len(self.blocks) and self.blocks[blknum]:
                    self.network.direct_send(self, sender_id, rlp.encode(NetworkMessage(NM_BLOCK, [rlp.encode(self.blocks[blknum])])))
            # Asking for block by hash
            else:
                o = self.objects.get(obj.args[0], None)
                if isinstance(o, Block):
                    log('Returning block by hash: %s, %r (%d)' % (obj.args[0][:8].encode('hex'), o, o.number), True)
                    self.network.direct_send(self, sender_id, rlp.encode(NetworkMessage(NM_BLOCK, [rlp.encode(o)])))
        elif obj.typ == NM_GETBLOCKS:
            log('Replying to GETBLOCKS message', True)
            blknum = big_endian_to_int(obj.args[0])
            messages = []
            for h in range(blknum, len(self.blocks))[:30]:
                if self.blocks[h]:
                    messages.append(rlp.encode(NetworkMessage(NM_BLOCK, [rlp.encode(self.blocks[h])])))
            log('Sending %d blocks from %d' % (len(messages), blknum), True)
            self.network.direct_send(self, sender_id, rlp.encode(NetworkMessage(NM_LIST, messages)))
            if blknum < len(self.blocks) and self.blocks[blknum]:
                self.network.direct_send(self, sender_id, rlp.encode(NetworkMessage(NM_BLOCK, [rlp.encode(self.blocks[blknum])])))
        elif obj.typ == NM_LIST:
            print 'Receiving list with %d items' % len(obj.args)
            for x in obj.args:
                self.on_receive(x, sender_id)

    def should_i_include_transaction(self, tx):
        check_state = State(self.stateroots[self.calc_state_roots_from-1] if self.calc_state_roots_from else self.genesis_state_root, OverlayDB(self.db))
        def my_listen(sender, topics, data):
            pass
            # print 't', topics

        if tx.addr == BET_INCENTIVIZER:
            o = tx_state_transition(check_state, tx)
            if not o:
                log('No output from running transaction to bet incentivizer', True)
                return False
            output = ''.join(map(chr, o))
            if len(output) < 32 or big_endian_to_int(output) != 1:
                log('Transaction to bet incentivizer fails', True)
                return False
            log('Transaction to bet incentivizer passes, should be included', True)
            return True
        else:
            o = tx_state_transition(check_state, tx, override_gas=150000+tx.intrinsic_gas, breaking=True, listeners=[my_listen])
            if not o:
                log('No output from running transaction', True)
                return False
            output = ''.join(map(chr, o))
            # Make sure that the account code matches
            if get_code(check_state, tx.addr).rstrip('\x00') != mandatory_account_evm:
                log('Account EVM mismatch: %r %r' %
                    (get_code(check_state, tx.addr), mandatory_account_evm), True)
                return False
            # Make sure that the right gas price is in memory (and implicitly that the tx succeeded)
            if len(output) < 32:
                log('Min gas price not found in output, not including transaction', True)
                return False
            # Make sure that the gas price is sufficient
            if big_endian_to_int(output[:32]) < self.min_gas_price:
                log('Gas price too low: shouldbe %d reallyis %d' % (self.min_gas_price, big_endian_to_int(output[:32])), True)
                return False
            log('Transaction passes, should be included', True)
            return True
    
    def add_transaction(self, tx, track=False):
        if tx.hash not in self.objects or self.time_received.get(tx.hash, 0) < time.time() - 15:
            log('Received transaction: %s' % tx.hash.encode('hex'), self.index == 3)
            self.objects[tx.hash] = tx
            self.time_received[tx.hash] = time.time()
            self.txpool[tx.hash] = tx
            if track:
                self.tracked_tx_hashes.append(tx.hash)
            self.network.broadcast(self, rlp.encode(NetworkMessage(NM_TRANSACTION, [rlp.encode(tx)])))

    def get_transaction_status(self, h):
        if h in self.finalized_txindex:
            return 'finalized: %r' % [[x[0], x[1][:8].encode('hex'), x[2], x[3]] for x in [self.finalized_txindex[h][1][0]]][0]
        elif h in self.unconfirmed_txindex:
            return 'unconfirmed: %r' % [(x[0], self.probs[x[0]], x[1][:8].encode('hex'), x[2], x[3]) for x in self.unconfirmed_txindex[h][1]]
        else:
            return None

    def make_block(self):
        # Transaction inclusion algorithm
        gas = GASLIMIT
        txs = []
        # Try to include transactions in txpool
        for h, tx in self.txpool.items():
            # If a transaction is not in the unconfirmed index AND not in the
            # finalized index, then add it
            if h not in self.unconfirmed_txindex and h not in self.finalized_txindex:
                log('Adding transaction: %s' % tx.hash.encode('hex'), self.index == 3)
                if tx.gas > gas:
                    break
                txs.append(tx)
                gas -= tx.gas
        # Publish most recent bets to the blockchain
        h = 0
        while h < len(self.stateroots) and self.stateroots[h] not in (None, '\x00' * 32):
            h += 1
        latest_state_root = self.stateroots[h-1] if h else self.genesis_state_root
        assert latest_state_root not in ('\x00' * 32, None)
        latest_state = State(latest_state_root, self.db)
        ops = self.opinions.items() 
        random.shuffle(ops)
        print 'Producing block %d, know up to %d, using state root after %d' % (self.next_block_to_produce, len(self.blocks)-1, h-1)
        for i, o in ops:
            latest_bet = call_casper(latest_state, 'getUserSeq', [i])
            bet_height = latest_bet
            while bet_height in self.bets[i]:
                print 'Inserting bet %d of validator %d using state root after height %d' % (latest_bet, i, h-1)
                bet = self.bets[i][bet_height]
                new_tx = Transaction(BET_INCENTIVIZER, 200000 + 6600 * len(bet.probs) + 10000 * len(bet.blockhashes + bet.stateroots),
                                     data=bet.serialize())
                if bet.max_height == 2**256 - 1:
                    self.tracked_tx_hashes.append(new_tx.hash)
                if new_tx.gas > gas:
                    break
                txs.append(new_tx)
                gas -= new_tx.gas
                bet_height += 1
            if o.seq < latest_bet:
                self.network.send_to_one(self, rlp.encode(NetworkMessage(NM_BET_REQUEST, map(encode_int, [i, o.seq + 1]))))
                self.last_asked_for_bets[i] = time.time()
        # Process the unconfirmed index for the transaction. Note that a
        # transaction could theoretically get included in the chain
        # multiple times even within the same block, though if the account
        # used to process the transaction is sane the transaction should
        # fail all but one time
        for h, (tx, positions) in self.unconfirmed_txindex.items():
            i = 0
            while i < len(positions):
                # We see this transaction at index `index` of block number `blknum`
                blknum, blkhash, groupindex, txindex = positions[i]
                if self.stateroots[blknum] in (None, '\x00' * 32):
                    i += 1
                    continue
                # Probability of the block being included
                p = self.probs[blknum]
                # Try running it
                if p > 0.95:
                    grp_shard = self.blocks[blknum].summaries[groupindex].left_bound
                    logdata = State(self.stateroots[blknum], self.db).get_storage(shardify(LOG, grp_shard), txindex)
                    logresult = big_endian_to_int(rlp.decode(rlp.descend(logdata, 0)))
                    # If the transaction passed and the block is finalized...
                    if p > 0.9999 and logresult == 2:
                        log('Transaction finalized, hash %s at blknum %d blkhash %s with index (%d, %d)' %
                            (tx.hash.encode('hex'), blknum, blkhash[:8].encode('hex'), groupindex, txindex), self.index == 3)
                        # Remove it from the txpool
                        if h in self.txpool:
                            del self.txpool[h]
                        # Add it to the finalized index
                        if h not in self.finalized_txindex:
                            self.finalized_txindex[h] = (tx, [])
                        self.finalized_txindex[h][1].append((blknum, blkhash, groupindex, txindex, rlp.decode(logdata)))
                        positions.pop(i)
                    # If the transaction was included but exited with an error (eg. due to a sequence number mismatch)
                    elif p > 0.95 and logresult == 1:
                        positions.pop(i)
                        self.tx_exceptions[h] = self.tx_exceptions.get(h, 0) + 1
                        log('Transaction inclusion finalized but transaction failed for the %dth time. p: %.5f, logresult: %d' %
                            (self.tx_exceptions[h], p, logresult), True)
                        # 10 strikes and we're out
                        if self.tx_exceptions[h] >= 10:
                            if h in self.txpool:
                                del self.txpool[h]
                    # If the transaction failed (eg. due to OOG from block gaslimit),
                    # remove it from the unconfirmed index, but not the expool, so
                    # that we can try to add it again
                    elif logresult == 0:
                        log('Transaction finalization attempt failed. p: %.5f, logresult: %d' % (p, logresult), True)
                        positions.pop(i)
                    else:
                        i += 1
                # If the block that the transaction was in didn't pass through,
                # remove it from the unconfirmed index, but not the expool, so
                # that we can try to add it again
                elif p < 0.05:
                    log('Transaction finalization attempt failed. p: %.5f' % p, True)
                    positions.pop(i)
                # Otherwise keep the transaction in the unconfirmed index
                else:
                    i += 1
            if len(positions) == 0:
                del self.unconfirmed_txindex[h]
        # Produce the block
        b = sign_block(Block(transactions=txs, number=self.next_block_to_produce, proposer=self.addr), self.key)
        # Broadcast it
        self.network.broadcast(self, rlp.encode(NetworkMessage(NM_BLOCK, [rlp.encode(b)])))
        self.receive_block(b)
        # If byzantine, produce two blocks
        if b.number >= self.double_block_suicide:
            log('## Being evil and making two blocks!!\n\n', True)
            new_tx = mk_transaction(1, 1, 1000000, '\x33' * ADDR_BYTES, 1, '', self.key, True)
            txs2 = [tx for tx in txs] + [new_tx]
            b2 = sign_block(Block(transactions=txs2, number=self.next_block_to_produce, proposer=self.addr), self.key)
            self.network.broadcast(self, rlp.encode(NetworkMessage(NM_BLOCK, [rlp.encode(b2)])))
        # Extend the list of block proposers
        self.last_block_produced = self.next_block_to_produce
        self.add_proposers()
        # Log it
        time_delay = time.time() - (self.genesis_time + BLKTIME * b.number)
        log('Node %d making block: %d %s with time delay %.2f' % (self.index, b.number, b.hash.encode('hex')[:16], time_delay), True)
        return b

    # Run every tick
    def tick(self):
        mytime = time.time()
        # If (i) we should be making blocks, and (ii) the time has come to
        # produce a block, then produce a block
        if self.index >= 0 and self.next_block_to_produce is not None:
            target_time = self.genesis_time + BLKTIME * self.next_block_to_produce
            if mytime >= target_time + self.next_submission_delay:
                self.recalc_state_roots()
                self.make_block()
                self.next_submission_delay = random.randrange(-BLKTIME * 2, BLKTIME * 6) if self.clockwrong else 0
        elif self.next_block_to_produce is None:
            self.add_proposers()
        if self.last_bet_made < time.time() - BLKTIME * VALIDATOR_ROUNDS * 1.5:
            self.mkbet()
