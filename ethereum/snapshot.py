import rlp
from ethereum import blocks
from ethereum.blocks import Account, BlockHeader, Block, CachedBlock
from ethereum.utils import is_numeric, is_string, encode_hex, decode_hex, zpad, scan_bin, big_endian_to_int
from ethereum.securetrie import SecureTrie
from ethereum.trie import BLANK_NODE, BLANK_ROOT
from ethereum.pruning_trie import Trie


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
    env = chain.env
    head_block = chain.head
    base_block_hash = chain.index.get_block_by_number(max(head_block.number-recent, 0))
    base_block = chain.get(base_block_hash)

    snapshot = create_env_snapshot(base_block)
    snapshot['base'] = create_base_snapshot(base_block)
    snapshot['blocks'] = create_blocks_snapshot(base_block, head_block)
    snapshot['alloc'] = create_state_snapshot(env, base_block.state)

    return snapshot


def create_env_snapshot(base):
    return {
        'chainDifficulty': snapshot_form(base.chain_difficulty())
    }


def create_base_snapshot(base):
    return snapshot_form(rlp.encode(base.header))


def create_state_snapshot(env, state_trie):
    alloc = dict()
    count = 0
    for addr, account_rlp in state_trie.iter_branch():
        alloc[encode_hex(addr)] = create_account_snapshot(env, account_rlp)
        count += 1
        print "[%d] created account snapshot %s" % (count, encode_hex(addr))
    return alloc


def create_account_snapshot(env, rlpdata):
    account = get_account(env, rlpdata)
    storage_trie = SecureTrie(Trie(env.db, account.storage))
    storage = dict()
    for k, v in storage_trie.iter_branch():
        storage[encode_hex(k.lstrip('\x00') or '\x00')] = encode_hex(v)
    return {
        'nonce': snapshot_form(account.nonce),
        'balance': snapshot_form(account.balance),
        'code': encode_hex(account.code),
        'storage': storage
    }


def create_blocks_snapshot(base, head):
    recent_blocks = list()
    block = head
    while True:
        recent_blocks.append(snapshot_form(rlp.encode(block)))
        if block.prevhash != base.hash:
            block = block.get_parent()
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
    head_block_rlp = scan_bin(snapshot['blocks'][limit-1])
    head_header_data = rlp.decode(head_block_rlp)[0]

    state = load_state(chain.env, snapshot['alloc'])
    assert state.root_hash == base_header.state_root

    _get_block_header = blocks.get_block_header
    def get_block_header(db, blockhash):
        if blockhash == first_header_data[0]:  # first block's prevhash
            return base_header
        return _get_block_header(db, blockhash)
    blocks.get_block_header = get_block_header

    _get_block = blocks.get_block
    def get_block(env, blockhash):
        if blockhash == first_header_data[0]:
            return FakeBlock(env, get_block_header(env.db, blockhash), int(snapshot['chainDifficulty']))
        return _get_block(env, blockhash)
    blocks.get_block = get_block

    def validate_uncles():
        return True

    print "Start loading recent blocks from snapshot"
    first_block = rlp.decode(first_block_rlp, Block, env=chain.env)
    chain.index.add_block(first_block)
    chain._store_block(first_block)
    chain.blockchain.put('HEAD', first_block.hash)
    chain.blockchain.put(chain.index._block_by_number_key(first_block.number), first_block.hash)
    chain.blockchain.commit()
    chain._update_head_candidate()

    count = 0
    for block_rlp in snapshot['blocks'][1:]:
        block_rlp = scan_bin(block_rlp)
        block = rlp.decode(block_rlp, Block, env=chain.env)
        if count < chain.env.config['MAX_UNCLE_DEPTH']+2:
            block.__setattr__('validate_uncles', validate_uncles)
        if not chain.add_block(block):
            print "Failed to load block #%d (%s), abort." % (block.number, encode_hex(block.hash)[:8])
        else:
            count += 1
            print "[%d] block #%d (%s) added" % (count, block.number, encode_hex(block.hash)[:8])
    print "Snapshot loaded."


def load_state(env, alloc):
    db = env.db
    state = SecureTrie(Trie(db, BLANK_ROOT))
    count = 0
    print "Start loading state from snapshot"
    for addr in alloc:
        account = alloc[addr]
        acct = Account.blank_account(db, env.config['ACCOUNT_INITIAL_NONCE'])
        if len(account['storage']) > 0:
            t = SecureTrie(Trie(db, BLANK_ROOT))
            for k in account['storage']:
                v = account['storage'][k]
                enckey = zpad(decode_hex(k), 32)
                t.update(enckey, decode_hex(v))
            acct.storage = t.root_hash
        if account['nonce']:
            acct.nonce = int(account['nonce'])
        if account['balance']:
            acct.balance = int(account['balance'])
        if account['code']:
            acct.code = decode_hex(account['code'])
        state.update(decode_hex(addr), rlp.encode(acct))
        count += 1
        if count % 1000 == 0:
            db.commit()
        print "[%d] loaded account %s" % (count, addr)
    db.commit()
    return state


def get_account(env, rlpdata):
    if rlpdata != BLANK_NODE:
        return rlp.decode(rlpdata, Account, db=env.db)
    else:
        return Account.blank_account(env.db, env.config['ACCOUNT_INITIAL_NONCE'])


def snapshot_form(val):
    if is_numeric(val):
        return str(val)
    elif is_string(val):
        return b'0x' + encode_hex(val)