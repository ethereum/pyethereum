import rlp
from ethereum.block import BlockHeader, Block
from ethereum.utils import is_numeric, is_string, encode_hex, decode_hex, zpad, scan_bin, big_endian_to_int
from ethereum import common
from ethereum.pow import consensus
from ethereum.state import State, Account
from ethereum.securetrie import SecureTrie
from ethereum.trie import BLANK_NODE, BLANK_ROOT
from ethereum.experimental.pruning_trie import Trie


class FakeHeader(object):
    def __init__(self, number, hash, state_root, gas_limit, timestamp):
        self.number = number
        self.hash = hash
        self.state_root = state_root
        self.gas_limit = gas_limit
        self.timestamp = timestamp


class FakeBlock(object):
    def __init__(self, env, header, chain_diff):
        self.env = env
        self.config = env.config
        self.header = header
        self.uncles = []
        self.number = header.number
        self.hash = header.hash
        self.gas_limit = header.gas_limit
        self.difficulty = header.difficulty
        self.timestamp = header.timestamp
        self._chain_diff = chain_diff

    def chain_difficulty(self):
        return self._chain_diff

    def has_parent(self):
        return False

    def get_ancestor_list(self, n):
        if n == 0 or self.header.number == 0:
            return []
        p = FakeBlock(self.env, self.header, 0)
        return [p] + p.get_ancestor_list(n - 1)


def create_snapshot(chain, recent=1024):
    assert recent > chain.env.config['MAX_UNCLE_DEPTH'] + 2

    head_block = chain.head
    base_block = chain.get_block_by_number(max(head_block.number - recent, 0))
    return {
        'base': snapshot_form(rlp.encode(base_block.header)),
        'chainDifficulty': snapshot_form(chain.get_score(base_block)),
        'blocks': create_blocks_snapshot(chain, base_block, head_block),
        'alloc': create_state_snapshot(chain, base_block)
    }


def create_state_snapshot(chain, block):
    env = chain.env
    state = State(block.state_root, env)
    alloc = dict()
    count = 0
    for addr, account_rlp in state.trie.iter_branch():
        alloc[encode_hex(addr)] = create_account_snapshot(env, account_rlp)
        count += 1
        print("[%d] created account snapshot %s" % (count, encode_hex(addr)))
    return alloc


def create_account_snapshot(env, rlpdata):
    account = get_account(env, rlpdata)
    storage_trie = SecureTrie(Trie(env.db, account.storage))
    storage = dict()
    for k, v in storage_trie.iter_branch():
        storage[encode_hex(k.lstrip(b'\x00') or b'\x00')] = encode_hex(v)
    return {
        'nonce': snapshot_form(account.nonce),
        'balance': snapshot_form(account.balance),
        'code': encode_hex(account.code),
        'storage': storage
    }


def create_blocks_snapshot(chain, base, head):
    recent_blocks = list()
    block = head
    while True:
        recent_blocks.append(snapshot_form(rlp.encode(block)))
        if block and block.prevhash != base.hash:
            block = chain.get_parent(block)
        else:
            break
    recent_blocks.reverse()
    return recent_blocks


def load_snapshot(chain, snapshot):
    base_header = rlp.decode(scan_bin(snapshot['base']), BlockHeader)

    limit = len(snapshot['blocks'])
    # first block is child of base block
    first_block_rlp = scan_bin(snapshot['blocks'][0])
    first_header_data = rlp.decode(first_block_rlp)[0]
    head_block_rlp = scan_bin(snapshot['blocks'][limit - 1])
    head_header_data = rlp.decode(head_block_rlp)[0]

    trie = load_state(chain.env, snapshot['alloc'])
    assert trie.root_hash == base_header.state_root
    chain.state.trie = trie
    chain.env.db.put(b'score:' + base_header.hash, snapshot['chainDifficulty'])
    chain.env.db.commit()

    print("Start loading recent blocks from snapshot")
    vbh = common.validate_header
    vus = consensus.validate_uncles

    def _vbh(state, header):
        return True

    def _vus(state, block):
        return True
    common.validate_header = _vbh
    consensus.validate_uncles = _vus
    # add the first block
    first_block = rlp.decode(first_block_rlp, sedes=Block)
    chain.head_hash = first_block.header.prevhash
    chain.add_block(first_block)
    assert chain.head_hash == first_block.header.hash
    common.validate_header = vbh

    count = 0
    for block_rlp in snapshot['blocks'][1:]:
        block_rlp = scan_bin(block_rlp)
        block = rlp.decode(block_rlp, Block)
        if count == chain.state.config['MAX_UNCLE_DEPTH'] + 2:
            consensus.validate_uncles = vus
        if not chain.add_block(block):
            print("Failed to load block #%d (%s), abort." % (block.number, encode_hex(block.hash)[:8]))
        else:
            count += 1
            print("[%d] block #%d (%s) added" % (count, block.number, encode_hex(block.hash)[:8]))
    print("Snapshot loaded.")


def load_state(env, alloc):
    db = env.db
    state = SecureTrie(Trie(db, BLANK_ROOT))
    count = 0
    print("Start loading state from snapshot")
    for addr in alloc:
        print("[%d] loading account %s" % (count, addr))
        account = alloc[addr]
        acct = Account.blank_account(db, env.config['ACCOUNT_INITIAL_NONCE'])
        if len(account['storage']) > 0:
            t = SecureTrie(Trie(db, BLANK_ROOT))
            c = 0
            for k in account['storage']:
                v = account['storage'][k]
                enckey = zpad(decode_hex(k), 32)
                t.update(enckey, decode_hex(v))
                c += 1
                if c % 1000 and len(db.db_service.uncommitted) > 50000:
                    print("%d uncommitted. committing..." % len(db.db_service.uncommitted))
                    db.commit()
            acct.storage = t.root_hash
        if account['nonce']:
            acct.nonce = int(account['nonce'])
        if account['balance']:
            acct.balance = int(account['balance'])
        if account['code']:
            acct.code = decode_hex(account['code'])
        state.update(decode_hex(addr), rlp.encode(acct))
        count += 1
    db.commit()
    return state


def get_account(env, rlpdata):
    if rlpdata != BLANK_NODE:
        return rlp.decode(rlpdata, Account, env=env)
    else:
        return Account.blank_account(env, env.config['ACCOUNT_INITIAL_NONCE'])


def snapshot_form(val):
    if is_numeric(val):
        return str(val)
    elif is_string(val):
        return b'0x' + encode_hex(val)
