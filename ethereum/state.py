import rlp
from ethereum.utils import normalize_address, hash32, trie_root, \
    big_endian_int, address, int256, encode_hex, encode_int, \
    big_endian_to_int, int_to_addr, zpad, parse_as_bin, parse_as_int, \
    decode_hex, sha3, is_string, is_numeric
from rlp.sedes import big_endian_int, Binary, binary, CountableList
from ethereum import utils
from ethereum import trie
from ethereum.trie import Trie
from ethereum.securetrie import SecureTrie
from ethereum.config import default_config, Env
from ethereum.block import FakeHeader
from ethereum.db import BaseDB, EphemDB, OverlayDB, RefcountDB
from ethereum.specials import specials as default_specials
import copy
import sys
if sys.version_info.major == 2:
    from repoze.lru import lru_cache
else:
    from functools import lru_cache


BLANK_HASH = utils.sha3(b'')
BLANK_ROOT = utils.sha3rlp(b'')

THREE = b'\x00' * 19 + b'\x03'


def snapshot_form(val):
    if is_numeric(val):
        return str(val)
    elif is_string(val):
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
    "receipts": [],
    "bloom": 0,
    "suicides": [],
    "recent_uncles": {},
    "prev_headers": [],
    "refunds": 0,
}


class Account(rlp.Serializable):

    fields = [
        ('nonce', big_endian_int),
        ('balance', big_endian_int),
        ('storage', trie_root),
        ('code_hash', hash32)
    ]

    def __init__(self, nonce, balance, storage, code_hash, env, address):
        assert isinstance(env.db, BaseDB)
        self.env = env
        self.address = address
        super(Account, self).__init__(nonce, balance, storage, code_hash)
        self.storage_cache = {}
        self.storage_trie = SecureTrie(Trie(RefcountDB(self.env.db)))
        self.storage_trie.root_hash = self.storage
        self.touched = False
        self.existent_at_start = True
        self._mutable = True
        self.deleted = False

    def commit(self):
        for k, v in self.storage_cache.items():
            if v:
                self.storage_trie.update(utils.encode_int32(k), rlp.encode(v))
            else:
                self.storage_trie.delete(utils.encode_int32(k))
        self.storage_cache = {}
        self.storage = self.storage_trie.root_hash

    @property
    def code(self):
        return self.env.db.get(self.code_hash)

    @code.setter
    def code(self, value):
        self.code_hash = utils.sha3(value)
        # Technically a db storage leak, but doesn't really matter; the only
        # thing that fails to get garbage collected is when code disappears due
        # to a suicide
        self.env.db.put(self.code_hash, value)

    def get_storage_data(self, key):
        if key not in self.storage_cache:
            v = self.storage_trie.get(utils.encode_int32(key))
            self.storage_cache[key] = utils.big_endian_to_int(
                rlp.decode(v) if v else b'')
        return self.storage_cache[key]

    def set_storage_data(self, key, value):
        self.storage_cache[key] = value

    @classmethod
    def blank_account(cls, env, address, initial_nonce=0):
        env.db.put(BLANK_HASH, b'')
        o = cls(initial_nonce, 0, trie.BLANK_ROOT, BLANK_HASH, env, address)
        o.existent_at_start = False
        return o

    def is_blank(self):
        return self.nonce == 0 and self.balance == 0 and self.code_hash == BLANK_HASH

    @property
    def exists(self):
        if self.is_blank():
            return self.touched or (
                self.existent_at_start and not self.deleted)
        return True

    def to_dict(self):
        odict = self.storage_trie.to_dict()
        for k, v in self.storage_cache.items():
            odict[utils.encode_int(k)] = rlp.encode(utils.encode_int(v))
        return {'balance': str(self.balance), 'nonce': str(self.nonce), 'code': '0x' + encode_hex(self.code),
                'storage': {'0x' + encode_hex(key.lstrip(b'\x00') or b'\x00'):
                            '0x' + encode_hex(rlp.decode(val)) for key, val in odict.items()}}


# from ethereum.state import State
class State():

    def __init__(self, root=b'', env=Env(), executing_on_head=False, **kwargs):
        self.env = env
        self.trie = SecureTrie(Trie(RefcountDB(self.db), root))
        for k, v in STATE_DEFAULTS.items():
            setattr(self, k, kwargs.get(k, copy.copy(v)))
        self.journal = []
        self.cache = {}
        self.log_listeners = []
        self.deletes = []
        self.changed = {}
        self.executing_on_head = executing_on_head

    @property
    def db(self):
        return self.env.db

    @property
    def config(self):
        return self.env.config

    def get_block_hash(self, n):
        if self.block_number < n or n > 256 or n < 0:
            o = b'\x00' * 32
        else:
            o = self.prev_headers[n].hash if self.prev_headers[n] else b'\x00' * 32
        return o

    def add_block_header(self, block_header):
        self.prev_headers = [block_header] + self.prev_headers

    def get_and_cache_account(self, address):
        if address in self.cache:
            return self.cache[address]
        if self.executing_on_head and False:
            try:
                rlpdata = self.db.get(b'address:' + address)
            except KeyError:
                rlpdata = b''
        else:
            rlpdata = self.trie.get(address)
        if rlpdata != trie.BLANK_NODE:
            o = rlp.decode(rlpdata, Account, env=self.env, address=address)
        else:
            o = Account.blank_account(
                self.env, address, self.config['ACCOUNT_INITIAL_NONCE'])
        self.cache[address] = o
        o._mutable = True
        o._cached_rlp = None
        return o

    def get_balance(self, address):
        return self.get_and_cache_account(
            utils.normalize_address(address)).balance

    def get_code(self, address):
        return self.get_and_cache_account(
            utils.normalize_address(address)).code

    def get_nonce(self, address):
        return self.get_and_cache_account(
            utils.normalize_address(address)).nonce

    def set_and_journal(self, acct, param, val):
        # self.journal.append((acct, param, getattr(acct, param)))
        preval = getattr(acct, param)
        self.journal.append(lambda: setattr(acct, param, preval))
        setattr(acct, param, val)

    def set_balance(self, address, value):
        acct = self.get_and_cache_account(utils.normalize_address(address))
        self.set_and_journal(acct, 'balance', value)
        self.set_and_journal(acct, 'touched', True)

    def set_code(self, address, value):
        # assert is_string(value)
        acct = self.get_and_cache_account(utils.normalize_address(address))
        self.set_and_journal(acct, 'code', value)
        self.set_and_journal(acct, 'touched', True)

    def set_nonce(self, address, value):
        acct = self.get_and_cache_account(utils.normalize_address(address))
        self.set_and_journal(acct, 'nonce', value)
        self.set_and_journal(acct, 'touched', True)

    def delta_balance(self, address, value):
        address = utils.normalize_address(address)
        acct = self.get_and_cache_account(address)
        newbal = acct.balance + value
        self.set_and_journal(acct, 'balance', newbal)
        self.set_and_journal(acct, 'touched', True)

    def increment_nonce(self, address):
        address = utils.normalize_address(address)
        acct = self.get_and_cache_account(address)
        newnonce = acct.nonce + 1
        self.set_and_journal(acct, 'nonce', newnonce)
        self.set_and_journal(acct, 'touched', True)

    def get_storage_data(self, address, key):
        return self.get_and_cache_account(
            utils.normalize_address(address)).get_storage_data(key)

    def set_storage_data(self, address, key, value):
        acct = self.get_and_cache_account(utils.normalize_address(address))
        preval = acct.get_storage_data(key)
        acct.set_storage_data(key, value)
        self.journal.append(lambda: acct.set_storage_data(key, preval))
        self.set_and_journal(acct, 'touched', True)

    def add_suicide(self, address):
        self.suicides.append(address)
        self.journal.append(lambda: self.suicides.pop())

    def add_log(self, log):
        for listener in self.log_listeners:
            listener(log)
        self.logs.append(log)
        self.journal.append(lambda: self.logs.pop())

    def add_receipt(self, receipt):
        self.receipts.append(receipt)
        self.journal.append(lambda: self.receipts.pop())

    def add_refund(self, value):
        preval = self.refunds
        self.refunds += value
        self.journal.append(lambda: setattr(self.refunds, preval))

    def snapshot(self):
        return (self.trie.root_hash, len(self.journal), {
                k: copy.copy(getattr(self, k)) for k in STATE_DEFAULTS})

    def revert(self, snapshot):
        h, L, auxvars = snapshot
        # Compatibility with weird geth+parity bug
        three_touched = self.cache[THREE].touched if THREE in self.cache else False
        while len(self.journal) > L:
            try:
                lastitem = self.journal.pop()
                lastitem()
            except Exception as e:
                print(e)
        if h != self.trie.root_hash:
            assert L == 0
            self.trie.root_hash = h
            self.cache = {}
        for k in STATE_DEFAULTS:
            setattr(self, k, copy.copy(auxvars[k]))
        if three_touched and 2675000 < self.block_number < 2675200:  # Compatibility with weird geth+parity bug
            self.delta_balance(THREE, 0)

    def set_param(self, k, v):
        preval = getattr(self, k)
        self.journal.append(lambda: setattr(self, k, preval))
        setattr(self, k, v)

    def is_SERENITY(self, at_fork_height=False):
        if at_fork_height:
            return self.block_number == self.config['SERENITY_FORK_BLKNUM']
        else:
            return self.block_number >= self.config['SERENITY_FORK_BLKNUM']

    def is_HOMESTEAD(self, at_fork_height=False):
        if at_fork_height:
            return self.block_number == self.config['HOMESTEAD_FORK_BLKNUM']
        else:
            return self.block_number >= self.config['HOMESTEAD_FORK_BLKNUM']

    def is_METROPOLIS(self, at_fork_height=False):
        if at_fork_height:
            return self.block_number == self.config['METROPOLIS_FORK_BLKNUM']
        else:
            return self.block_number >= self.config['METROPOLIS_FORK_BLKNUM']

    def is_CONSTANTINOPLE(self, at_fork_height=False):
        if at_fork_height:
            return self.block_number == self.config['CONSTANTINOPLE_FORK_BLKNUM']
        else:
            return self.block_number >= self.config['CONSTANTINOPLE_FORK_BLKNUM']

    def is_ANTI_DOS(self, at_fork_height=False):
        if at_fork_height:
            return self.block_number == self.config['ANTI_DOS_FORK_BLKNUM']
        else:
            return self.block_number >= self.config['ANTI_DOS_FORK_BLKNUM']

    def is_SPURIOUS_DRAGON(self, at_fork_height=False):
        if at_fork_height:
            return self.block_number == self.config['SPURIOUS_DRAGON_FORK_BLKNUM']
        else:
            return self.block_number >= self.config['SPURIOUS_DRAGON_FORK_BLKNUM']

    def is_DAO(self, at_fork_height=False):
        if at_fork_height:
            return self.block_number == self.config['DAO_FORK_BLKNUM']
        else:
            return self.block_number >= self.config['DAO_FORK_BLKNUM']

    def account_exists(self, address):
        if self.is_SPURIOUS_DRAGON():
            o = not self.get_and_cache_account(
                utils.normalize_address(address)).is_blank()
        else:
            a = self.get_and_cache_account(address)
            if a.deleted and not a.touched:
                return False
            if a.touched:
                return True
            else:
                return a.existent_at_start
        return o

    def transfer_value(self, from_addr, to_addr, value):
        assert value >= 0
        if self.get_balance(from_addr) >= value:
            self.delta_balance(from_addr, -value)
            self.delta_balance(to_addr, value)
            return True
        return False

    def account_to_dict(self, address):
        return self.get_and_cache_account(
            utils.normalize_address(address)).to_dict()

    def commit(self, allow_empties=False):
        for addr, acct in self.cache.items():
            if acct.touched or acct.deleted:
                acct.commit()
                self.deletes.extend(acct.storage_trie.deletes)
                self.changed[addr] = True
                if self.account_exists(addr) or allow_empties:
                    self.trie.update(addr, rlp.encode(acct))
                    if self.executing_on_head:
                        self.db.put(b'address:' + addr, rlp.encode(acct))
                else:
                    self.trie.delete(addr)
                    if self.executing_on_head:
                        try:
                            self.db.delete(b'address:' + addr)
                        except KeyError:
                            pass
        self.deletes.extend(self.trie.deletes)
        self.trie.deletes = []
        self.cache = {}
        self.journal = []

    def to_dict(self):
        for addr in self.trie.to_dict().keys():
            self.get_and_cache_account(addr)
        return {encode_hex(addr): acct.to_dict()
                for addr, acct in self.cache.items()}

    def del_account(self, address):
        self.set_balance(address, 0)
        self.set_nonce(address, 0)
        self.set_code(address, b'')
        self.reset_storage(address)
        self.set_and_journal(
            self.get_and_cache_account(
                utils.normalize_address(address)),
            'deleted',
            True)
        self.set_and_journal(
            self.get_and_cache_account(
                utils.normalize_address(address)),
            'touched',
            False)
        # self.set_and_journal(self.get_and_cache_account(utils.normalize_address(address)), 'existent_at_start', False)

    def reset_storage(self, address):
        acct = self.get_and_cache_account(address)
        pre_cache = acct.storage_cache
        acct.storage_cache = {}
        self.journal.append(lambda: setattr(acct, 'storage_cache', pre_cache))
        pre_root = acct.storage_trie.root_hash
        self.journal.append(
            lambda: setattr(
                acct.storage_trie,
                'root_hash',
                pre_root))
        acct.storage_trie.root_hash = BLANK_ROOT

    # Creates a snapshot from a state
    def to_snapshot(self, root_only=False, no_prevblocks=False):
        snapshot = {}
        if root_only:
            # Smaller snapshot format that only includes the state root
            # (requires original DB to re-initialize)
            snapshot["state_root"] = '0x' + encode_hex(self.trie.root_hash)
        else:
            # "Full" snapshot
            snapshot["alloc"] = self.to_dict()
        # Save non-state-root variables
        for k, default in STATE_DEFAULTS.items():
            default = copy.copy(default)
            v = getattr(self, k)
            if is_numeric(default):
                snapshot[k] = str(v)
            elif isinstance(default, (str, bytes)):
                snapshot[k] = '0x' + encode_hex(v)
            elif k == 'prev_headers' and not no_prevblocks:
                snapshot[k] = [prev_header_to_dict(
                    h) for h in v[:self.config['PREV_HEADER_DEPTH']]]
            elif k == 'recent_uncles' and not no_prevblocks:
                snapshot[k] = {str(n): ['0x' + encode_hex(h)
                                        for h in headers] for n, headers in v.items()}
        return snapshot

    # Creates a state from a snapshot
    @classmethod
    def from_snapshot(cls, snapshot_data, env, executing_on_head=False):
        state = State(env=env)
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
                        state.set_storage_data(
                            addr,
                            big_endian_to_int(parse_as_bin(k)),
                            big_endian_to_int(parse_as_bin(v)))
        elif "state_root" in snapshot_data:
            state.trie.root_hash = parse_as_bin(snapshot_data["state_root"])
        else:
            raise Exception(
                "Must specify either alloc or state root parameter")
        for k, default in STATE_DEFAULTS.items():
            default = copy.copy(default)
            v = snapshot_data[k] if k in snapshot_data else None
            if is_numeric(default):
                setattr(state, k, parse_as_int(v)
                        if k in snapshot_data else default)
            elif is_string(default):
                setattr(state, k, parse_as_bin(v)
                        if k in snapshot_data else default)
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
        if executing_on_head:
            state.executing_on_head = True
        state.commit()
        state.changed = {}
        return state

    def ephemeral_clone(self):
        snapshot = self.to_snapshot(root_only=True, no_prevblocks=True)
        env2 = Env(OverlayDB(self.env.db), self.env.config)
        s = State.from_snapshot(snapshot, env2)
        for param in STATE_DEFAULTS:
            setattr(s, param, getattr(self, param))
        s.recent_uncles = self.recent_uncles
        s.prev_headers = self.prev_headers
        for acct in self.cache.values():
            assert not acct.touched or not acct.deleted
        s.journal = copy.copy(self.journal)
        s.cache = {}
        return s


def prev_header_to_dict(h):
    return {
        "hash": '0x' + encode_hex(h.hash),
        "number": str(h.number),
        "timestamp": str(h.timestamp),
        "difficulty": str(h.difficulty),
        "gas_used": str(h.gas_used),
        "gas_limit": str(h.gas_limit),
        "uncles_hash": '0x' + encode_hex(h.uncles_hash)
    }


BLANK_UNCLES_HASH = sha3(rlp.encode([]))


def dict_to_prev_header(h):
    return FakeHeader(hash=parse_as_bin(h['hash']),
                      number=parse_as_int(h['number']),
                      timestamp=parse_as_int(h['timestamp']),
                      difficulty=parse_as_int(h['difficulty']),
                      gas_used=parse_as_int(h.get('gas_used', '0')),
                      gas_limit=parse_as_int(h['gas_limit']),
                      uncles_hash=parse_as_bin(h.get('uncles_hash', '0x' + encode_hex(BLANK_UNCLES_HASH))))
