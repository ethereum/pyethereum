from ethereum.state import State, STATE_DEFAULTS
from ethereum.block import Block, BlockHeader, FakeHeader
from ethereum.utils import decode_hex, big_endian_to_int, encode_hex
from ethereum.state_transition import apply_block, initialize

def parse_as_bin(s):
    return decode_hex(s[2:] if s[:2] == '0x' else s)

def parse_as_int(s):
    return int(s[2:], 16) if s[:2] == '0x' else int(s)


def state_from_snapshot(snapshot_data, db):
    state = State(db = db)
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
        v = snapshot_data[k] if k in snapshot_data else None
        if isinstance(default, (int, long)):
            setattr(state, k, parse_as_int(v) if k in snapshot_data else default)
        elif isinstance(default, (str, bytes)):
            setattr(state, k, parse_as_bin(v) if k in snapshot_data else default)
        elif k == 'prev_headers':
            headers = []
            if k in snapshot_data:
                for i, h in enumerate(v):
                    headers.append(FakeHeader(hash=parse_as_bin(h['hash']),
                                              number=state.block_number - i,
                                              timestamp=parse_as_int(h['timestamp']),
                                              difficulty=parse_as_int(h['difficulty']),
                                              gas_limit=parse_as_int(h['gas_limit'])))
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


def to_snapshot(state, root_only=False):
    snapshot = {}
    if root_only:
        snapshot["state_root"] = '0x'+encode_hex(state.trie.root_hash)
    else:
        snapshot["alloc"] = state.to_dict()
    for k, default in STATE_DEFAULTS.items():
        v = getattr(state, k)
        if isinstance(default, (int, long)):
            snapshot[k] = str(v)
        elif isinstance(default, (str, bytes)):
            snapshot[k] = '0x'+encode_hex(v)
        elif k == 'prev_headers':
            snapshot[k] = [{"hash": '0x'+encode_hex(h.hash),
                            "number": str(h.number),
                            "timestamp": str(h.timestamp),
                            "difficulty": str(h.difficulty),
                            "gas_limit": str(h.gas_limit)} for h in v]
        elif k == 'recent_uncles':
            snapshot[k] = {str(n): ['0x'+encode_hex(h) for h in headers] for n, headers in v.items()}
    return snapshot
    


def state_from_genesis_declaration(genesis_data, db):
    h = BlockHeader(nonce=parse_as_bin(genesis_data["nonce"]),
                    difficulty=parse_as_int(genesis_data["difficulty"]),
                    mixhash=parse_as_bin(genesis_data["mixhash"]),
                    coinbase=parse_as_bin(genesis_data["coinbase"]),
                    timestamp=parse_as_int(genesis_data["timestamp"]),
                    prevhash=parse_as_bin(genesis_data["parentHash"]),
                    extra_data=parse_as_bin(genesis_data["extraData"]),
                    gas_limit=parse_as_int(genesis_data["gasLimit"]))
    blk = Block(h, [], [])
    state = State(db=db)
    for addr, data in genesis_data["alloc"].items():
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
    initialize(state, blk)
    state.commit()
    blk.header.state_root = state.trie.root_hash
    state.prev_headers=[h]
    return state
