from ethereum.hybrid_casper import casper_utils, chain
from ethereum.tools import tester
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
    def __init__(self, key, genesis, network):
        self.key = key
        self.coinbase = utils.privtoaddr(self.key)
        self.chain = chain.Chain(genesis=genesis, coinbase=self.coinbase, new_head_cb=self._on_new_head)
        # When the transaction_queue is modified, we must set
        # self._head_candidate_needs_updating to True in order to force the
        # head candidate to be updated.
        self.transaction_queue = TransactionQueue()
        self._head_candidate_needs_updating = True
        # Add validator to the network
        network.join(self)

    def broadcast_transaction(self, tx):
        self.network.broadcast(tx)

    def broadcast_newblock(self, block):
        pass

    def _on_new_head(self, block):
        # self.transaction_queue = self.transaction_queue.diff(block.transactions)
        # self._head_candidate_needs_updating = True
        # for cb in self.on_new_head_cbs:
        #     cb(block)
        pass

    def should_prepare(self, state):
        # casper = tester.ABIContract(tester.State(state), casper_utils.casper_abi, self.chain.casper_address)
        return False

    def should_commit(self, state):
        return False

    def accept_block(self, block):
        # TODO: Add logic which only adds blocks if we can trace it back to the full chain
        self.chain.add_block(block)
        post_state = self.chain.mk_poststate_of_blockhash(block.hash)
        if self.should_prepare(post_state):
            pass
        if self.should_commit(post_state):
            pass
        print('Block added. Head:', self.chain.head_hash)

    # Check the state, and determine if we should commit or prepare
    def on_receive(self, msg):
        if isinstance(msg, block.Block):
            self.accept_block(msg)
        elif isinstance(msg, transactions.Transaction):
            self.accept_transaction(msg)
        print('In on receive! Head:', self.chain.head_hash)

    def mk_deposit_transactions(self, value):
        casper_ct = abi.ContractTranslator(casper_utils.casper_abi)
        nonce = self.chain.state.get_nonce(self.coinbase)
        valcode_tx = transactions.Transaction(nonce, tester.GASPRICE, tester.STARTGAS,
                                              '', 0, casper_utils.mk_validation_code(self.coinbase)).sign(self.key)
        nonce += 1
        valcode_addr = utils.mk_contract_address(self.coinbase, nonce)
        deposit_func = casper_ct.encode('deposit', [valcode_addr, self.coinbase])
        deposit_tx = transactions.Transaction(nonce, tester.GASPRICE, tester.STARTGAS,
                                              self.chain.casper_address, value, deposit_func).sign(self.key)
        return valcode_tx, deposit_tx

        # t = tester.State(self.chain.state.ephemeral_clone())
        # casper = tester.ABIContract(t, casper_utils.casper_abi, self.chain.casper_address)
        # valcode_addr, valcode_tx = t.tx(self.key, '', 0, casper_utils.mk_validation_code(self.coinbase), return_tx=True)
        # casper.deposit(valcode_addr, self.coinbase, value=value)
        # # TODO: Add forking logic if the validator index changes because we jump on a new fork
        # self.validator_index = casper.get_nextValidatorIndex() - 1
        # self.valcode_addr = valcode_addr
        # return valcode_tx, deposit_tx

    # def prepare(self, epoch, source_epoch):
    #     self.ancestry_hash[epoch] = utils.sha3(epoch_blockhash(t, epoch), self.ancestry_hash[source_epoch])
    #     casper.prepare(mk_prepare(self.validator_index, epoch, epoch_blockhash(self.t, epoch),
    #                               self.ancestry_hash[source_epoch], source_epoch, self.ancestry_hash[source_epoch], self.key))
