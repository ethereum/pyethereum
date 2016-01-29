from rlp.sedes import big_endian_int, Binary, binary, CountableList
from utils import address, int256, trie_root, hash32, to_string, \
    sha3, zpad, normalize_address, int_to_addr, big_endian_to_int, \
    encode_int, safe_ord, encode_int32, encode_hex, shardify, \
    get_shard, match_shard
from db import EphemDB, OverlayDB
from serenity_transactions import Transaction
import fastvm as vm
from config import BLOCKHASHES, STATEROOTS, BLKNUMBER, CASPER, GAS_REMAINING, GASLIMIT, NULL_SENDER, ETHER, PROPOSER, RNGSEEDS, TXGAS, TXINDEX, LOG, MAXSHARDS, UNHASH_MAGIC_BYTES
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


class TransactionGroupSummary(rlp.Serializable):
    fields = [
        ('gas_limit', big_endian_int),
        ('left_bound', big_endian_int),
        ('right_bound', big_endian_int),
        ('transaction_hash', binary)
    ]

    def __init__(self, gas_limit=GASLIMIT, left_bound=0, right_bound=2**160, txgroup=[], transaction_hash=None):
        self.gas_limit = gas_limit
        self.left_bound = left_bound
        self.right_bound = right_bound
        self.transaction_hash = transaction_hash or sha3(rlp.encode(txgroup))


# The entire block, including the transactions. Note that the concept of
# extra data is non-existent; if a proposer wants extra data they should
# just make the first transaction a dummy containing that data
class Block(rlp.Serializable):
    fields = [
        ('header', BlockHeader),
        ('summaries', CountableList(TransactionGroupSummary)),
        ('transaction_groups', CountableList(CountableList(Transaction)))
    ]

    def __init__(self, header=None, transactions=[], transaction_groups=None, summaries=None, number=None, proposer='\x00' * 20, sig=b''):
        if transaction_groups is None or summaries is None or header is None:
            if transaction_groups is not None or summaries is not None or header is not None:
                raise Exception("If you supply one of txgroups/summaries/header you must supply all of them!")
            # TODO: Later, create a smarter algorithm for this
            # For now, we just create a big super-group with a global range
            # containing all of the desired transactions
            self.transaction_groups = [transactions]
            for tx in transactions:
                assert tx.left_bound % (tx.right_bound - tx.left_bound) == 0
                assert 0 <= tx.left_bound < tx.right_bound <= MAXSHARDS
            self.summaries = [TransactionGroupSummary(GASLIMIT, 0, MAXSHARDS, transactions)]
            self.summaries[0].intrinsic_gas = sum([tx.intrinsic_gas for tx in transactions]) 
            assert self.summaries[0].intrinsic_gas < GASLIMIT
            self.header = BlockHeader(number, sha3(rlp.encode(self.summaries)), proposer, sig)
        else:
            prevright = 0
            for s, g in zip(summaries, transaction_groups):
                # Check tx hash matches
                assert s.transaction_hash == sha3(rlp.encode(g))
                # Bounds must reflect a node in the binary tree (eg. 12-14 is valid,
                # so is 13-14 or 14-15, but 13-15 is not)
                assert s.left_bound % (s.right_bound - s.left_bound) == 0
                # Summaries must be disjoint and in sorted order with bounds valid and
                # within the global bounds
                assert 0 <= prevright <= s.left_bound < s.right_bound <= MAXSHARDS
                # Check that all transaction bounds are a subset of the summary
                for tx in g:
                    assert s.left_bound <= tx.left_bound < tx.right_bound <= s.right_bound
                s.intrinsic_gas = sum([tx.intrinsic_gas for tx in g])
                prevright = s.right_bound
            # Check gas limit condition
            assert sum([s.intrinsic_gas for s in summaries]) < GASLIMIT
            # Check header transaction root matches
            assert header.txroot == sha3(rlp.encode(summaries))
            self.summaries, self.transaction_groups, self.header = summaries, transaction_groups, header

    def add_transaction(tx, group_id=0):
        self.transaction_groups[group_id].append(tx)
        self.summaries[group_id].transaction_hash = sha3(rlp.encode(self.transaction_groups[group_id]))
        self.header.txroot = sha3(rlp.encode(self.summaries[group_id]))

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

def initialize_with_gas_limit(state, gas_limit, left_bound=0):
    state.set_storage(shardify(GAS_REMAINING, left_bound), '\x00' * 32, zpad(encode_int(gas_limit), 32))
    

transition_cache_map = {}

# Processes a block on top of a state to reach a new state
def block_state_transition(state, block, listeners=[]):
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
        for s, g in zip(block.summaries, block.transaction_groups):
            left_shard = s.left_bound // 2**160
            state.set_storage(shardify(GAS_REMAINING, left_shard), '\x00' * 32, zpad(encode_int(s.gas_limit - s.intrinsic_gas), 32))
            # Set the txindex to 0 to start off
            state.set_storage(shardify(TXINDEX, left_shard), '\x00' * 32, zpad(encode_int(0), 32))
            # Apply transactions sequentially
            print 'Block %d contains %d transactions and %d intrinsic gas' % (blknumber, sum([len(g) for g in block.transaction_groups]), sum([summ.intrinsic_gas for summ in block.summaries]))
            for tx in g:
                tx_state_transition(state, tx, s.left_bound, s.right_bound, listeners=listeners)
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
    # Consistency checking
    check_key = pre+(block.hash if block else 'NONE')
    if check_key not in transition_cache_map:
        transition_cache_map[check_key] = state.root
    else:
        assert transition_cache_map[check_key] == state.root

def tx_state_transition(state, tx, left_bound=0, right_bound=MAXSHARDS, listeners=[]):
    _TXINDEX = shardify(TXINDEX, left_bound)
    _LOG = shardify(LOG, left_bound)
    _GAS_REMAINING = shardify(GAS_REMAINING, left_bound)
    _TXGAS = shardify(TXGAS, left_bound)
    # Get prior gas used
    gas_remaining = big_endian_to_int(state.get_storage(_GAS_REMAINING, '\x00' * 32))
    # If there is not enough gas left for this transaction, it's a no-op
    if gas_remaining - tx.exec_gas < 0:
        print 'UNABLE TO EXECUTE transaction due to gas limits: %d have, %d required' % \
            (gas_remaining, tx.exec_gas)
        state.set_storage(_LOG, state.get_storage(_TXINDEX, 0), 0)
        return None
    # If the recipient is out of range, it's a no-op
    if not (left_bound <= get_shard(tx.addr) < right_bound):
        print 'UNABLE TO EXECUTE transaction due to out-of-range'
        state.set_storage(_LOG, state.get_storage(_TXINDEX, 0), 0)
        return None
    # Set an object in the state for tx gas
    state.set_storage(_TXGAS, '\x00' * 32, encode_int32(tx.gas))
    ext = VMExt(state, listeners=listeners)
    # Empty the log store
    state.set_storage(_LOG, state.get_storage(_TXINDEX, 0), '')
    # Create the account if it does not yet exist
    if tx.code and not state.get_storage(tx.addr, b''):
        message = vm.Message(NULL_SENDER, tx.addr, 0, tx.exec_gas, vm.CallData([], 0, 0), left_bound, right_bound)
        result, execution_start_gas, data = apply_msg(ext, message, tx.code)
        if not result:
            state.set_storage(_LOG, state.get_storage(_TXINDEX, 0), 1)
            return None
        code = ''.join([chr(x) for x in data])
        put_code(state, tx.addr, code)
    else:
        execution_start_gas = tx.exec_gas
    # Process VM execution
    message_data = vm.CallData([safe_ord(x) for x in tx.data], 0, len(tx.data))
    message = vm.Message(NULL_SENDER, tx.addr, 0, execution_start_gas, message_data)
    result, msg_gas_remained, data = \
        apply_msg(ext, message, get_code(state, tx.addr))
    assert 0 <= msg_gas_remained <= execution_start_gas <= tx.exec_gas
    # Set gas used
    state.set_storage(_GAS_REMAINING, '\x00' * 32, gas_remaining - tx.exec_gas + msg_gas_remained)
    # Places a log in storage
    logs = state.get_storage(_LOG, state.get_storage(_TXINDEX, 0))
    state.set_storage(_LOG, state.get_storage(_TXINDEX, 0),
                      encode_int32(2 if result else 1) + logs)
    # Increments the txindex
    state.set_storage(_TXINDEX, 0, big_endian_to_int(state.get_storage(_TXINDEX, 0)) + 1)
    return data

# Determines the contract address for a piece of code and a given creator
# address (contracts created from outside get creator '\x00' * 20)
def mk_contract_address(sender='\x00'*20, left_bound=0, code=''):
    return shardify(sha3(sender + code)[12:], left_bound)

RLPEMPTYLIST = rlp.encode([])
# Save a log in the state
def add_log(state, sender, topics, data, leftbound, listeners):
    # print big_endian_to_int(state.get_storage(TXINDEX, 0)), state.get_storage(LOG, state.get_storage(TXINDEX, 0)).encode('hex')
    old_storage = state.get_storage(LOG, state.get_storage(shardify(TXINDEX, leftbound), 0)) or RLPEMPTYLIST
    new_storage = rlp.append(old_storage, [sender, map(encode_int32, topics), data])
    state.set_storage(LOG, state.get_storage(shardify(TXINDEX, leftbound), 0), new_storage)
    for listener in listeners:
        listener(sender, topics, ''.join([chr(x) for x in data]))

def get_code(state, address):
    codehash = state.get_storage(address, '')
    return state.db.get(UNHASH_MAGIC_BYTES + codehash) if codehash else ''

def put_code(state, address, code):
    codehash = sha3(code)
    state.db.put(UNHASH_MAGIC_BYTES + codehash, code)
    state.set_storage(address, '', codehash)

# External calls that can be made from inside the VM. To use the EVM with a
# different blockchain system, database, set parameters for testing, just
# swap out the functions here
class VMExt():

    def __init__(self, state, listeners=[]):
        self._state = state
        self.set_storage = state.set_storage
        self.get_storage = state.get_storage
        self.log = lambda sender, topics, data, leftbound: add_log(state, sender, topics, data, leftbound, listeners)
        self.log_storage = state.account_to_dict
        self.unhash = lambda x: state.db.get(UNHASH_MAGIC_BYTES + x)
        self.msg = lambda msg, code: apply_msg(self, msg, code)
        self.static_msg = lambda msg, code: apply_msg(EmptyVMExt, msg, code)


# An empty VMExt instance that can be used to employ the EVM "purely"
# without accessing state. This is used for Casper signature verifications
class _EmptyVMExt():

    def __init__(self):
        self._state = State('', EphemDB())
        self.set_storage = lambda addr, k, v: None
        self.get_storage = lambda addr, k: ''
        self.log = lambda topics, mem: None
        self.log_storage = lambda addr: None
        self.unhash = lambda x: ''
        self.msg = lambda msg, code: apply_msg(self, msg, code)
        self.static_msg = lambda msg, code: apply_msg(EmptyVMExt, msg, code)

EmptyVMExt = _EmptyVMExt()

eve_cache = {}

# Processes a message
def apply_msg(ext, msg, code):
    _SENDER_ETHER = match_shard(ETHER, msg.sender)
    _RECIPIENT_ETHER = match_shard(ETHER, msg.to)
    cache_key = msg.sender + msg.to + str(msg.value) + msg.data.extract_all() + code
    if ext is EmptyVMExt and cache_key in eve_cache:
        return eve_cache[cache_key]
    # Transfer value, instaquit if not enough
    snapshot = ext._state.snapshot()
    if big_endian_to_int(ext.get_storage(_SENDER_ETHER, msg.sender)) < msg.value:
        print 'MSG TRANSFER FAILED'
        return 1, msg.gas, []
    elif msg.value:
        ext.set_storage(_SENDER_ETHER, msg.sender, big_endian_to_int(ext.get_storage(_SENDER_ETHER, msg.sender)) - msg.value)
        ext.set_storage(_RECIPIENT_ETHER, msg.to, big_endian_to_int(ext.get_storage(_RECIPIENT_ETHER, msg.to)) + msg.value)
    # Main loop
    msg_to_raw = big_endian_to_int(msg.to)
    if msg_to_raw in specials.specials:
        res, gas, dat = specials.specials[msg_to_raw](ext, msg)
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
