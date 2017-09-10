from ethereum.tools import tester
from ethereum.utils import encode_hex
from ethereum.hybrid_casper import casper_utils
import re

ALLOC = {a: {'balance': 500*10**19} for a in tester.accounts[:10]}

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
        # Register token handlers
        self.handlers = dict()
        self.handlers['B'] = self.handle_B
        self.handlers['J'] = self.handle_J
        self.handlers['P'] = self.handle_P
        self.handlers['C'] = self.handle_C
        self.handlers['S'] = self.handle_S
        self.handlers['R'] = self.handle_R
        self.handlers['H'] = self.handle_H

    def handle_B(self, number):
        if number == '':
            print ("No number of blocks specified, Mining 1 epoch to curr HEAD")
            self.mine_epochs(number_of_epochs=1)
        else:
            print ("Mining " + str(number) + " blocks to curr HEAD")
            self.t.mine(number)

    def handle_J(self, number):
        casper_utils.induct_validator(self.t, self.casper, tester.keys[number], 200 * 10**18)

    def handle_P(self, validator_index):
        _e, _a, _se, _sa, _pce = self.get_recommended_casper_msg_contents(validator_index)
        self.casper.prepare(casper_utils.mk_prepare(validator_index, _e, _a, _se, _sa, tester.keys[validator_index]))

    def handle_C(self, validator_index):
        _e, _a, _se, _sa, _pce = self.get_recommended_casper_msg_contents(validator_index)
        self.casper.commit(casper_utils.mk_commit(validator_index, _e, _a, _pce, tester.keys[validator_index]))

    def handle_S(self, saved_block_id):
        if saved_block_id in self.saved_blocks:
            raise Exception('Checkpoint {} already exists'.format(saved_block_id))
        blockhash = self.t.head_state.prev_headers[0].hash
        self.saved_blocks[saved_block_id] = blockhash
        print('Saving checkpoint with hash: {}'.format(encode_hex(self.saved_blocks[saved_block_id])))

    def handle_R(self, saved_block_id):
        if saved_block_id not in self.saved_blocks:
            raise Exception('Checkpoint {} does not exist'.format(saved_block_id))
        blockhash = self.saved_blocks[saved_block_id]
        self.t.change_head(blockhash)
        print('Reverting to checkpoint with hash: {}'.format(encode_hex(self.saved_blocks[saved_block_id])))

    def handle_H(self, saved_block_id):
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

    def get_recommended_casper_msg_contents(self, validator_index):
        return \
            self.casper.get_current_epoch(), self.casper.get_recommended_ancestry_hash(), \
            self.casper.get_recommended_source_epoch(), self.casper.get_recommended_source_ancestry_hash(), \
            self.casper.get_validators__prev_commit_epoch(validator_index)

    # Mines blocks required for number_of_epochs epoch changes, plus an offset of 2 blocks
    def mine_epochs(self, number_of_epochs):
        epoch_length = self.t.chain.config['EPOCH_LENGTH']
        distance_to_next_epoch = (epoch_length - self.t.head_state.block_number) % epoch_length
        number_of_blocks = distance_to_next_epoch + epoch_length*(number_of_epochs-1) + 2
        return self.t.mine(number_of_blocks=number_of_blocks)
