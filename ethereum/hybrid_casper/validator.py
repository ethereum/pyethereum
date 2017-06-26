import copy
from ethereum.hybrid_casper import casper_utils, chain
from ethereum.pow.ethpow import Miner
from ethereum.tools import tester
from ethereum.meta import make_head_candidate
from ethereum import block, transactions
from ethereum.transaction_queue import TransactionQueue
from ethereum.messages import apply_transaction
from ethereum import abi, utils
# from ethereum.slogging import get_logger, configure_logging
# config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace,eth.pb.msg:trace,eth.pb.tx:debug'
# configure_logging(config_string=config_string)

class Network(object):
    def __init__(self):
        self.nodes = []
        self.time = 0

    # TODO: Add the concept of *time* or add block dependency handling
    def broadcast(self, msg):
        for n in self.nodes:
            n.on_receive(msg)

    def join(self, node):
        self.nodes.append(node)

class Validator(object):
    def __init__(self, key, genesis, network, valcode_addr=None, mining=False):
        self.key = key
        self.coinbase = utils.privtoaddr(self.key)
        self.chain = chain.Chain(genesis=genesis, coinbase=self.coinbase, new_head_cb=self._on_new_head)
        self.mining = mining
        self.nonce = self.chain.state.get_nonce(self.coinbase)
        self.valcode_tx = None
        self.deposit_tx = None
        self.valcode_addr = valcode_addr
        self.prepares = dict()
        self.prev_commit_epoch = 0
        self.epoch_length = self.chain.env.config['EPOCH_LENGTH']
        # self.commits = dict()
        # When the transaction_queue is modified, we must set
        # self._head_candidate_needs_updating to True in order to force the
        # head candidate to be updated.
        self.transaction_queue = TransactionQueue()
        self._head_candidate_needs_updating = True
        # Add validator to the network
        self.network = network
        self.network.join(self)

    @property
    def head_candidate(self):
        if self._head_candidate_needs_updating:
            self._head_candidate_needs_updating = False
            # Make a copy of self.transaction_queue because
            # make_head_candidate modifies it.
            txqueue = copy.deepcopy(self.transaction_queue)
            self._head_candidate, self._head_candidate_state = make_head_candidate(
                self.chain, txqueue=txqueue, timestamp=self.chain.state.timestamp + 14)
        return self._head_candidate

    def _on_new_head(self, block):
        self.transaction_queue = self.transaction_queue.diff(block.transactions)
        self._head_candidate_needs_updating = True

    def epoch_blockhash(self, state, epoch):
        if epoch == 0:
            return b'\x00' * 32
        return state.prev_headers[epoch*self.epoch_length * -1 - 1].hash

    def get_ancestry_hash(self, state, epoch, source_epoch, source_ancestry_hash):
        if epoch == 0:
            return source_ancestry_hash
        ancestry_hash = source_ancestry_hash
        for i in range(source_epoch, epoch):
            ancestry_hash = utils.sha3(self.epoch_blockhash(state, i) + ancestry_hash)
        return ancestry_hash

    def get_validator_index(self, state):
        t = tester.State(state.ephemeral_clone())
        casper = tester.ABIContract(t, casper_utils.casper_abi, self.chain.casper_address)
        try:
            return casper.get_validator_indexes(self.valcode_addr)
        except tester.TransactionFailed:
            return None

    # Check the state, and determine if we should commit or prepare
    def on_receive(self, msg):
        if isinstance(msg, block.Block):
            self.accept_block(msg)
        elif isinstance(msg, transactions.Transaction):
            self.accept_transaction(msg)

    def accept_block(self, block):
        self.chain.process_parent_queue()
        if not self.chain.add_block(block):
            print('Block failed to add:', block.hash)
            return
        # Create a poststate based on the blockhash we recieved
        post_state = self.chain.mk_poststate_of_blockhash(block.hash)
        # Generate prepare & commit messages and broadcast if possible
        prepare_msg = self.get_prepare_message(post_state)
        if prepare_msg:
            prepare_tx = self.mk_prepare_tx(prepare_msg)
            self.broadcast_transaction(prepare_tx)
        commit_msg = self.get_commit_message(post_state)
        if commit_msg:
            commit_tx = self.mk_commit_tx(commit_msg)
            self.broadcast_transaction(commit_tx)
        print('Block added.', block.hash, 'Head:', self.chain.head_hash)

    def accept_transaction(self, tx):
        if self.mining:
            self.transaction_queue.add_transaction(tx)
            self.mine_and_broadcast_blocks(1)

    def broadcast_transaction(self, tx):
        self.network.broadcast(tx)

    def broadcast_newblock(self, block):
        print('Block hash:', block.hash)
        print('Block txs:', block.transactions)
        self.network.broadcast(block)

    def get_prepare_message(self, state):
        epoch = state.block_number // self.epoch_length
        # Don't prepare if we have already or if we don't have EPOCH_LENGTH/3 or more blocks in this epoch
        if epoch in self.prepares or state.block_number % self.epoch_length < self.epoch_length // 3:
            return False
        if self.chain.checkpoint_head_hash:
            source_epoch = self.chain.get_block(self.chain.checkpoint_head_hash).header.number // self.epoch_length
        else:
            source_epoch = 0
        # Check for PREPARE_COMMIT_CONSISTENCY
        if source_epoch < self.prev_commit_epoch and self.prev_commit_epoch < epoch:
            return False
        # Create a Casper contract which we can use to get related values
        casper = tester.ABIContract(tester.State(state), casper_utils.casper_abi, self.chain.casper_address)
        # Get the ancestry hash and source ancestry hash
        source_ancestry_hash = casper.get_justified_ancestry_hashes(source_epoch)
        ancestry_hash = self.get_ancestry_hash(state, epoch, source_epoch, source_ancestry_hash)
        prepare_msg = casper_utils.mk_prepare(self.get_validator_index(state), epoch, self.epoch_blockhash(state, epoch),
                                              ancestry_hash, source_epoch, source_ancestry_hash, self.key)
        try:  # Attempt to submit the prepare, to make sure that it doesn't doesn't violate DBL_PREPARE & it is justified
            casper.prepare(prepare_msg)
        except tester.TransactionFailed:
            print('Prepare failed')
            return False
        # Save the prepare message we generated
        self.prepares[epoch] = prepare_msg
        print('Submitted Prepare:', self.get_validator_index(state), epoch, self.epoch_blockhash(state, epoch), self.prev_commit_epoch)
        return prepare_msg

    def get_commit_message(self, state):
        epoch = state.block_number // self.epoch_length
        # Don't commit if we have already or if we don't have EPOCH_LENGTH/2 or more blocks in this epoch
        if state.block_number % self.epoch_length < self.epoch_length // 2:
            return False
        # Create a Casper contract which we can use to get related values
        casper = tester.ABIContract(tester.State(state), casper_utils.casper_abi, self.chain.casper_address)
        # Make the commit message
        commit_msg = casper_utils.mk_commit(self.get_validator_index(state), epoch, self.epoch_blockhash(state, epoch),
                                            self.prev_commit_epoch, self.key)
        try:  # Attempt to submit the commit, to make sure that it doesn't doesn't violate DBL_PREPARE & it is justified
            casper.commit(commit_msg)
        except tester.TransactionFailed:
            print('Commit failed')
            return False
        # Save the commit as now our last commit epoch
        self.prev_commit_epoch = epoch
        print('Submitted Commit:', self.get_validator_index(state), epoch, self.epoch_blockhash(state, epoch), self.prev_commit_epoch)
        return commit_msg

    def mine_and_broadcast_blocks(self, number_of_blocks=1):
        for i in range(number_of_blocks):
            self._head_candidate_needs_updating = True
            block = Miner(self.head_candidate).mine(rounds=100, start_nonce=0)
            print('Did we add block? ', self.chain.add_block(block))
            print('mining a new block with hash:', utils.encode_hex(block.hash), '\nand prevhash:', utils.encode_hex(block.header.prevhash))
            print('mining a new block my head is:', utils.encode_hex(self.chain.head_hash))
            self.transaction_queue = self.transaction_queue.diff(block.transactions)
            self.broadcast_newblock(block)

    def broadcast_deposit(self):
        if not self.valcode_tx or not self.deposit_tx:
            # Generate transactions
            valcode_tx = self.mk_validation_code_tx()
            valcode_addr = utils.mk_contract_address(self.coinbase, self.nonce)
            deposit_tx = self.mk_deposit_tx(3 * 10**18, valcode_addr)
            # Verify the transactions pass
            temp_state = self.chain.state.ephemeral_clone()
            valcode_success, o1 = apply_transaction(temp_state, valcode_tx)
            deposit_success, o2 = apply_transaction(temp_state, deposit_tx)
            print(valcode_success)
            print(deposit_success)
            if not (valcode_success and deposit_success):
                self.nonce = self.chain.state.get_nonce(self.coinbase)
                print(o1)
                print(o2)
                raise Exception('Valcode tx or deposit tx failed')
            self.valcode_tx = valcode_tx
            self.valcode_addr = valcode_addr
            self.deposit_tx = deposit_tx
        self.broadcast_transaction(self.valcode_tx)
        self.broadcast_transaction(self.deposit_tx)

    def mk_validation_code_tx(self):
        valcode_tx = self.mk_transaction('', 0, casper_utils.mk_validation_code(self.coinbase))
        return valcode_tx

    def mk_deposit_tx(self, value, valcode_addr):
        casper_ct = abi.ContractTranslator(casper_utils.casper_abi)
        deposit_func = casper_ct.encode('deposit', [valcode_addr, self.coinbase])
        deposit_tx = self.mk_transaction(self.chain.casper_address, value, deposit_func)
        return deposit_tx

    def mk_prepare_tx(self, prepare_msg):
        casper_ct = abi.ContractTranslator(casper_utils.casper_abi)
        prepare_func = casper_ct.encode('prepare', [prepare_msg])
        prepare_tx = self.mk_transaction(to=self.chain.casper_address, value=0, data=prepare_func)
        return prepare_tx

    def mk_commit_tx(self, commit_msg):
        casper_ct = abi.ContractTranslator(casper_utils.casper_abi)
        commit_func = casper_ct.encode('commit', [commit_msg])
        commit_tx = self.mk_transaction(self.chain.casper_address, 0, commit_func)
        return commit_tx

    def mk_transaction(self, to=b'\x00' * 20, value=0, data=b'', gasprice=tester.GASPRICE, startgas=tester.STARTGAS):
        tx = transactions.Transaction(self.nonce, gasprice, startgas, to, value, data).sign(self.key)
        self.nonce += 1
        return tx
