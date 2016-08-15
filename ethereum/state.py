import rlp
from ethereum.utils import normalize_address, hash32, trie_root, \
    big_endian_int, address, int256, encode_hex, encode_int, \
    big_endian_to_int, int_to_addr, zpad, parse_as_bin, parse_as_int, \
    decode_hex, sha3
from rlp.sedes import big_endian_int, Binary, binary, CountableList
from ethereum import utils
from ethereum import trie
from ethereum.trie import Trie
from ethereum.securetrie import SecureTrie
from config import default_config, Env
from ethereum.block import FakeHeader
from db import BaseDB, EphemDB, OverlayDB
import copy
import sys
if sys.version_info.major == 2:
    from repoze.lru import lru_cache
else:
    from functools import lru_cache


ACCOUNT_SPECIAL_PARAMS = ('nonce', 'balance', 'code', 'storage', 'deleted')
ACCOUNT_OUTPUTTABLE_PARAMS = ('nonce', 'balance', 'code')

@lru_cache(1024)
def get_block(db, blockhash):
    """
    Assumption: blocks loaded from the db are not manipulated
                -> can be cached including hash
    """
    return rlp.decode(rlp.descend(db.get(blockhash), 0), BlockHeader)


def snapshot_form(val):
    if isinstance(val, (int, long)):
        return str(val)
    elif isinstance(val, (str, bytes)):
        return '0x' + encode_hex(val)


STATE_DEFAULTS = {
    "txindex": 0,
    "gas_used": 0,
    "gas_limit": 3141592,
    "block_number": 0,
    "block_coinbase": '\x00' * 20,
    "block_difficulty": 1,
    "timestamp": 0,
    "logs": [],
    "suicides": [],
    "recent_uncles": {},
    "prev_headers": [],
    "refunds": 0,
}


class State():

    def __init__(self, root='', env=Env(), **kwargs):
        self.env = env
        self.trie = SecureTrie(Trie(self.db, root))
        for k, v in STATE_DEFAULTS.items():
            setattr(self, k, kwargs.get(k, copy.copy(v)))
        self.journal = []
        self.cache = {}
        self.modified = {}
        self.log_listeners = []

    @property
    def db(self):
        return self.env.db

    @property
    def config(self):
        return self.env.config

    def get_block_hash(self, n):
        if self.is_METROPOLIS():
            if self.block_number < n or n >= self.config['METROPOLIS_WRAPAROUND'] or n < 0:
                o = b'\x00' * 32
            sbytes = self.get_storage_bytes(utils.normalize_address(self.config["METROPOLIS_BLOCKHASH_STORE"]),
                                            (self.block_number - n - 1) % self.config['METROPOLIS_WRAPAROUND'])
            return sbytes or (b'\x00' * 32)
        else:
            if self.block_number < n or n > 256 or n < 0:
                o = b'\x00' * 32
            else:
                o = self.prev_headers[n].hash if self.prev_headers[n] else b'\x00' * 32
            return o

    def add_block_header(self, block_header):
        self.journal.append(('~prev_headers', None, len(self.prev_headers), None))
        self.prev_headers = [block_header] + self.prev_headers

    def typecheck_storage(self, k, v):
        if k == 'nonce' or k == 'balance':
            assert isinstance(v, (int, long))
        elif k == 'code':
            assert isinstance(v, (str, bytes))
        elif k == 'storage':
            assert isinstance(v, (str, bytes)) and len(v) == 32
        elif k == 'deleted':
            assert isinstance(v, bool)
        else:
            assert isinstance(v, (str, bytes))
        return True

    def set_storage(self, addr, k, v):
        if isinstance(k, (int, long)):
            k = zpad(encode_int(k), 32)
        self.typecheck_storage(k, v)
        addr = normalize_address(addr)
        preval = self.get_storage(addr, k)
        self.journal.append((addr, k, preval, addr in self.modified))
        if self.cache[addr].get('deleted', False):
            self.journal.append((addr, 'deleted', True, addr in self.modified))
            self.cache[addr]['deleted'] = False
        self.cache[addr][k] = v
        assert self.get_storage(addr, k) == v
        if addr not in self.modified:
            self.modified[addr] = {}
        self.modified[addr][k] = True

    def set_param(self, k, v):
        self.journal.append((k, None, getattr(self, k), None))
        setattr(self, k, v)

    # It's unsafe because it passes through the cache
    def _get_account_unsafe(self, addr):
        rlpdata = self.trie.get(addr)
        if rlpdata != trie.BLANK_NODE:
            o = rlp.decode(rlpdata, Account, db=self.db)
            o._mutable = True
            return o
        else:
            return Account.blank_account(self.db, self.config['ACCOUNT_INITIAL_NONCE'])

    def get_storage(self, addr, k):
        if isinstance(k, (int, long)):
            k = zpad(encode_int(k), 32)
        addr = normalize_address(addr)
        if addr not in self.cache:
            self.cache[addr] = {}
        elif k in self.cache[addr]:
            return self.cache[addr][k]
        acct = self._get_account_unsafe(addr)
        if k in ACCOUNT_SPECIAL_PARAMS:
            v = getattr(acct, k)
        else:
            t = SecureTrie(Trie(self.trie.db))
            if 'storage' in self.cache[addr]:
                t.root_hash = self.cache[addr]['storage']
            else:
                t.root_hash = acct.storage
            v = t.get(k)
            v = rlp.decode(v) if v else b''
        self.cache[addr][k] = v
        return v

    get_balance = lambda self, addr: self.get_storage(addr, 'balance')

    # set_balance = lambda self, addr, v: self.set_storage(addr, 'balance', v)
    def set_balance( self, addr, v):
        self.set_storage(addr, 'balance', v)

    delta_balance = lambda self, addr, v: self.set_balance(addr, self.get_balance(addr) + v)

    def transfer_value(self, from_addr, to_addr, value):
        assert value >= 0
        if self.get_balance(from_addr) >= value:
            self.delta_balance(from_addr, -value)
            self.delta_balance(to_addr, value)
            return True
        return False

    get_nonce = lambda self, addr: self.get_storage(addr, 'nonce')
    set_nonce = lambda self, addr, v: self.set_storage(addr, 'nonce', v)
    increment_nonce = lambda self, addr: self.set_nonce(addr, self.get_nonce(addr) + 1)
    get_code = lambda self, addr: self.get_storage(addr, 'code')
    set_code = lambda self, addr, v: self.set_storage(addr, 'code', v)
    get_storage_bytes = lambda self, addr, k: self.get_storage(addr, k)
    set_storage_bytes = lambda self, addr, k, v: self.set_storage(addr, k, v)

    # get_storage_data = lambda self, addr, k: big_endian_to_int(self.get_storage(addr, k)[-32:])
    def get_storage_data (self, addr, k):
        o = big_endian_to_int(self.get_storage(addr, k)[-32:])
        return o

    # set_storage_data = lambda self, addr, k, v: self.set_storage(addr, k, encode_int(v) if isinstance(v, (int, long)) else v)
    def set_storage_data (self, addr, k, v):
        self.set_storage(addr, k, encode_int(v) if isinstance(v, (int, long)) and k not in ACCOUNT_SPECIAL_PARAMS else v)

    def account_exists(self, addr):
        if addr not in self.modified:
            o = self.trie.get(addr) != trie.BLANK_NODE
        elif self.cache[addr].get('deleted', False):
            o = False
        else:
            o = True
        return o

    def reset_storage(self, addr):
        self.set_storage(addr, 'storage', trie.BLANK_ROOT)
        if addr in self.cache:
            for k in self.cache[addr]:
                if k not in ACCOUNT_SPECIAL_PARAMS:
                    self.set_storage(addr, k, '')
        t = SecureTrie(Trie(self.trie.db))
        acct = self._get_account_unsafe(addr)
        t.root_hash = acct.storage
        for k in t.to_dict().keys():
            self.set_storage(addr, k, '')

    # Commit the cache to the trie
    def commit(self):
        rt = self.trie.root_hash
        for addr, subcache in self.cache.items():
            if addr not in self.modified:
                continue
            acct = self._get_account_unsafe(addr)
            t = SecureTrie(Trie(self.trie.db))
            t.root_hash = acct.storage
            modified = False
            for key, value in subcache.items():
                if key in ACCOUNT_SPECIAL_PARAMS:
                    if getattr(acct, key) != value:
                        assert acct._mutable
                        setattr(acct, key, value)
                        modified = True
                else:
                    curval = t.get(key)
                    curval = rlp.decode(curval) if curval else ''
                    if key in self.modified.get(addr, {}) and value != curval:
                        if value:
                            t.update(utils.zpad(key, 32), rlp.encode(value))
                        else:
                            t.delete(utils.zpad(key, 32))
                        modified = True
            # print 'new account storage', repr(addr), t.to_dict()
            # print 'new account storage 2', repr(addr), {k: t.get(k) for k in t.to_dict().keys()}
            acct.storage = t.root_hash
            if addr in self.modified or True:
                if not acct.deleted:
                    acct._cached_rlp = None
                    self.trie.update(addr, rlp.encode(acct))
                else:
                    self.trie.delete(addr)
        self.journal.append(('~root', (self.cache, self.modified), rt, None))  # FIXME USED?
        self.cache = {}
        self.modified = {}

    def reset_journal(self):
        "resets the journal. should be called after State.commit unless there is a better strategy"
        self.journal = []


    def del_account(self, address):
        """Delete an account.

        :param address: the address of the account (binary or hex string)
        """
        if len(address) == 40:
            address = decode_hex(address)
        assert len(address) == 20
        blank_acct = Account.blank_account(self.db, self.config['ACCOUNT_INITIAL_NONCE'])
        for param in ACCOUNT_OUTPUTTABLE_PARAMS:
            self.set_storage(address, param, getattr(blank_acct, param))
        self.reset_storage(address)
        self.set_storage(address, 'deleted', True)

    def add_log(self, log):
        for listener in self.log_listeners:
            listener(log)
        self.journal.append(('~logs', None, len(self.logs), None))
        self.logs.append(log)

    def add_suicide(self, suicide):
        self.journal.append(('~suicides', None, len(self.suicides), None))
        self.suicides.append(suicide)

    # Returns a value x, where State.revert(x) at any later point will return
    # you to the point at which the snapshot was made (unless journal_reset was called).
    def snapshot(self):
        return (self.trie.root_hash, len(self.journal))

    # Reverts to the provided snapshot
    def revert(self, snapshot):
        root, journal_length = snapshot
        if root != self.trie.root_hash and journal_length != 0:
            raise Exception("Cannot return to this snapshot")
        self.trie.root_hash = root
        while len(self.journal) > journal_length:
            addr, key, preval, premod = self.journal.pop()
            if addr == '~root':  # FIXME IS THIS USED?
                self.trie.root_hash = preval
                self.cache, self.modified = key
            elif addr == '~logs':
                self.logs = self.logs[:preval]
            elif addr == '~suicides':
                self.suicides = self.suicides[:preval]
            elif addr == '~prev_headers':
                self.prev_headers = self.prev_headers[-preval:]
            elif addr in STATE_DEFAULTS:
                setattr(self, addr, preval)
            else:
                self.cache[addr][key] = preval
                if not premod:
                    del self.modified[addr]

    # Converts the state tree to a dictionary
    def to_dict(self):
        state_dump = {}
        for address in self.trie.to_dict().keys():
            acct = self._get_account_unsafe(address)
            storage_dump = {}
            acct_trie = SecureTrie(Trie(self.db))
            acct_trie.root_hash = acct.storage
            for key, v in acct_trie.to_dict().items():
                storage_dump[encode_hex(key.lstrip('\x00') or '\x00')] = encode_hex(rlp.decode(v))
            acct_dump = {"storage": storage_dump}
            for c in ACCOUNT_OUTPUTTABLE_PARAMS:
                acct_dump[c] = snapshot_form(getattr(acct, c))
            state_dump[encode_hex(address)] = acct_dump
        for address, v in self.cache.items():
            if encode_hex(address) not in state_dump:
                state_dump[encode_hex(address)] = {"storage":{}}
                blanky = Account.blank_account(self.db, self.config['ACCOUNT_INITIAL_NONCE'])
                for c in ACCOUNT_OUTPUTTABLE_PARAMS:
                    state_dump[encode_hex(address)][c] = snapshot_form(getattr(blanky, c))
            acct_dump = state_dump[encode_hex(address)]
            for key, val in v.items():
                if key in ACCOUNT_SPECIAL_PARAMS:
                    acct_dump[key] = snapshot_form(val)
                else:
                    if val:
                        acct_dump["storage"][encode_hex(key)] = encode_hex(val)
                    elif encode_hex(key) in acct_dump["storage"]:
                        del acct_dump["storage"][val]
        return state_dump

    # Creates a state from a snapshot
    @classmethod
    def from_snapshot(cls, snapshot_data, env):
        state = State(env = env)
        if "alloc" in snapshot_data:
            for addr, data in snapshot_data["alloc"].items():
                if len(addr) == 40:
                    addr = decode_hex(addr)
                assert len(addr) == 20
                if 'wei' in data:
                    state.set_balance(addr, parse_as_int(data['wei']))
                if 'balance' in data:
                    state.set_balance(addr, parse_as_int(data['balance']))
                if 'code' in data:
                    state.set_code(addr, parse_as_bin(data['code']))
                if 'nonce' in data:
                    state.set_nonce(addr, parse_as_int(data['nonce']))
                if 'storage' in data:
                    for k, v in data['storage'].items():
                        state.set_storage_data(addr, parse_as_bin(k), parse_as_bin(v))
        elif "state_root" in snapshot_data:
            state.trie.root_hash = parse_as_bin(snapshot_data["state_root"])
        else:
            raise Exception("Must specify either alloc or state root parameter")
        for k, default in STATE_DEFAULTS.items():
            default = copy.copy(default)
            v = snapshot_data[k] if k in snapshot_data else None
            if isinstance(default, (int, long)):
                setattr(state, k, parse_as_int(v) if k in snapshot_data else default)
            elif isinstance(default, (str, bytes)):
                setattr(state, k, parse_as_bin(v) if k in snapshot_data else default)
            elif k == 'prev_headers':
                if k in snapshot_data:
                    headers = [dict_to_prev_header(h) for h in v]
                else:
                    headers = default
                setattr(state, k, headers)
            elif k == 'recent_uncles':
                if k in snapshot_data:
                    uncles = {}
                    for height, _uncles in v.items():
                        uncles[int(height)] = []
                        for uncle in _uncles:
                            uncles[int(height)].append(parse_as_bin(uncle))
                else:
                    uncles = default
                setattr(state, k, uncles)
        state.commit()
        return state

    # Creates a snapshot from a state
    def to_snapshot(self, root_only=False, no_prevblocks=False):
        snapshot = {}
        if root_only:
            # Smaller snapshot format that only includes the state root
            # (requires original DB to re-initialize)
            snapshot["state_root"] = '0x'+encode_hex(self.trie.root_hash)
        else:
            # "Full" snapshot
            snapshot["alloc"] = self.to_dict()
        # Save non-state-root variables
        for k, default in STATE_DEFAULTS.items():
            default = copy.copy(default)
            v = getattr(self, k)
            if isinstance(default, (int, long)):
                snapshot[k] = str(v)
            elif isinstance(default, (str, bytes)):
                snapshot[k] = '0x'+encode_hex(v)
            elif k == 'prev_headers' and not no_prevblocks:
                snapshot[k] = [prev_header_to_dict(h) for h in v[:self.config['PREV_HEADER_DEPTH']]]
            elif k == 'recent_uncles' and not no_prevblocks:
                snapshot[k] = {str(n): ['0x'+encode_hex(h) for h in headers] for n, headers in v.items()}
        return snapshot

    def ephemeral_clone(self):
        snapshot = self.to_snapshot(root_only=True, no_prevblocks=True)
        env2 = Env(OverlayDB(self.env.db), self.env.config)
        s = State.from_snapshot(snapshot, env2)
        s.cache = copy.deepcopy(self.cache)
        s.modified = copy.deepcopy(self.modified)
        s.journal = copy.deepcopy(self.journal)
        for param in STATE_DEFAULTS:
            setattr(s, param, getattr(self, param))
        s.recent_uncles = self.recent_uncles
        s.prev_headers = self.prev_headers
        return s

    # forks

    def _is_X_fork(self, name, at_fork_height=False):
        height =  self.config[name + '_FORK_BLKNUM']
        if self.block_number < height:
            return False
        elif at_fork_height and self.block_number > height:
            return False
        return True

    def is_METROPOLIS(self, at_fork_height=False):
        return self._is_X_fork('METROPOLIS', at_fork_height)

    def is_HOMESTEAD(self, at_fork_height=False):
        return self._is_X_fork('HOMESTEAD', at_fork_height)

    def is_SERENITY(self, at_fork_height=False):
        return self._is_X_fork('SERENITY', at_fork_height)

    def is_DAO(self, at_fork_height=False):
        return self._is_X_fork('DAO', at_fork_height)


def prev_header_to_dict(h):
    return {
        "hash": '0x'+encode_hex(h.hash),
        "number": str(h.number),
        "timestamp": str(h.timestamp),
        "difficulty": str(h.difficulty),
        "gas_used": str(h.gas_used),
        "gas_limit": str(h.gas_limit),
        "uncles_hash": '0x'+encode_hex(h.uncles_hash)
    }


BLANK_UNCLES_HASH = sha3(rlp.encode([]))

def dict_to_prev_header(h):
    return FakeHeader(hash=parse_as_bin(h['hash']),
                      number=parse_as_int(h['number']),
                      timestamp=parse_as_int(h['timestamp']),
                      difficulty=parse_as_int(h['difficulty']),
                      gas_used=parse_as_int(h.get('gas_used', '0')),
                      gas_limit=parse_as_int(h['gas_limit']),
                      uncles_hash=parse_as_bin(h.get('uncles_hash', '0x'+encode_hex(BLANK_UNCLES_HASH))))

class Account(rlp.Serializable):

    """An Ethereum account.

    :ivar nonce: the account's nonce (the number of transactions sent by the
                 account)
    :ivar balance: the account's balance in wei
    :ivar storage: the root of the account's storage trie
    :ivar code_hash: the SHA3 hash of the code associated with the account
    :ivar db: the database in which the account's code is stored
    """

    fields = [
        ('nonce', big_endian_int),
        ('balance', big_endian_int),
        ('storage', trie_root),
        ('code_hash', hash32)
    ]

    def __init__(self, nonce, balance, storage, code_hash, db):
        assert isinstance(db, BaseDB)
        self.db = db
        self._mutable = True
        self.deleted = False
        super(Account, self).__init__(nonce, balance, storage, code_hash)

    @property
    def code(self):
        """The EVM code of the account.

        This property will be read from or written to the db at each access,
        with :ivar:`code_hash` used as key.
        """
        return self.db.get(self.code_hash)

    @code.setter
    def code(self, value):
        self.code_hash = utils.sha3(value)
        # Technically a db storage leak, but doesn't really matter; the only
        # thing that fails to get garbage collected is when code disappears due
        # to a suicide
        self.db.inc_refcount(self.code_hash, value)

    @classmethod
    def blank_account(cls, db, initial_nonce=0):
        """Create a blank account

        The returned account will have zero nonce and balance, a blank storage
        trie and empty code.

        :param db: the db in which the account will store its code.
        """
        code_hash = utils.sha3(b'')
        db.put(code_hash, b'')
        o = cls(initial_nonce, 0, trie.BLANK_ROOT, code_hash, db)
        o._mutable = True
        return o
