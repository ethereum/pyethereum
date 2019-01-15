from ethereum.utils import sha3, privtoaddr, int_to_addr, to_string, big_endian_to_int, checksum_encode, int_to_big_endian, encode_hex, normalize_address
from ethereum.genesis_helpers import mk_basic_state
from ethereum.transactions import Transaction
from ethereum.consensus_strategy import get_consensus_strategy
from ethereum.config import config_homestead, config_tangerine, config_spurious, config_metropolis, default_config, Env
from ethereum.pow.ethpow import Miner
from ethereum.messages import apply_transaction, apply_message
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
    base_alloc[a] = {'balance': 10**24}
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
except (ImportError, TypeError):
    pass

try:
    from vyper import compiler
    languages['vyper'] = compiler
except (ImportError, TypeError):
    pass


class TransactionFailed(Exception):
    pass


from ethereum.abi import ContractTranslator
import types

STARTGAS = 3141592
GASPRICE = 0

from ethereum.slogging import configure_logging
config_string = ':info'
# configure_logging(config_string=config_string)


class ABIContract(object):  # pylint: disable=too-few-public-methods

    def __init__(self, _tester, _abi, address):
        self.address = address

        if isinstance(_abi, ContractTranslator):
            abi_translator = _abi
        else:
            abi_translator = ContractTranslator(_abi)

        self.translator = abi_translator

        for function_name in self.translator.function_data:
            if self.translator.function_data[function_name]['is_constant']:
                function = self.method_factory(_tester.call, function_name)
            else:
                function = self.method_factory(_tester.tx, function_name)
            method = types.MethodType(function, self)
            setattr(self, function_name, method)

    @staticmethod
    def method_factory(tx_or_call, function_name):
        """ Return a proxy for calling a contract method with automatic encoding of
        argument and decoding of results.
        """

        def kall(self, *args, **kwargs):
            key = kwargs.get('sender', k0)

            result = tx_or_call(  # pylint: disable=protected-access
                sender=key,
                to=self.address,
                value=kwargs.get('value', 0),
                data=self.translator.encode(function_name, args),
                startgas=kwargs.get('startgas', STARTGAS),
                gasprice=kwargs.get('gasprice', GASPRICE)
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
        None: config_metropolis,
        'mainnet': default_config,
        'homestead': config_homestead,
        'tangerine': config_tangerine,
        'spurious': config_spurious,
        'metropolis': config_metropolis,
    }
    return env if isinstance(env, Env) else Env(config=d[env])


class State(object):
    def __init__(self, genesis):
        self.state = genesis

    def tx(self, sender=k0, to=b'\x00' * 20, value=0,
           data=b'', startgas=STARTGAS, gasprice=GASPRICE):
        sender_addr = privtoaddr(sender)
        transaction = Transaction(self.state.get_nonce(sender_addr), gasprice, startgas,
                                  to, value, data).sign(sender)
        success, output = apply_transaction(self.state, transaction)
        if not success:
            raise TransactionFailed()
        return output

    def call(self, sender=k0, to=b'\x00' * 20, value=0,
             data=b'', startgas=STARTGAS, gasprice=GASPRICE):
        self.state.commit()
        sender_addr = privtoaddr(sender)
        result = apply_message(
            self.state.ephemeral_clone(),
            sender=sender_addr,
            to=to,
            code_address=to,
            value=value,
            data=data,
            gas=startgas)
        if result is None:
            raise TransactionFailed()
        return result


class Chain(object):
    def __init__(self, alloc=base_alloc, env=None, genesis=None):
        from ethereum.pow import chain as pow_chain
        if genesis:
            if type(genesis)!=dict and genesis.env.config['CONSENSUS_STRATEGY'] == 'hybrid_casper':
                from ethereum.hybrid_casper import chain as hybrid_casper_chain
                self.chain = hybrid_casper_chain.Chain(genesis, reset_genesis=True)
            else:
                self.chain = pow_chain.Chain(genesis, env=env, reset_genesis=True)
        else:
            self.chain = pow_chain.Chain(mk_basic_state(alloc, None, get_env(env)), reset_genesis=True)
        self.cs = get_consensus_strategy(self.chain.env.config)
        self.block = mk_block_from_prevstate(
            self.chain, timestamp=self.chain.state.timestamp + 1)
        self.head_state = self.chain.state.ephemeral_clone()
        self.cs.initialize(self.head_state, self.block)
        self.last_sender = None
        self.last_tx = None

    def direct_tx(self, transaction):
        self.last_tx = transaction
        if self.last_sender is not None and privtoaddr(
                self.last_sender) != transaction.sender:
            self.last_sender = None
        success, output = apply_transaction(self.head_state, transaction)
        self.block = self.block.copy(
            transactions=self.block.transactions + (transaction,)
        )
        if not success:
            raise TransactionFailed()
        return output

    def tx(self, sender=k0, to=b'\x00' * 20, value=0,
           data=b'', startgas=STARTGAS, gasprice=GASPRICE):
        sender_addr = privtoaddr(sender)
        self.last_sender = sender
        transaction = Transaction(self.head_state.get_nonce(sender_addr), gasprice, startgas,
                                  to, value, data).sign(sender)
        output = self.direct_tx(transaction)
        return output

    def call(self, sender=k0, to=b'\x00' * 20, value=0,
             data=b'', startgas=STARTGAS, gasprice=GASPRICE):
        self.head_state.commit()
        to = normalize_address(to)
        sender_addr = privtoaddr(sender)
        result = apply_message(
            self.head_state.ephemeral_clone(),
            sender=sender_addr,
            to=to,
            code_address=to,
            value=value,
            data=data,
            gas=startgas)
        if result is None:
            raise TransactionFailed()
        return result

    def last_gas_used(self, with_tx=False):
        if len(self.head_state.receipts) == 1:
            diff = self.head_state.receipts[-1].gas_used
        else:
            diff = self.head_state.receipts[-1].gas_used - \
                self.head_state.receipts[-2].gas_used
        return diff - (not with_tx) * self.last_tx.intrinsic_gas_used

    def contract(self, sourcecode, args=[], sender=k0, value=0, libraries=None,
                 language=None, l=None, startgas=STARTGAS, gasprice=GASPRICE):
        assert not (l and language)
        language = l or language
        if language == 'evm':
            assert len(args) == 0
            return self.tx(sender=sender, to=b'', value=value,
                           data=sourcecode, startgas=startgas, gasprice=gasprice)
        else:
            compiler = languages[language]
            interface = compiler.mk_full_signature(sourcecode)
            ct = ContractTranslator(interface)
            code = compiler.compile(
                sourcecode, libraries=libraries
            ) + (ct.encode_constructor_arguments(args) if args else b'')
            addr = self.tx(
                sender=sender,
                to=b'',
                value=value,
                data=code,
                startgas=startgas,
                gasprice=gasprice)
            return ABIContract(self, ct, addr)

    def mine(self, number_of_blocks=1, timestamp=14, coinbase=a0):
        self.cs.finalize(self.head_state, self.block)
        self.block = set_execution_results(self.head_state, self.block)
        bin_nonce, mixhash = Miner(self.block).mine(rounds=100, start_nonce=0)
        self.block = self.block.copy(header=self.block.header.copy(
            nonce=bin_nonce,
            mixhash=mixhash
        ))
        assert self.chain.add_block(self.block)
        b = self.block
        for i in range(1, number_of_blocks):
            b, _ = make_head_candidate(
                self.chain, parent=b, timestamp=self.chain.state.timestamp + timestamp, coinbase=coinbase)
            min_nonce, mixhash = Miner(b).mine(rounds=100, start_nonce=0)
            b = b.copy(header=b.header.copy(
                nonce=bin_nonce,
                mixhash=mixhash
            ))
            assert self.chain.add_block(b)
        self.change_head(b.header.hash, coinbase)
        return b

    def change_head(self, parent, coinbase=a0):
        self.head_state = self.chain.mk_poststate_of_blockhash(
            parent).ephemeral_clone()
        self.block = mk_block_from_prevstate(
            self.chain,
            self.head_state,
            timestamp=self.chain.state.timestamp,
            coinbase=coinbase)
        self.cs.initialize(self.head_state, self.block)

    def snapshot(self):
        self.head_state.commit()
        return self.head_state.snapshot(), len(
            self.block.transactions), self.block.number

    def revert(self, snapshot):
        state_snapshot, txcount, blknum = snapshot
        assert blknum == self.block.number, "Cannot revert beyond block boundaries!"
        self.block = self.block.copy(
            transactions=self.block.transactions[:txcount]
        )
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
        "previousHash": "0x" + encode_hex(c.head_state.prev_headers[0].hash),
    }
    pre = c.head_state.to_dict()
    return {"env": env, "pre": pre}


def mk_state_test_postfill(c, prefill, filler_mode=False):
    txdata = c.last_tx.to_dict()
    modified_tx_data = {
        "data": [txdata["data"]],
        "gasLimit": [int_to_0x_hex(txdata["startgas"])],
        "gasPrice": int_to_0x_hex(txdata["gasprice"]),
        "nonce": int_to_0x_hex(txdata["nonce"]),
        "secretKey": '0x' + encode_hex(c.last_sender),
        "to": txdata["to"],
        "value": [int_to_0x_hex(txdata["value"])],
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
        o["post"] = {config: [{"hash": postStateHash,
                               "indexes": {"data": 0, "gas": 0, "value": 0}}]}
    else:
        o["expect"] = [{"indexes": {"data": 0, "gas": 0, "value": 0}, "network": [
            "Metropolis"], "result": c.head_state.to_dict()}]
    return o
