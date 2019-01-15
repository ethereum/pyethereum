from ethereum.state import State
from ethereum.block import Block, BlockHeader, BLANK_UNCLES_HASH
from ethereum.utils import (
    decode_hex,
    big_endian_to_int,
    encode_hex,
    parse_as_bin,
    parse_as_int,
    normalize_address,
    to_string,
)
from ethereum.config import Env
from ethereum.consensus_strategy import get_consensus_strategy
from ethereum.db import OverlayDB, RefcountDB
import rlp
import json


def block_from_genesis_declaration(genesis_data, env):
    h = BlockHeader(nonce=parse_as_bin(genesis_data["nonce"]),
                    difficulty=parse_as_int(genesis_data["difficulty"]),
                    mixhash=parse_as_bin(
        genesis_data.get(
            "mixhash", genesis_data.get(
                "mixHash", "0" * 64))),
        coinbase=parse_as_bin(genesis_data["coinbase"]),
        bloom=parse_as_int(genesis_data.get("bloom", "0")),
        timestamp=parse_as_int(genesis_data["timestamp"]),
        prevhash=parse_as_bin(genesis_data["parentHash"]),
        extra_data=parse_as_bin(genesis_data["extraData"]),
        gas_used=parse_as_int(genesis_data.get("gasUsed", "0")),
        gas_limit=parse_as_int(genesis_data["gasLimit"]))
    return Block(h, [], [])


def state_from_genesis_declaration(
        genesis_data, env, block=None, allow_empties=False, executing_on_head=False):
    if block:
        assert isinstance(block, Block)
    else:
        block = block_from_genesis_declaration(genesis_data, env)

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
                state.set_storage_data(
                    addr, big_endian_to_int(
                        parse_as_bin(k)), big_endian_to_int(
                        parse_as_bin(v)))
    get_consensus_strategy(state.config).initialize(state, block)
    if executing_on_head:
        state.executing_on_head = True
    state.commit(allow_empties=allow_empties)
    print('deleting %d' % len(state.deletes))
    rdb = RefcountDB(state.db)
    for delete in state.deletes:
        rdb.delete(delete)
    block.header.state_root = state.trie.root_hash
    state.changed = {}
    state.prev_headers = [block.header]
    return state


def initialize_genesis_keys(state, genesis):
    db = state.db
    db.put(b'GENESIS_NUMBER', to_string(genesis.header.number))
    db.put(b'GENESIS_HASH', to_string(genesis.header.hash))
    db.put(b'GENESIS_STATE', json.dumps(state.to_snapshot()))
    db.put(b'GENESIS_RLP', rlp.encode(genesis))
    db.put(b'block:0', genesis.header.hash)
    db.put(b'score:' + genesis.header.hash, "0")
    db.put(b'state:' + genesis.header.hash, state.trie.root_hash)
    db.put(genesis.header.hash, b'GENESIS')
    db.commit()


def mk_genesis_data(env, **kwargs):
    assert isinstance(env, Env)

    allowed_args = set([
        'start_alloc',
        'parent_hash',
        'coinbase',
        'difficulty',
        'gas_limit',
        'timestamp',
        'extra_data',
        'mixhash',
        'nonce',
    ])
    assert set(kwargs.keys()).issubset(allowed_args)

    genesis_data = {
        "parentHash": kwargs.get('parent_hash', encode_hex(env.config['GENESIS_PREVHASH'])),
        "coinbase": kwargs.get('coinbase', encode_hex(env.config['GENESIS_COINBASE'])),
        "difficulty": kwargs.get('difficulty', env.config['GENESIS_DIFFICULTY']),
        "gasLimit": kwargs.get('gas_limit', env.config['GENESIS_GAS_LIMIT']),
        "timestamp": kwargs.get('timestamp', 0),
        "extraData": kwargs.get('extra_data', encode_hex(env.config['GENESIS_EXTRA_DATA'])),
        "mixhash": kwargs.get('mixhash', encode_hex(env.config['GENESIS_MIXHASH'])),
        "nonce": kwargs.get('nonce', encode_hex(env.config['GENESIS_NONCE'])),
        "alloc": kwargs.get('start_alloc', env.config['GENESIS_INITIAL_ALLOC'])
    }
    return genesis_data


def mk_genesis_block(env, **kwargs):
    genesis_data = mk_genesis_data(env, **kwargs)
    block = block_from_genesis_declaration(genesis_data, env)
    state = state_from_genesis_declaration(genesis_data, env, block=block)
    return block


def mk_basic_state(alloc, header=None, env=None, executing_on_head=False):
    env = env or Env()
    state = State(env=env, executing_on_head=executing_on_head)
    if not header:
        header = {
            "number": 0, "gas_limit": env.config['BLOCK_GAS_LIMIT'],
            "gas_used": 0, "timestamp": 1467446877, "difficulty": 1,
            "uncles_hash": '0x' + encode_hex(BLANK_UNCLES_HASH)
        }
    h = BlockHeader(number=parse_as_int(header['number']),
                    timestamp=parse_as_int(header['timestamp']),
                    difficulty=parse_as_int(header['difficulty']),
                    gas_limit=parse_as_int(header['gas_limit']),
                    uncles_hash=parse_as_bin(header['uncles_hash']))
    state.prev_headers = [h]

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
