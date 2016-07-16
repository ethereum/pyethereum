from ethereum.state import State
from ethereum.block import Block, BlockHeader, FakeHeader, BLANK_UNCLES_HASH
from ethereum.utils import decode_hex, big_endian_to_int, encode_hex, \
    parse_as_bin, parse_as_int, normalize_address
from ethereum.state_transition import initialize
from ethereum.config import Env
from ethereum.db import OverlayDB
import rlp

def state_from_genesis_declaration(genesis_data, env):
    h = BlockHeader(nonce=parse_as_bin(genesis_data["nonce"]),
                    difficulty=parse_as_int(genesis_data["difficulty"]),
                    mixhash=parse_as_bin(genesis_data.get("mixhash", genesis_data.get("mixHash", "0"*64))),
                    coinbase=parse_as_bin(genesis_data["coinbase"]),
                    bloom=parse_as_int(genesis_data.get("bloom", "0")),
                    timestamp=parse_as_int(genesis_data["timestamp"]),
                    prevhash=parse_as_bin(genesis_data["parentHash"]),
                    extra_data=parse_as_bin(genesis_data["extraData"]),
                    gas_used=parse_as_int(genesis_data.get("gasUsed", "0")),
                    gas_limit=parse_as_int(genesis_data["gasLimit"]))
    blk = Block(h, [], [])
    state = State(env=env)
    for addr, data in genesis_data["alloc"].items():
        addr = normalize_address(addr)
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


def mk_basic_state(alloc, header, env):
    state = State(env=env)
    if not header:
        header = {
            "number": 0, "gas_limit": 4712388, "gas_used": 0,
            "timestamp": 1467446877, "difficulty": 2**25, "hash": '00' * 32,
            "uncles_hash": '0x'+encode_hex(BLANK_UNCLES_HASH)
        }
    state.prev_headers = [FakeHeader(hash=parse_as_bin(header['hash']),
                                     number=parse_as_int(header['number']),
                                     timestamp=parse_as_int(header['timestamp']),
                                     difficulty=parse_as_int(header['difficulty']),
                                     gas_limit=parse_as_int(header['gas_limit']),
                                     uncles_hash=parse_as_bin(header['uncles_hash']))]
    
    for addr, data in alloc.items():
        addr = normalize_address(addr)
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

    state.block_number = header["number"]
    state.gas_limit = header["gas_limit"]
    state.timestamp = header["timestamp"]
    state.block_difficulty = header["difficulty"]
    state.commit()
    return state


