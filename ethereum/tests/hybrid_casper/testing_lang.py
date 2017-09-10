# Not finished, needs to be properly hooked in
# Example code:
# J1 J2 J3 B B B S1 B B R1 B B B P1 P2 C1 C2 B S1 B B B
# B100 for 1 epoch? B5 B1 B2 etc for blocks, B is just mining 1 block!
# Translates into:
# Join with validators 1, 2 and 3. Then create 3 blocks, save a
# checkpoint 1. Create 2 more blocks, then revert to checkpoint 1.
# Create 3 more blocks, then prepare and commit with validators
# 1 and 2. Finally create 3 more blocks.
#from ethereum.hybrid_casper import chain
# {validatorkey: deposit_val,}

from ethereum.tools import tester
from ethereum.common import verify_execution_results, mk_block_from_prevstate, set_execution_results
from ethereum import utils

# hybrid casper + casper utils, all in NEW casper contract
#from <INSERT HERE> import casper_init_txs, validation_code_addr_from_privkey, call_casper
from ethereum.hybrid_casper import casper_utils, validator
from ethereum.tools.testing_lang import TestLang
import math
import re

#validator_lookup_map = {validation_code_addr_from_privkey(sha3(str(i))): i for i in range(20)}

# TODO: SPHINX DOCUMENTATION
# TODO: Add balance for validator accounts?
# FOR NOW, ADD export PYTHONPATH="***serpent module path***" in order to successfully run
# MAYBE: d0, d1, d2, d3, d4, d5, d6, d7, d8, d9 = deposits[:10]

# Modify at your will
EPOCH_LENGTH = 25
SLASH_DELAY = 864
INTEREST_FACTOR = 0.02
PENALTY_FACTOR = 0.002
ALLOC = {a: {'balance': 5*10**19} for a in tester.accounts[:10]}
k0, k1, k2, k3, k4, k5, k6, k7, k8, k9 = tester.keys[:10]
a0, a1, a2, a3, a4, a5, a6, a7, a8, a9 = tester.accounts[:10]

# simplified version of prepare for testing_lang needs (slashing funcs)
class PrepareMsg():
    def __init__(self, epoch, blockhash):
        self.epoch = epoch
        self.blockhash = blockhash

# simplified version of commit for testing_lang needs (slashing funcs)
class CommitMsg():
    def __init__(self, epoch, epoch_source):
        self.epoch = epoch
        self.epoch_source = epoch_source

# validator object mainly for keeping track of prepare messages to check for slashing condition violations
class Validator:
    def __init__(self, key, validator_index):
        #self.prepare_msgs = [] #list of PrepareMsg objects, TODO: every time we call prepare from Validator X, add the prepare msg to the prepare msg list of this validator
        self.processed = {}
        self.prepare_map = {} # {epoch: prepare in that epoch}
        self.commit_incompatible_map = {} # {epoch: commit incompatible with that epoch}
        self.evidence = None
        self.key = key
        self.val_index = validator_index

class TestLangHybrid(TestLang):
    # For a custom Casper parser, overload generic parser and construct your chain
    def __init__(self, test):
        # Initializes hybrid casper chain + tester
        #
        self.genesis = casper_utils.make_casper_genesis(ALLOC, EPOCH_LENGTH, SLASH_DELAY, INTEREST_FACTOR, PENALTY_FACTOR)
        #self.epoch_num = 0 #starts at 0 or 1?
        self.t = tester.Chain(genesis=self.genesis)
        self.casper = tester.ABIContract(self.t, casper_utils.casper_abi, self.t.chain.env.config['CASPER_ADDRESS'])
        # self.casper.initiate() #FIXME: L35-36 copied from init_chain_and_casper, don't really get 35-36 lol
        self.test = test # the testinglang string
        self.saved_checkpoints = dict()
        self.prev_commit_epoch = 0
        #self.active_validators = [] #list of active validators 0-9
        self.active_validators = {} #TODO: IMPLEMENT MEMBER VARIABLES AS WE DO PROCESS_PREPARE, {0 : Validator(0), 1: Validator(1)}
        self.t.mine(1)
        self.val_index = 0
        # initialize 10 validator keys/accounts
        self.k0, self.k1, self.k2, self.k3, self.k4, self.k5, self.k6, self.k7, self.k8, self.k9 = tester.keys[:10]
        self.a0, self.a1, self.a2, self.a3, self.a4, self.a5, self.a6, self.a7, self.a8, self.a9 = tester.accounts[:10]
        #init_val_addr = utils.privtoaddr(k0)
        #init_val_valcode_addr = utils.mk_contract_address(init_val_addr, 2) #second parameter == nonce; does this matter?
        #validators = [validator.Validator(k0, copy.deepcopy(genesis), network, valcode_addr=init_val_valcode_addr)]
        self._e, self._a, self._se, self._sa = None, None, None, None

    def get_ancestry_hash(self, state, epoch, source_epoch, source_ancestry_hash):
        if epoch == 0:
            return source_ancestry_hash
        ancestry_hash = source_ancestry_hash
        for i in range(source_epoch, epoch):
            ancestry_hash = utils.sha3(self.epoch_blockhash(state, i) + ancestry_hash)
        return ancestry_hash

    # Helper function for gettting blockhashes by epoch, based on the current chain
    def epoch_blockhash(self, epoch):
        if epoch == 0:
            return b'\x00' * 32
        return self.t.head_state.prev_headers[epoch*EPOCH_LENGTH * -1 - 1].hash

    # Mines blocks required for number_of_epochs epoch changes, plus an offset of 2 blocks
    def mine_epochs(self, number_of_epochs):
        distance_to_next_epoch = (EPOCH_LENGTH - self.t.head_state.block_number) % EPOCH_LENGTH
        number_of_blocks = distance_to_next_epoch + EPOCH_LENGTH*(number_of_epochs-1) + 2
        self.t.mine(number_of_blocks=number_of_blocks)

    def process_prepare(self, p, v):
        if p.blockhash in v.processed:
            return
        if p.epoch in v.prepare_map:
            v.evidence = (p, v.prepare_map[p.epoch])
            return
        if p.epoch in v.commit_incompatible_map:
            v.evidence = (p, v.commit_incompatible_map[p.epoch])
            return
        v.prepare_map[p.epoch] = p

    def process_commit(self, c, v):
        print (c.epoch_source)
        for e in range(c.epoch_source + 1, c.epoch):
            if e in v.prepare_map:
                v.evidence = (v.prepare_map[e], c)
                return
            v.commit_incompatible_map[e] = c

    def parse(self):
        if self.test == '':
            raise Exception("Please pass in a valid test string")
        for token in self.test.split(' '):
            letters, numbers = re.match('([A-Za-z]*)([0-9]*)', token).groups()
            if letters+numbers != token:
                raise Exception("Bad token: %s" % token)
            if numbers != '':
                numbers = int(numbers)
            # Mines X blocks to the current head
            # If no number specified, adds an epoch of blocks [EPOCH_LENGTH]
            # t.mine(number_of_blocks=number)
            if letters == 'B':
                if numbers == '':
                    self.mine_epochs(number_of_epochs=1)
                    print ("No number of blocks specified, Mining 1 epoch to curr HEAD")
                else:
                    print ("Mining " + str(numbers) + " blocks to curr HEAD")
                    self.t.mine(numbers)

            # Adds a join transaction (eg. "J5" adds a join for validator 5)
            # Deposit + join txs ONLY. Need to explicitly mine epochs using login rule for logging in validators
            # test_chain.py L39-42
            # btw, J1 J2 J3 J4 J5 B should hit gas limit + script should explicitly mine blocks for this reason
            if letters == 'J':
                if numbers == '':
                    raise Exception("Need to specify validator number for join")
                elif numbers <= 0:
                    raise Exception("Invalid validator specified: %s" % str(numbers))
                else:
                    print ("Joining validator " + str(numbers))
                    #Add validators to map of active validators 0-9
                    if numbers not in self.active_validators:
                        self.active_validators[numbers] = Validator(tester.keys[numbers], self.val_index)
                        casper_utils.induct_validator(self.t, self.casper, tester.keys[numbers], 3 * 10**18)
                        self.val_index += 1
                    else:
                        raise Exception("Already joined this validator")


            # Submits a prepare transaction for validator X.
            # X needs to be an active validator otherwise throws exception.
            # Can you prepare in the middle of an epoch? What is the point
            if letters == 'P':
                if numbers == '':
                    raise Exception("Need to specify validator number for prepare")
                elif numbers <= 0:
                    raise Exception("Invalid validator specified: %s" % str(numbers))
                elif numbers not in self.active_validators:
                    raise Exception("Not an active validator: %s" % str(numbers))
                else:
                    # updates current epoch (Removedself.epoch_num bc of self.casper.get_current_epoch())
                    # self.epoch_num = int(self.t.head_state.block_number / EPOCH_LENGTH)
                    #FIXME: IMPLEMENT DYNASTY FOR THE ANC_BLOCKHASH... what is source blockhash/source anc_blockhash

                    # MIGHT NOT NEED (VALIDATOR.PY): updates source epoch
                    # if self.t.checkpoint_head_hash != b'\x00'*32:
                    #     source_epoch = self.t.get_block(self.t.checkpoint_head_hash).header.number // EPOCH_LENGTH
                    # else:
                    #     source_epoch = 0

                    # get source ancestry hash
                    #source_ancestry_hash = self.casper.get_justified_ancestry_hashes(source_epoch)

                    #get ancestry hash
                    #ancestry_hash = self.get_ancestry_hash(source_ancestry_hash)
                    self._e, self._a, self._se, self._sa = \
                        self.casper.get_current_epoch(), self.casper.get_recommended_ancestry_hash(), \
                        self.casper.get_recommended_source_epoch(), self.casper.get_recommended_source_ancestry_hash()

                    self.casper.prepare(casper_utils.mk_prepare(self.active_validators[numbers].val_index, self._e, self._a, self._se, self._sa, tester.keys[numbers]))
                    p = PrepareMsg(self._e, self.epoch_blockhash(self._e))
                    self.process_prepare(p, self.active_validators[numbers])

                    print ("Submitting prepare for validator " + str(numbers))

            # Submits a commit transaction for validator X.
            # X needs to be an active validator otherwise throws exception.
            if letters == 'C':
                if numbers == '':
                    raise Exception("Need to specify validator number for commit")
                elif numbers <= 0:
                    raise Exception("Invalid validator specified: %s" % str(numbers))
                elif numbers not in self.active_validators:
                    raise Exception("Not an active validator: %s" % str(numbers))
                else:
                    #_e, _a = self.casper.get_current_epoch(), self.casper.get_recommended_ancestry_hash()

                    self.casper.commit(casper_utils.mk_commit(self.active_validators[numbers].val_index, self._e, self._a, self.prev_commit_epoch, tester.keys[numbers]))
                    # update prev_commit_epoch to current epoch
                    self.prev_commit_epoch = self._e



                    c = CommitMsg(self._e, self._se)
                    self.process_commit(c, self.active_validators[numbers])
                    print ("Submitting commit for validator " + str(numbers))

            # Submits a commit transaction for validator X.
            # X needs to be an active validator otherwise throws exception.
            if letters == 'R':
                if numbers == '':
                    raise Exception("Need to specify valid checkpoint number")
                elif numbers <= 0:
                    raise Exception("Invalid checkpoint specified: %s" % str(numbers))
                elif numbers not in self.saved_checkpoints:
                    raise Exception("Not a saved checkpoint: %s" % str(numbers))
                else:
                    print ("Reverting to checkpoint " + str(numbers))
                    print(type(self.saved_checkpoints[numbers]))
                    print(self.saved_checkpoints[numbers])
                    print(self.t.chain.get_block(self.saved_checkpoints[numbers]).hash)
                    self.t.change_head(self.saved_checkpoints[numbers])

            # Saves a checkpoint
            # Needs epoch to save a checkpoint
            if letters == 'S':
                if numbers == '':
                    raise Exception("Need to specify valid save number")

                else:
                    print ("Saving checkpoint " + str(numbers))
                    #
                    self.saved_checkpoints[numbers] = self.t.head_state.prev_headers[-1].hash

            # # Searches through specified validator's messages for messages that violate slashing condition.
            # # If there are a pair of messages that violate a slashing condition, we can run a slashing transaction on the validator on that chain.
            # # Otherwise, throw an exception.
            # if letters == 'X'
            #     if numbers == '':
            #         raise Exception("Need to specify valid validator number to check slashing")
            #     #grab validator
            #     v = self.active_validators[numbers]
            #     if v.evidence is not None: #There is evidence
