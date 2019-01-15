from ethereum.tools import tester
from ethereum.utils import encode_hex, privtoaddr
from ethereum.hybrid_casper import casper_utils
import re

ALLOC = {a: {'balance': 500*10**19} for a in tester.accounts[:10]}

class Validator(object):
    def __init__(self, withdrawal_addr, key):
        self.withdrawal_addr = withdrawal_addr
        self.key = key
        self.prepare_map = {}  # {epoch: prepare in that epoch}
        self.commit_map = {}  # {epoch: commit incompatible with that epoch}
        self.uncommittable_epochs = {}
        self.double_prepare_evidence = []
        self.prepare_commit_consistency_evidence = []

    def get_recommended_casper_msg_contents(self, casper, validator_index):
        return \
            casper.get_current_epoch(), casper.get_recommended_ancestry_hash(), \
            casper.get_recommended_source_epoch(), casper.get_recommended_source_ancestry_hash(), \
            casper.get_validators__prev_commit_epoch(validator_index)

    def prepare(self, casper):
        validator_index = self.get_validator_index(casper)
        _e, _a, _se, _sa, _pce = self.get_recommended_casper_msg_contents(casper, validator_index)
        prepare_msg = casper_utils.mk_prepare(validator_index, _e, _a, _se, _sa, self.key)
        if _e in self.prepare_map and self.prepare_map[_e] != prepare_msg:
            print('Found double prepare for validator:', encode_hex(self.withdrawal_addr))
            self.double_prepare_evidence.append(self.prepare_map[_e])
            self.double_prepare_evidence.append(prepare_msg)
        for i in range(_se+1, _e-1):
            self.uncommittable_epochs[i] = prepare_msg
            if i in self.commit_map:
                print('Found prepare commit consistency in prepare for validator:', encode_hex(self.withdrawal_addr))
                self.prepare_commit_consistency_evidence.append(prepare_msg)
                self.prepare_commit_consistency_evidence.append(self.commit_map[i])
        self.prepare_map[_e] = prepare_msg
        casper.prepare(prepare_msg)

    def commit(self, casper):
        validator_index = self.get_validator_index(casper)
        _e, _a, _se, _sa, _pce = self.get_recommended_casper_msg_contents(casper, validator_index)
        commit_msg = casper_utils.mk_commit(validator_index, _e, _a, _pce, self.key)
        self.commit_map[_e] = commit_msg
        if _e in self.uncommittable_epochs:
                print('Found prepare commit consistency in commit for validator:', encode_hex(self.withdrawal_addr))
                self.prepare_commit_consistency_evidence.append(self.uncommittable_epochs[_e])
                self.prepare_commit_consistency_evidence.append(commit_msg)
        casper.commit(commit_msg)

    def slash(self, casper):
        if len(self.double_prepare_evidence) > 0:
            casper.double_prepare_slash(self.double_prepare_evidence[0], self.double_prepare_evidence[1])
        elif len(self.prepare_commit_consistency_evidence) > 0:
            casper.prepare_commit_inconsistency_slash(self.prepare_commit_consistency_evidence[0], self.prepare_commit_consistency_evidence[1])
        else:
            raise Exception('No slash evidence found')
        print('Slashed validator:', encode_hex(self.withdrawal_addr))

    def get_validator_index(self, casper):
        if self.withdrawal_addr is None:
            raise Exception('Valcode address not set')
        try:
            return casper.get_validator_indexes(self.withdrawal_addr)
        except tester.TransactionFailed:
            return None

class TestLangHybrid(object):
    # For a custom Casper parser, overload generic parser and construct your chain
    def __init__(self, test_string, epoch_length, withdrawal_delay, base_interest_factor, base_penalty_factor):
        if test_string == '':
            raise Exception("Please pass in a valid test string")
        self.test_string = test_string
        self.genesis = casper_utils.make_casper_genesis(ALLOC, epoch_length, withdrawal_delay, base_interest_factor, base_penalty_factor)
        self.t = tester.Chain(genesis=self.genesis)
        self.casper = tester.ABIContract(self.t, casper_utils.casper_abi, self.t.chain.env.config['CASPER_ADDRESS'])
        self.saved_blocks = dict()
        self.validators = dict()
        # Register token handlers
        self.handlers = dict()
        self.handlers['B'] = self.mine_blocks
        self.handlers['J'] = self.join
        self.handlers['P'] = self.prepare
        self.handlers['C'] = self.commit
        self.handlers['S'] = self.save_block
        self.handlers['R'] = self.revert_to_block
        self.handlers['H'] = self.check_head_equals_block
        self.handlers['X'] = self.slash

    def mine_blocks(self, number):
        if number == '':
            print ("No number of blocks specified, Mining 1 epoch to curr HEAD")
            self.mine_epochs(number_of_epochs=1)
        else:
            print ("Mining " + str(number) + " blocks to curr HEAD")
            self.t.mine(number)

    def join(self, number):
        withdrawal_addr = privtoaddr(tester.keys[number])
        casper_utils.induct_validator(self.t, self.casper, tester.keys[number], 200 * 10**18)
        self.validators[number] = Validator(withdrawal_addr, tester.keys[number])

    def prepare(self, validator_index):
        self.validators[validator_index].prepare(self.casper)

    def commit(self, validator_index):
        self.validators[validator_index].commit(self.casper)

    def slash(self, validator_index):
        self.validators[validator_index].slash(self.casper)

    def save_block(self, saved_block_id):
        if saved_block_id in self.saved_blocks:
            raise Exception('Checkpoint {} already exists'.format(saved_block_id))
        blockhash = self.t.head_state.prev_headers[0].hash
        self.saved_blocks[saved_block_id] = blockhash
        print('Saving checkpoint with hash: {}'.format(encode_hex(self.saved_blocks[saved_block_id])))

    def revert_to_block(self, saved_block_id):
        if saved_block_id not in self.saved_blocks:
            raise Exception('Checkpoint {} does not exist'.format(saved_block_id))
        blockhash = self.saved_blocks[saved_block_id]
        self.t.change_head(blockhash)
        print('Reverting to checkpoint with hash: {}'.format(encode_hex(self.saved_blocks[saved_block_id])))

    def check_head_equals_block(self, saved_block_id):
        if saved_block_id not in self.saved_blocks:
            raise Exception('Checkpoint {} does not exist'.format(saved_block_id))
        blockhash = self.saved_blocks[saved_block_id]
        print('Saved num: {} - Chain head num: {}'.format(self.t.chain.get_block(blockhash).number, self.t.chain.head.number))
        assert self.t.chain.head_hash == blockhash
        print('Passed assert H{}'.format(saved_block_id))

    def parse(self):
        for token in self.test_string.split(' '):
            letter, number = re.match('([A-Za-z]*)([0-9]*)', token).groups()
            if letter+number != token:
                raise Exception("Bad token: %s" % token)
            if number != '':
                number = int(number)
            self.handlers[letter](number)

    # Mines blocks required for number_of_epochs epoch changes, plus an offset of 2 blocks
    def mine_epochs(self, number_of_epochs):
        epoch_length = self.t.chain.config['EPOCH_LENGTH']
        distance_to_next_epoch = (epoch_length - self.t.head_state.block_number) % epoch_length
        number_of_blocks = distance_to_next_epoch + epoch_length*(number_of_epochs-1) + 2
        return self.t.mine(number_of_blocks=number_of_blocks)
