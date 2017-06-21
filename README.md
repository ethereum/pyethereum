This is the Python core library of the Ethereum project.

For the python based command line client see:
https://github.com/ethereum/pyethapp

## Installation:

``git clone https://github.com/ethereum/pyethereum/``

``cd pyethereum``

``python setup.py install``


## Components

### ethereum.pow.chain

Contains the Chain class, which can be used to manage a blockchain. Main methods are:

* `__init__(genesis=None, env=None, new_head_cb=None, reset_genesis=False, localtime=None)` - initializes with the given genesis. `env` specifies the _environment_ (including chain config and database), `new_head_cb` is a callback called when a new head is added, and `localtime` is what the chain assumes is the current timestamp. The genesis can be:
    * None - in which case it assumes `env` is given, and creates a Chain object with the data saved in `env.db`. If `reset_genesis` is set, it re-initializes the chain.
    * A `State` object
    * A genesis declaration
    * A state snapshot (`State.snapshot()`)
    * An allocation (ie. dict `{address: {balance: 1, nonce: 2, code: b'\x03\x04\x05', storage: {"0x06": "0x07"}}}`)
* `add_block(block)` - adds a block to the chain
* `process_time_queue(timestamp)` - tells the chain that the current time has increased to the new timestamp. The chain will then process any blocks that were unprocessed because they appeared too "early"
* `get_blockhash_by_number(num)` - get the block hash of a block at the given block number
* `get_block(hash)` - gets the block with the given blockhash
* `get_block_by_number(num)` - equivalent to `get_block(get_blockhash_by_number(num))`
* `get_parent(block)` - gets the parent of a block
* `get_children(block)` - gets the children of a block
* `head` (property) - gets the block at the head of the chain
* `state` (property) - gets the state at the head of the chain
* `mk_poststate_of_blockhash(hash)` - creates a state object after a given block
* `has_block(block)` - is that block in the chain? Returns True/False
* `get_chain(from, to)` - roughly equivalent to `[get_block_by_number(i) for i in range(from, to)]`, though automatically stops if it reaches the head. `from` can be elided to start from genesis, `to` can be elided to go up to the head.
* `get_tx_position(tx)` - if the transaction is in the chain, returns `(blknum, index)` where `blknum` is the block number of the block that contains the transaction and `index` is its position in the block

### ethereum.state

Contains the State class, which is used to manage a state. Main methods are:

* `__init__(root_hash, env, **kwargs)` - initializes a state with the given root hash, the given env (which includes a config and database) and the given auxiliary arguments. These include:
    * `txindex` - the transaction index
    * `gas_used` - amount of gas used
    * `gas_limit` - block gas limit
    * `block_number` - block number
    * `block_coinbase` - block coinbase address
    * `block_difficulty` - block difficulty
    * `timestamp` - timestamp
    * `logs` - logs created so far
    * `receipts` - receipts created so far (from previous transactions in the current block)
    * `bloom` - the bloom filter
    * `suicides` - suicides (or selfdestructs, the newer more politically correct synonym)
    * `recent_uncles` - recent uncle blocks in the chain
    * `prev_headers` - previous block headers
    * `refunds` - suicide/selfdestruct refund counter

Pyethereum follows a **maximally state-centric model**; the ONLY information needed to process a transaction or a block is located within the state itself, allowing the actual state transition logic to be a very clean `apply_transaction(state, tx)` and `apply_block(state, block)`.

* `get_balance`- gets the balance of an account
* `get_code` - gets the code of an account
* `get_storage_data(addr, k)` - gets the storage at the given key of the given address. Expects a key in **numerical** form (eg. b"cow" or "0x636f77" is represented as 6516599).
* `to_snapshot(root_only=False, no_prevblocks=False)` - creates a snapshot for the current state. If `root_only` is set, only adds the state root, not the entire state. If `no_prevblocks` is set, does not add previous headers and uncles. Setting either of those flags means that the same database would be required to recover from the snapshot.
* `from_snapshot(snapshot, env)` (classmethod) - creates a state from the given snapshot with the given `env`.
* `ephemeral_clone()` - creates a clone of the state that you can work with without affecting the original

There are also many methods that modify the state, eg. `set_code`, `set_storage_data`, but it is generally recommended to avoid using these, and instead modify the state ONLY through `apply_transaction` and `apply_block`.

### ethereum.meta

This file contains two functions:

* `apply_block(state, block)` - takes a state and processes a block onto that state
* `make_head_candidate(chain, txqueue=None, parent=None, timestamp, coinbase, extra_data, min_gasprice=0)` - creates a candidate block for the chain on top of the given parent block (default: head of the chain). Gets transactions from the given `txqueue` object with the given `mingasprice` (otherwise does not add transactions). `timestamp`, `coinbase` and `extra_data` can be used to specify those parameters in the block; otherwise defaults are used

### ethereum.messages

The main function that should be called from here is `apply_transaction(state, tx)`.

### ethereum.utils

Contains a bunch of utility functions, including:

#### Numerical and hex conversions

* `encode_int(i)` - converts an integer into big-endian binary representation
* `zpad(data, length)` - pads the data up to the desired length by adding zero bytes on the left
* `encode_int32(i)` - equivalent to `zpad(encode_int(i), 32)` but faster
* `big_endian_to_int(d)` - converts binary data into an integer
* `encode_hex(b)` - converts bytes to hex
* `decode_hex(h)` - converts hex to bytes
* `int_to_addr(i)` - converts integer to address
* `is_numeric(i)` - returns True if the value is int or long, otherwise False

#### Cryptography

* `sha3(data)` - computes the SHA3 (or more precisely, keccak256) hash
* `ecrecover_to_pub(hash, v, r, s)` - recovers the public key that made the signature as a 64-byte binary blob of `encode_int32(x) + encode_int32(y)`. Hashing this and taking the last 20 bytes gives the _address_ that signed a message.
* `ecsign(hash, key)` - returns the v, r, s values of a signature
* `normalize_key(key)` - converts a key from many formats into 32-byte binary
* `privtoaddr(key)` - converts a key to an address

#### Addresses

* `normalize_address(addr)` - converts an address into 20-byte binary form
* `check_checksum(addr)` - returns True if the address checksum passes, otherwise False
* `checksum_encode(addr)` - converts an address into hex form with a checksum
* `mk_contract_address(addr, nonce)` - creates the address of a contract created by the given address with the given nonce

#### Miscellaneous

* `denoms` - contains the denominations of ether, eg. `denoms.finney = 10**15`, `denoms.shannon = 10**9`, `denoms.gwei = 10**9`

### ethereum.block

Contains the `Block` and `BlockHeader` classes. Generally recommended to avoid creating blocks and block headers directly, instead using `mk_head_candidate`. The member variables are straightforward:

* `block.transactions` - transactions in a block
* `block.uncles` - uncles in a block
* `block.header` - header of a block

And in the header:

* `header.hash` - the hash (also the block hash)
* `header.mining_hash` - the hash used for proof of work mining
* `header.to_dict()` - serializes into a human-readable dict
* `header.prevhash` - previous block hash
* `header.uncles_hash` - hash of the uncle list
* `header.coinbase` - coinbase (miner) address
* `header.state_root` - root hash of the post-state
* `header.tx_list_root` - hash of the transactions in the block
* `header.receipts_root` - hash of the receipt trie
* `header.bloom` - bloom filter
* `header.difficulty` - block difficulty
* `header.number` - block number
* `header.gas_limit` - gas limit
* `header.gas_used` - gas used
* `header.timestamp` - timestamp
* `header.extra_data` - block extra data
* `header.mixhash` and `header.nonce` - Ethash proof of work values

### ethereum.transactions

Contains the Transaction class, with the following methods and values:

* `__init__(nonce, gasprice, startgas, to, value, data, (v, r, s optional))` - constructor
* `sign(key, network_id=None)` - signs the transaction with the given key, and with the given EIP155 chain ID (leaving as None will create a pre-EIP155 tx, be warned of replay attacks if you do this!)
* `sender` - the sender address of the transaction
* `network_id` - the EIP155 chain ID of the transaction
* `hash` - the hash of the transaction
* `to_dict()` - serializes into a human-readable dict
* `intrinsic_gas_used` - the amount of gas consumed by the transaction, including the cost of the tx data
* `creates` - if the transaction creates a contract, returns the contract address
* `nonce`, `gasprice`, `startgas`, `to`, `value`, `data`, `v`, `r`, `s` - parameters in the transaction

### ethereum.tools.keys

Creates encrypted private key storaes

* `decode_keystore_json(jsondata, password)` - returns the private key from an encrypted keystore object. NOTE: if you are loading from a file, the most convenient way to do this is `import json; key = decode_keystore_json(json.load(open('filename.json')), 'password')`
* `make_keystore_json(key, pw, kdf='pbkdf2', cipher='aes-128-ctr')` - creates an encrypted keystore object for the key. Keeping `kdf` and `cipher` at their default values is recommended.

### ethereum.abi

Most compilers for HLLs (solidity, serpent, viper, etc) on top of Ethereum have the option to output an ABI declaration for a program. This is a json object that looks something like this:

    [{"name": "ecrecover(uint256,uint256,uint256,uint256)", "type": "function", "constant": false,
     "inputs": [{"name": "h", "type": "uint256"}, {"name": "v", "type": "uint256"}, {"name": "r", "type": "uint256"}, {"name": "s", "type": "uint256"}],
     "outputs": [{"name": "out", "type": "int256[]"}]},
     {"name": "PubkeyTripleLogEvent(uint256,uint256,uint256)", "type": "event",
     "inputs": [{"name": "x", "type": "uint256", "indexed": false}, {"name": "y", "type": "uint256", "indexed": false}, {"name": "z", "type": "uint256", "indexed": false}]}]

You can initialize an `abi.ContractTranslator` object to encode and decode data for contracts as follows:

    true, false = True, False
    ct = abi.ContractTranslator(<json here>)
    txdata = ct.encode('function_name', [arg1, arg2, arg3])

You can also call `ct.decode_event([topic1, topic2...], logdata)` to decode a log.

### RLP encoding and decoding

For any transaction or block, you can simply do:

    import rlp
    bindata = rlp.encode(<tx or block>)

To decode:

    import rlp
    from ethereum.transactions import Transaction
    rlp.decode(blob, Transaction)

Or:

    import rlp
    from ethereum.blocks import Block
    rlp.decode(blob, Block)

### Consensus abstraction

The pyethereum codebase is designed to be maximally friendly for use across many different consensus algorithms. If you want to add a new consensus algo, you'll need to take the following steps:

* Add a directory alongside `pow`, and in it create a `chain.py` class that implements a `Chain` module. This may have a totally different fork choice rule for proof of work (GHOST, signature counting, Casper, etc).
* Add an entry to `consensus_strategy.py`. You will need to implement:
    * `check_seal` - check that a block is correctly "sealed" (mined, signed, etc)
    * `validate_uncles(state, block)` - check that uncles are valid
    * `initialize(state, block)` - called in `apply_block` before transactions are processed
    * `finalize(state, block)` - called in `apply_block` after transactions are processed
    * `get_uncle_candidates(chain, state)` - called in `mk_head_candidate` to include uncles in a block
* Create a chain config with the `CONSENSUS_STRATEGY` set to whatever you named your new consensus strategy

## Tester module

See https://github.com/ethereum/pyethereum/wiki/Using-pyethereum.tester

## Tests

Run `python3.6 -m pytest ethereum/tests/<filename>` for any .py file in that directory. Currently all tests are passing except for a few Metropolis-specific state tests and block tests.

To make your own state tests, use the tester module as follows:

```python
from ethereum.tools import tester as t
import json
c = t.Chain()
x = c.contract(<code>, language=<language>)
pre = t.mk_state_test_prefill(c)
x.foo(<args>)
post = t.mk_state_test_postfill(c, pre)
open('output.json', 'w').write(json.dumps(post, indent=4))
```

To make a test filler file instead, do `post = t.mk_state_test_postfill(c, pre, True)`.

## Licence

See LICENCE
