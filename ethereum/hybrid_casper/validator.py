import copy
import time
from ethereum.hybrid_casper import casper_utils, chain
from ethereum.tools import tester
from ethereum.meta import make_head_candidate
from ethereum import block, transactions
from ethereum.transaction_queue import TransactionQueue
from ethereum import abi, utils

class Network(object):
    def __init__(self):
        self.nodes = []
        self.time = 0

    def broadcast(self, msg):
        for n in self.nodes:
            n.on_receive(msg)

    def join(self, node):
        self.nodes.append(node)

class Validator(object):
    def __init__(self, key, genesis, network, mining=False):
        self.key = key
        self.coinbase = utils.privtoaddr(self.key)
        self.chain = chain.Chain(genesis=genesis, coinbase=self.coinbase, new_head_cb=self._on_new_head)
        self.mining = mining
        self.nonce = self.chain.state.get_nonce(self.coinbase)
        self.valcode_tx = None
        self.deposit_tx = None
        # When the transaction_queue is modified, we must set
        # self._head_candidate_needs_updating to True in order to force the
        # head candidate to be updated.
        self.transaction_queue = TransactionQueue()
        self._head_candidate_needs_updating = True
        # Add validator to the network
        self.network = network
        self.network.join(self)

    def broadcast_transaction(self, tx):
        self.network.broadcast(tx)

    def broadcast_newblock(self, block):
        pass

    def _on_new_head(self, block):
        self.transaction_queue = self.transaction_queue.diff(block.transactions)
        self._head_candidate_needs_updating = True

    @property
    def head_candidate(self):
        if self._head_candidate_needs_updating:
            self._head_candidate_needs_updating = False
            # Make a copy of self.transaction_queue because
            # make_head_candidate modifies it.
            txqueue = copy.deepcopy(self.transaction_queue)
            self._head_candidate, self._head_candidate_state = make_head_candidate(
                self.chain, txqueue, timestamp=int(time.time()))
        return self._head_candidate

    def should_prepare(self, state):
        # casper = tester.ABIContract(tester.State(state), casper_utils.casper_abi, self.chain.casper_address)
        return False

    def should_commit(self, state):
        return False

    def should_deposit(self, state):
        # TODO: Instead of assuming only one chain, actually test the state to see if we have deposited here or if we need to re-broadcast
        if not self.deposit_tx:
            return True
        return False

    def accept_block(self, block):
        # TODO: Add logic which only adds blocks if we can trace it back to the full chain
        self.chain.add_block(block)
        post_state = self.chain.mk_poststate_of_blockhash(block.hash)
        if self.should_prepare(post_state):
            pass
        if self.should_commit(post_state):
            pass
        if self.should_deposit(post_state):
            print('DEPOSITING')
            self.broadcast_deposit()
        # print('Block added. Head:', self.chain.head_hash)

    def accept_transaction(self, tx):
        print('ACCEPTED TX!')
        if tx.hash in self.transaction_queue.txs:
            return
        if self.mining:
            self._head_candidate_needs_updating = True
            self.broadcast_newblock(self.head_candidate)
            self.chain.add_block(self.head_candidate)

    # Check the state, and determine if we should commit or prepare
    def on_receive(self, msg):
        if isinstance(msg, block.Block):
            self.accept_block(msg)
        elif isinstance(msg, transactions.Transaction):
            self.accept_transaction(msg)
        # print('In on receive! Head:', self.chain.head_hash)

    def mk_validation_code_tx(self):
        valcode_tx = self.mk_transaction('', 0, casper_utils.mk_validation_code(self.coinbase))
        return valcode_tx

    def mk_deposit_tx(self, value, valcode_addr):
        casper_ct = abi.ContractTranslator(casper_utils.casper_abi)
        deposit_func = casper_ct.encode('deposit', [valcode_addr, self.coinbase])
        deposit_tx = self.mk_transaction(self.chain.casper_address, value, deposit_func)
        return deposit_tx

    def broadcast_deposit(self):
        if not self.valcode_tx or not self.deposit_tx:
            self.valcode_tx = self.mk_validation_code_tx()
            valcode_addr = utils.mk_contract_address(self.coinbase, self.nonce-1)
            self.deposit_tx = self.mk_deposit_tx(3 * 10**18, valcode_addr)
        self.broadcast_transaction(self.valcode_tx)
        self.broadcast_transaction(self.deposit_tx)

    def mk_transaction(self, to=b'\x00' * 20, value=0, data=b'', gasprice=tester.GASPRICE, startgas=tester.STARTGAS):
        tx = transactions.Transaction(self.nonce, gasprice, startgas, '', value, data).sign(self.key)
        self.nonce += 1
        return tx

    # def mk_deposit_transactions(self, value):
    #     nonce = self.chain.state.get_nonce(self.coinbase)
    #     valcode_tx = transactions.Transaction(nonce, tester.GASPRICE, tester.STARTGAS,
    #                                           '', 0, casper_utils.mk_validation_code(self.coinbase)).sign(self.key)
    #     valcode_addr = utils.mk_contract_address(self.coinbase, nonce)
    #     return valcode_tx, deposit_tx

        # t = tester.State(self.chain.state.ephemeral_clone())
        # casper = tester.ABIContract(t, casper_utils.casper_abi, self.chain.casper_address)
        # valcode_addr, valcode_tx = t.tx(self.key, '', 0, casper_utils.mk_validation_code(self.coinbase), return_tx=True)
        # casper.deposit(valcode_addr, self.coinbase, value=value)
        # self.validator_index = casper.get_nextValidatorIndex() - 1
        # self.valcode_addr = valcode_addr
        # return valcode_tx, deposit_tx

    # def prepare(self, epoch, source_epoch):
    #     self.ancestry_hash[epoch] = utils.sha3(epoch_blockhash(t, epoch), self.ancestry_hash[source_epoch])
    #     casper.prepare(mk_prepare(self.validator_index, epoch, epoch_blockhash(self.t, epoch),
    #                               self.ancestry_hash[source_epoch], source_epoch, self.ancestry_hash[source_epoch], self.key))
