from rlp.sedes import big_endian_int, Binary, binary, CountableList
from utils import address, int256, trie_root, hash32, to_string, \
    sha3, zpad, normalize_address, int_to_addr, big_endian_to_int, \
    encode_int, safe_ord, encode_int32
from config import Env
from db import EphemDB, OverlayDB
from serenity_transactions import Transaction
import vm
from config import BLOCKHASHES, STATEROOTS, BLKNUMBER, CASPER, GAS_CONSUMED, GASLIMIT, NULL_SENDER, ETHER, PROPOSER, RNGSEEDS
import rlp
import trie
import specials
TT255 = 2 ** 255
TT256 = 2 ** 256
TT256M1 = 2 ** 256 - 1

class BlockHeader(rlp.Serializable):
    fields = [
        ('number', big_endian_int),
        ('txroot', trie_root),
        ('proposer', address),
        ('sig', binary)
    ]

    def __init__(self, number=0, txroot=trie.BLANK_ROOT, proposer='\x00'*20, sig=b''):
        fields = {k: v for k, v in locals().items() if k != 'self'}
        super(BlockHeader, self).__init__(**fields)

    @property
    def hash(self):
        return sha3(rlp.encode(self))


class Block(rlp.Serializable):
    fields = [
        ('header', BlockHeader),
        ('transactions', CountableList(Transaction))
    ]

    def __init__(self, header=None, transactions=[], number=None, proposer='\x00' * 20, sig=b''):
        self.transactions = transactions
        self.transaction_trie = trie.Trie(EphemDB())
        self.intrinsic_gas = sum([tx.intrinsic_gas for tx in transactions])
        assert self.intrinsic_gas <= GASLIMIT
        for i, tx in enumerate(self.transactions):
            self.transaction_trie.update(encode_int32(i), rlp.encode(tx))
        if header:
            assert header.txroot == self.transaction_trie.root_hash
            self.header = header
        else:
            self.header = BlockHeader(number, self.transaction_trie.root_hash, proposer, sig)

    def add_transaction(tx):
        self.transaction_trie.update(zpad(rlp.encode(len(self.transactions), 32)), rlp.encode(tx))
        self.transactions.append(tx)
        self.header.txroot = self.transaction_trie.root_hash

    @property
    def hash(self): return self.header.hash

    @property
    def number(self): return self.header.number
    @number.setter
    def number(self, number): self.header.number = number

    @property
    def sig(self): return self.header.sig
    @sig.setter
    def sig(self, sig): self.header.sig = sig

    @property
    def proposer(self): return self.header.proposer
    @proposer.setter
    def proposer(self, proposer): self.header.proposer = proposer

    @property
    def txroot(self): return self.header.txroot



class State():
    def __init__(self, state_root, db):
        self.state = trie.Trie(db)
        self.state.root_hash = state_root
        self.db = self.state.db

    def set_storage(self, addr, k, v):
        if isinstance(k, (int, long)):
            k = zpad(encode_int(k), 32)
        if isinstance(v, (int, long)):
            v = zpad(encode_int(v), 32)
        addr = normalize_address(addr)
        t = trie.Trie(self.state.db)
        t.root_hash = self.state.get(addr)
        t.update(k, v)
        self.state.update(addr, t.root_hash)

    def get_storage(self, addr, k):
        if isinstance(k, (int, long)):
            k = zpad(encode_int(k), 32)
        addr = normalize_address(addr)
        t = trie.Trie(self.state.db)
        t.root_hash = self.state.get(addr)
        return t.get(k)

    def account_exists(self, addr):
        return self.state.get(normalize_address(addr)) != trie.BLANK_ROOT

    @property
    def root(self):
        return self.state.root_hash

    def clone(self):
        return State(self.state.root_hash, OverlayDB(self.state.db))

    def to_dict(self):
        state_dump = {}
        for address, v in self.state.to_dict().items():
            acct_dump = {}
            acct_trie = trie.Trie(self.state.db)
            acct_trie.root_hash = v
            for key, v in acct_trie.to_dict().items():
                acct_dump[encode_hex(k)] = encode_hex(v)
            state_dump[encode_hex(address)] = acct_dump
        return state_dump

    def account_to_dict(self, account):
        acct_trie = trie.Trie(self.state.db)
        acct_trie.root = self.state.get(normalize_address(account))
        acct_dump = {}
        for key, v in acct_trie.to_dict().items():
            acct_dump[encode_hex(k)] = encode_hex(v)
        return acct_dump

    def snapshot(self):
        return self.state.root_hash

    def revert(self, snapshot):
        self.state.root_hash = snapshot

def block_state_transition(state, block):
    blknumber = utils.big_endian_int(state.get_storage(BLKNUMBER, '\x00' * 32))
    blkproposer = block.proposer if block else '\x00' * 20
    blkhash = block.hash if block else '\x00' * 32
    state.set_storage(BLKNUMBER, '\x00' * 32, 32, encode_int32(blknumber))
    state.set_storage(PROPOSER, '\x00' * 32, 32, blkproposer)
    if block:
        # Initialize the GAS_CONSUMED variable to _just_ intrinsic gas (ie. tx data consumption)
        state.set_storage(GAS_CONSUMED, '\x00' * 32, zpad(encode_int(block.intrinsic_gas), 32))
        # Apply transactions sequentially
        for i, tx in enumerate(block.transaction_list):
            tx_state_transition(state, tx, i)
    # Put the block hash in storage
    state.set_storage(BLOCKHASHES, encode_int32(blknumber), blkhash)
    # Update the RNG seed (the lower 64 bits contains the number of validators,
    # the upper 192 bits are pseudorandom)
    prevseed = state.get_storage(RNGSEEDS, encode_int32(blknumber - 1)) if blknumber else '\x00' * 32 
    newseed = utils.big_endian_to_int(sha3(prevseed + blkproposer))
    newseed = newseed - (newseed % 2**64) + state.get_storage(CASPER, 0)
    state.set_storage(RNGSEEDS, encode_int32(blknumber), newseed)
    # Put the state root in storage
    state.set_storage(STATEROOTS, encode_int32(blknumber), state.root)


def tx_state_transition(state, tx, index):
    # Get prior gas used
    gas_used = big_endian_to_int(state.get_storage(GAS_CONSUMED, '\x00' * 32))
    if gas_used + tx.execgas > GASLIMIT:
        return None
    ext = VMExt(state, tx)
    # Create the account if it does not yet exist
    if tx.code and not state.get_storage(tx.addr, b''):
        message = vm.Message(NULL_SENDER, tx.addr, 0, tx.execgas, b'')
        result, execution_start_gas, data = apply_msg(ext, message, tx.code)
        if not result:
            return None
        state.set_storage(tx.addr, b'', ''.join([chr(x) for x in data]))
    else:
        execution_start_gas = tx.execgas
    # Process VM execution
    message_data = vm.CallData([safe_ord(x) for x in tx.data], 0, len(tx.data))
    message = vm.Message(NULL_SENDER, tx.addr, 0, execution_start_gas, message_data)
    result, gas_remained, data = apply_msg(ext, message, state.get_storage(tx.addr, b''))
    # Set gas used
    state.set_storage(GAS_CONSUMED, '\x00' * 32, zpad(encode_int(gas_used + tx.execgas - gas_remained), 32))
    return data

def mk_contract_address(sender='\x00'*20, code=''):
    return sha3(sender + code)[12:]


# External calls that can be made from inside the VM. To use the EVM with a
# different blockchain system, database, set parameters for testing, just
# swap out the functions here
class VMExt():

    def __init__(self, state, tx):
        self._state = state
        self.set_storage = state.set_storage
        self.get_storage = state.get_storage
        self.account_exists = state.account_exists
        self.log_storage = state.account_to_dict
        self.tx_execgas = tx.execgas
        self.msg = lambda msg, code: apply_msg(self, msg, code)


class EmptyVMExt():
    def __init__():
        self.set_storage = lambda addr, k, v: 0
        self.get_storage = lambda addr, k: 0
        self.account_exists = lambda addr: 0
        self.log_storage = lambda addr: 0
        self.tx_execgas = 0
        self.msg = lambda msg, code: (1, msg.gas, [])


def apply_msg(ext, msg, code):
    # Transfer value, instaquit if not enough
    snapshot = ext._state.snapshot()
    if ext.get_storage(ETHER, msg.sender) < msg.value:
        print 'MSG TRANSFER FAILED'
        return 1, msg.gas, []
    else:
        ext.set_storage(ETHER, msg.sender, big_endian_to_int(ext.get_storage(ETHER, msg.sender)) - msg.value)
        ext.set_storage(ETHER, msg.to, big_endian_to_int(ext.get_storage(ETHER, msg.to)) + msg.value)
    # Main loop
    if msg.to in specials.specials:
        res, gas, dat = specials.specials[msg.to](ext, msg)
    else:
        res, gas, dat = vm.vm_execute(ext, msg, code)
    # gas = int(gas)
    # assert utils.is_numeric(gas)
    if res == 0:
        print 'REVERTING'
        ext._state.revert(snapshot)
    else:
        pass  # print 'MSG APPLY SUCCESSFUL'

    return res, gas, dat
