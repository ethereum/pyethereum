from rlp.sedes import big_endian_int, Binary, binary, CountableList
from utils import address, int256, trie_root, hash32, to_string, \
    sha3, zpad, normalize_address, int_to_addr, big_endian_to_int, \
    encode_int, safe_ord, encode_int32, encode_hex
from db import EphemDB, OverlayDB
from serenity_transactions import Transaction
import fastvm as vm
from config import BLOCKHASHES, STATEROOTS, BLKNUMBER, CASPER, GAS_CONSUMED, GASLIMIT, NULL_SENDER, ETHER, PROPOSER, RNGSEEDS, TXGAS, TXINDEX, LOG
import rlp
import trie
import specials
TT255 = 2 ** 255
TT256 = 2 ** 256
TT256M1 = 2 ** 256 - 1

# Block header (~150 bytes in the normal case); light clients download these
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


# The entire block, including the transactions. Note that the concept of
# extra data is non-existent; if a proposer wants extra data they should
# just make the first transaction a dummy containing that data
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


# An object representing the state. In Serenity, the state will be just a
# trie of accounts with storage; _all_ intermediate state, including gas
# used, logs, transaction index, etc, is placed into contracts. This greatly
# simplifies a large amount of handling code
class State():
    def __init__(self, state_root, db):
        self.state = trie.Trie(db)
        self.state.root_hash = state_root
        self.db = self.state.db
        # The state uses a journaling cache data structure in order to
        # facilitate revert operations while maintaining very high efficiency
        # for updates. Note that the cache is designed to handle commits
        # happening at any time; commits can be reverted too. Committing is
        # done automatically whenever a root is requested; for this reason,
        # use the State.root method to get the root instead of poking into
        # State.state.root_hash directly
        self.journal = []
        self.cache = {}
        self.modified = {}

    def set_storage(self, addr, k, v):
        if isinstance(k, (int, long)):
            k = zpad(encode_int(k), 32)
        if isinstance(v, (int, long)):
            v = zpad(encode_int(v), 32)
        addr = normalize_address(addr)
        self.journal.append((addr, k, self.get_storage(addr, k)))
        self.cache[addr][k] = v
        if addr not in self.modified:
            self.modified[addr] = {}
        self.modified[addr][k] = True

    def commit(self):
        rt = self.state.root_hash
        for addr, subcache in self.cache.items():
            t = trie.Trie(self.state.db)
            t.root_hash = self.state.get(addr)
            modified = False
            for key, value in subcache.items():
                if key in self.modified.get(addr, {}) and value != t.get(key):
                    t.update(key, value)
                    modified = True
            if modified:
                self.state.update(addr, t.root_hash)
        self.journal.append(('~root', (self.cache, self.modified), rt))
        self.cache = {}
        self.modified = {}

    def get_storage(self, addr, k):
        if isinstance(k, (int, long)):
            k = zpad(encode_int(k), 32)
        addr = normalize_address(addr)
        if addr not in self.cache:
            self.cache[addr] = {}
        elif k in self.cache[addr]:
            return self.cache[addr][k]
        t = trie.Trie(self.state.db)
        t.root_hash = self.state.get(addr)
        v = t.get(k)
        self.cache[addr][k] = v
        return v

    @property
    def root(self):
        self.commit()
        return self.state.root_hash

    # Creates a new state using an overlay of the existing state. Updates to
    # the cloned state will NOT affect the parent state.
    def clone(self):
        self.commit()
        return State(self.root, OverlayDB(self.state.db))

    # Converts the state to a dictionary
    def to_dict(self):
        state_dump = {}
        for address, v in self.state.to_dict().items():
            acct_dump = {}
            acct_trie = trie.Trie(self.state.db)
            acct_trie.root_hash = v
            for key, v in acct_trie.to_dict().items():
                acct_dump[encode_hex(key)] = encode_hex(v)
            state_dump[encode_hex(address)] = acct_dump
        for address, v in self.cache.items():
            if address not in state_dump:
                state_dump[encode_hex(address)] = {}
            for key, val in v.items():
                if val:
                    state_dump[encode_hex(address)][encode_hex(key)] = encode_hex(val)
            if not state_dump[encode_hex(address)]:
                del state_dump[encode_hex(address)]
        return state_dump

    def account_to_dict(self, account):
        acct_trie = trie.Trie(self.state.db)
        acct_trie.root = self.state.get(normalize_address(account))
        acct_dump = {}
        for key, v in acct_trie.to_dict().items():
            acct_dump[encode_hex(k)] = encode_hex(v)
        return acct_dump

    # Returns a value x, where State.revert(x) at any later point will return
    # you to the point at which the snapshot was made.
    def snapshot(self):
        return len(self.journal)

    # Reverts to the provided snapshot
    def revert(self, snapshot):
        while len(self.journal) > snapshot:
            addr, key, preval = self.journal.pop()
            if addr == '~root':
                self.state.root_hash = preval
                self.cache, self.modified = key
            else:
                self.cache[addr][key] = preval

# Processes a block on top of a state to reach a new state
def block_state_transition(state, block):
    pre = state.root
    # Determine the current block number, block proposer and block hash
    blknumber = big_endian_to_int(state.get_storage(BLKNUMBER, '\x00' * 32))
    blkproposer = block.proposer if block else '\x00' * 20
    blkhash = block.hash if block else '\x00' * 32
    # Put the state root in storage
    if blknumber:
        state.set_storage(STATEROOTS, encode_int32(blknumber - 1), state.root)
    # Put the proposer in storage
    state.set_storage(PROPOSER, '\x00' * 32, blkproposer)
    # If the block exists (ie. is not NONE), process every transaction
    if block:
        assert block.number == blknumber, (block.number, blknumber)
        # Initialize the GAS_CONSUMED variable to _just_ the sum of
        # intrinsic gas of each transaction (ie. tx data consumption
        # only, not computation)
        state.set_storage(GAS_CONSUMED, '\x00' * 32, zpad(encode_int(block.intrinsic_gas), 32))
        # Set the txindex to 0 to start off
        state.set_storage(TXINDEX, '\x00' * 32, zpad(encode_int(0), 32))
        # Apply transactions sequentially
        print 'Block contains %d transactions' % len(block.transactions)
        for tx in block.transactions:
            tx_state_transition(state, tx)
    # Put the block hash in storage
    state.set_storage(BLOCKHASHES, encode_int32(blknumber), blkhash)
    # Put the next block number in storage
    state.set_storage(BLKNUMBER, '\x00' * 32, encode_int32(blknumber + 1))
    # Update the RNG seed (the lower 64 bits contains the number of validators,
    # the upper 192 bits are pseudorandom)
    prevseed = state.get_storage(RNGSEEDS, encode_int32(blknumber - 1)) if blknumber else '\x00' * 32 
    newseed = big_endian_to_int(sha3(prevseed + blkproposer))
    newseed = newseed - (newseed % 2**64) + big_endian_to_int(state.get_storage(CASPER, 0))
    state.set_storage(RNGSEEDS, encode_int32(blknumber), newseed)


def tx_state_transition(state, tx):
    # Get prior gas used
    gas_used = big_endian_to_int(state.get_storage(GAS_CONSUMED, '\x00' * 32))
    # If there is not enough gas left for this transaction, it's a no-op
    if gas_used + tx.exec_gas > GASLIMIT:
        print 'UNABLE TO EXECUTE transaction due to gas limits: %d pre, %d asked, %d projected post vs %d limit' % \
            (gas_used, tx.exec_gas, gas_used + tx.exec_gas, GASLIMIT)
        state.set_storage(LOG, state.get_storage(TXINDEX, '\x00' * 32), '\x00' * 32)
        return None
    # Set an object in the state for tx gas
    state.set_storage(TXGAS, '\x00' * 32, encode_int32(tx.gas))
    ext = VMExt(state)
    # Create the account if it does not yet exist
    if tx.code and not state.get_storage(tx.addr, b''):
        message = vm.Message(NULL_SENDER, tx.addr, 0, tx.exec_gas, vm.CallData([], 0, 0))
        result, execution_start_gas, data = apply_msg(ext, message, tx.code)
        if not result:
            state.set_storage(LOG, state.get_storage(TXINDEX, '\x00' * 32), encode_int32(1))
            return None
        state.set_storage(tx.addr, b'', ''.join([chr(x) for x in data]))
    else:
        execution_start_gas = tx.exec_gas
    # Process VM execution
    message_data = vm.CallData([safe_ord(x) for x in tx.data], 0, len(tx.data))
    message = vm.Message(NULL_SENDER, tx.addr, 0, execution_start_gas, message_data)
    result, gas_remained, data = apply_msg(ext, message, state.get_storage(tx.addr, b''))
    assert 0 <= gas_remained <= execution_start_gas <= tx.exec_gas, (gas_remained, execution_start_gas, tx.exec_gas)
    # Set gas used
    state.set_storage(GAS_CONSUMED, '\x00' * 32, zpad(encode_int(gas_used + tx.exec_gas - gas_remained), 32))
    # Places a log in storage
    state.set_storage(LOG, state.get_storage(TXINDEX, '\x00' * 32), encode_int32(2 if result else 1) + ''.join([chr(x) for x in data]))
    # Increments the txindex
    state.set_storage(TXINDEX, '\x00' * 32, encode_int32(big_endian_to_int(state.get_storage(TXINDEX, '\x00' * 32)) + 1))
    return data

# Determines the contract address for a piece of code and a given creator
# address (contracts created from outside get creator '\x00' * 20)
def mk_contract_address(sender='\x00'*20, code=''):
    return sha3(sender + code)[12:]


# External calls that can be made from inside the VM. To use the EVM with a
# different blockchain system, database, set parameters for testing, just
# swap out the functions here
class VMExt():

    def __init__(self, state):
        self._state = state
        self.set_storage = state.set_storage
        self.get_storage = state.get_storage
        self.log_storage = state.account_to_dict
        self.msg = lambda msg, code: apply_msg(self, msg, code)
        self.static_msg = lambda msg, code: apply_msg(EmptyVMExt, msg, code)


# An empty VMExt instance that can be used to employ the EVM "purely"
# without accessing state. This is used for Casper signature verifications
class _EmptyVMExt():

    def __init__(self):
        self._state = State('', EphemDB())
        self.set_storage = lambda addr, k, v: None
        self.get_storage = lambda addr, k: ''
        self.log_storage = lambda addr: None
        self.msg = lambda msg, code: apply_msg(self, msg, code)
        self.static_msg = lambda msg, code: apply_msg(EmptyVMExt, msg, code)

EmptyVMExt = _EmptyVMExt()

eve_cache = {}

# Processes a message
def apply_msg(ext, msg, code):
    cache_key = msg.sender + msg.to + str(msg.value) + msg.data.extract_all() + code
    if ext is EmptyVMExt and cache_key in eve_cache:
        return eve_cache[cache_key]
    # Transfer value, instaquit if not enough
    snapshot = ext._state.snapshot()
    if ext.get_storage(ETHER, msg.sender) < msg.value:
        print 'MSG TRANSFER FAILED'
        return 1, msg.gas, []
    elif msg.value:
        ext.set_storage(ETHER, msg.sender, big_endian_to_int(ext.get_storage(ETHER, msg.sender)) - msg.value)
        ext.set_storage(ETHER, msg.to, big_endian_to_int(ext.get_storage(ETHER, msg.to)) + msg.value)
    # Main loop
    if msg.to in specials.specials:
        res, gas, dat = specials.specials[msg.to](ext, msg)
    else:
        res, gas, dat = vm.vm_execute(ext, msg, code)
    # If the message failed, revert execution
    if res == 0:
        print 'REVERTING %d gas from account 0x%s to account 0x%s with data 0x%s' % \
            (msg.gas, msg.sender.encode('hex'), msg.to.encode('hex'), msg.data.extract_all().encode('hex'))
        if 200000 < msg.gas < 500000:
            raise Exception("123")
        ext._state.revert(snapshot)
    # Otherwise, all good
    else:
        pass  # print 'MSG APPLY SUCCESSFUL'

    eve_cache[cache_key] = (res, gas if res else 0, dat)
    return res, gas if res else 0, dat
