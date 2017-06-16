from ethereum.utils import sha3, privtoaddr, int_to_addr, to_string, big_endian_to_int, checksum_encode, int_to_big_endian, encode_hex
from ethereum.genesis_helpers import mk_basic_state
from ethereum.pow import chain
from ethereum.transactions import Transaction
from ethereum.consensus_strategy import get_consensus_strategy
from ethereum.config import config_homestead, config_tangerine, config_spurious, config_metropolis, default_config, Env
from ethereum.pow.ethpow import Miner
from ethereum.messages import apply_transaction
from ethereum.common import verify_execution_results, mk_block_from_prevstate, set_execution_results
from ethereum.meta import make_head_candidate
from ethereum.abi import ContractTranslator
import rlp
# Initialize accounts
accounts = []
keys = []

for account_number in range(10):
    keys.append(sha3(to_string(account_number)))
    accounts.append(privtoaddr(keys[-1]))

k0, k1, k2, k3, k4, k5, k6, k7, k8, k9 = keys[:10]
a0, a1, a2, a3, a4, a5, a6, a7, a8, a9 = accounts[:10]

base_alloc = {}
minimal_alloc = {}
for a in accounts:
    base_alloc[a] = {'balance': 10**18}
for i in range(1, 9):
    base_alloc[int_to_addr(i)] = {'balance': 1}
    minimal_alloc[int_to_addr(i)] = {'balance': 1}
minimal_alloc[accounts[0]] = {'balance': 10**18}

# Initialize languages
languages = {}

try:
    import serpent
    languages['serpent'] = serpent
except ImportError:
    pass

from ethereum.tools._solidity import get_solidity
_solidity = get_solidity()
if _solidity:
    languages['solidity'] = _solidity

try:
    from viper import compiler
    languages['viper'] = compiler
except ImportError:
    pass

class TransactionFailed(Exception):
    pass

from ethereum.abi import ContractTranslator
import types

STARTGAS = 3141592
GASPRICE = 1

from ethereum.slogging import configure_logging
config_string = ':info'
# configure_logging(config_string=config_string)

class ABIContract(object):  # pylint: disable=too-few-public-methods

    def __init__(self, _chain, _abi, address):
        self.address = address

        if isinstance(_abi, ContractTranslator):
            abi_translator = _abi
        else:
            abi_translator = ContractTranslator(_abi)

        self.translator = abi_translator

        for function_name in self.translator.function_data:
            function = self.method_factory(_chain, function_name)
            method = types.MethodType(function, self)
            setattr(self, function_name, method)

    @staticmethod
    def method_factory(test_chain, function_name):
        """ Return a proxy for calling a contract method with automatic encoding of
        argument and decoding of results.
        """

        def kall(self, *args, **kwargs):
            key = kwargs.get('sender', k0)

            result = test_chain.tx(  # pylint: disable=protected-access
                sender=key,
                to=self.address,
                value=kwargs.get('value', 0),
                data=self.translator.encode(function_name, args),
                startgas=kwargs.get('startgas', STARTGAS)
            )

            if result is False:
                return result
            if result == b'':
                return None
            o = self.translator.decode(function_name, result)
            return o[0] if len(o) == 1 else o
        return kall

def get_env(env):
    d = {
        None: config_spurious,
        'mainnet': default_config,
        'homestead': config_homestead,
        'tangerine': config_tangerine,
        'spurious': config_spurious,
        'metropolis': config_metropolis,
    }
    return env if isinstance(env, Env) else Env(config=d[env])


class Chain(object):
    def __init__(self, alloc=None, env=None):
        self.chain = chain.Chain(
            genesis=mk_basic_state(base_alloc if alloc is None else alloc,
                                   None,
                                   get_env(env)),
            reset_genesis=True
        )
        self.cs = get_consensus_strategy(self.chain.env.config)
        self.block = mk_block_from_prevstate(self.chain, timestamp=self.chain.state.timestamp + 1)
        self.head_state = self.chain.state.ephemeral_clone()
        self.cs.initialize(self.head_state, self.block)
        self.last_sender = None
        self.last_tx = None

    def direct_tx(self, transaction):
        self.last_tx, self.last_sender = transaction, None
        success, output = apply_transaction(self.head_state, transaction)
        self.block.transactions.append(transaction)
        if not success:
            raise TransactionFailed()
        return output

    def tx(self, sender=k0, to=b'\x00' * 20, value=0, data=b'', startgas=STARTGAS, gasprice=GASPRICE):
        sender_addr = privtoaddr(sender)
        transaction = Transaction(self.head_state.get_nonce(sender_addr), gasprice, startgas,
                                  to, value, data).sign(sender)
        o = self.direct_tx(transaction)
        self.last_sender = sender
        return o

    def contract(self, sourcecode, args=[], sender=k0, value=0, language='evm', startgas=STARTGAS, gasprice=GASPRICE):
        if language == 'evm':
            assert len(args) == 0
            return self.tx(sender=sender, to=b'', value=value, data=sourcecode, startgas=startgas, gasprice=gasprice)
        else:
            compiler = languages[language]
            interface = compiler.mk_full_signature(sourcecode)
            ct = ContractTranslator(interface)
            code = compiler.compile(sourcecode) + (ct.encode_constructor_arguments(args) if args else b'')
            addr = self.tx(sender=sender, to=b'', value=value, data=code, startgas=startgas, gasprice=gasprice)
            return ABIContract(self, ct, addr)

    def mine(self, number_of_blocks=1, coinbase=a0):
        self.cs.finalize(self.head_state, self.block)
        set_execution_results(self.head_state, self.block)
        self.block = Miner(self.block).mine(rounds=100, start_nonce=0)
        assert self.chain.add_block(self.block)
        assert self.head_state.trie.root_hash == self.chain.state.trie.root_hash
        for i in range(1, number_of_blocks):
            b, _ = make_head_candidate(self.chain, timestamp=self.chain.state.timestamp + 14)
            b = Miner(b).mine(rounds=100, start_nonce=0)
            assert self.chain.add_block(b)
        self.block = mk_block_from_prevstate(self.chain, timestamp=self.chain.state.timestamp + 14)
        self.head_state = self.chain.state.ephemeral_clone()
        self.cs.initialize(self.head_state, self.block)

    def snapshot(self):
        self.head_state.commit()
        return self.head_state.snapshot(), len(self.block.transactions), self.block.number

    def revert(self, snapshot):
        state_snapshot, txcount, blknum = snapshot
        assert blknum == self.block.number
        self.block.transactions = self.block.transactions[:txcount]
        self.head_state.revert(state_snapshot)

def int_to_0x_hex(v):
    o = encode_hex(int_to_big_endian(v))
    if o and o[0] == '0':
        return '0x' + o[1:]
    else:
        return '0x' + o
    

def mk_state_test_prefill(c):
    env = {
        "currentCoinbase": checksum_encode(c.head_state.block_coinbase),
        "currentDifficulty": int_to_0x_hex(c.head_state.block_difficulty),
        "currentGasLimit": int_to_0x_hex(c.head_state.gas_limit),
        "currentNumber": int_to_0x_hex(c.head_state.block_number),
        "currentTimestamp": int_to_0x_hex(c.head_state.timestamp),
        "previousHash": "0x"+encode_hex(c.head_state.prev_headers[0].hash),
    }
    pre = c.head_state.to_dict()
    return {"env": env, "pre": pre}

def mk_state_test_postfill(c, prefill, filler_mode=False):
    txdata = c.last_tx.to_dict()
    modified_tx_data = {
        "data": [ txdata["data"] ],
        "gasLimit": [ int_to_0x_hex(txdata["startgas"]) ],
        "gasPrice": int_to_0x_hex(txdata["gasprice"]),
        "nonce": int_to_0x_hex(txdata["nonce"]),
        "secretKey": '0x' + encode_hex(c.last_sender),
        "to": txdata["to"],
        "value": [ int_to_0x_hex(txdata["value"]) ],
    }
    c.head_state.commit()
    postStateHash = '0x' + encode_hex(c.head_state.trie.root_hash)
    if c.chain.config == config_homestead:
        config = 'Homestead'
    elif c.chain.config == config_tangerine:
        config = 'EIP150'
    elif c.chain.config == config_spurious:
        config = 'EIP158'
    elif c.chain.config == config_metropolis:
        config = 'Metropolis'
    else:
        raise Exception("Cannot get config")
    o = {
        "env": prefill["env"],
        "pre": prefill["pre"],
        "transaction": modified_tx_data,
    }
    if not filler_mode:
        o["post"] = {config: [ { "hash": postStateHash, "indexes": {"data": 0, "gas": 0, "value": 0} } ] }
    else:
        o["expect"] = [ {"indexes": {"data": 0, "gas": 0, "value": 0}, "network": ["Metropolis"], "result": c.head_state.to_dict() } ]
    return o
