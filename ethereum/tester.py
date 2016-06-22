# -*- coding: utf8 -*-
import shutil
import tempfile
import time
import types
import warnings

import rlp
from rlp.utils import ascii_chr

from ethereum import blocks, db, opcodes, processblock, transactions
from ethereum.abi import ContractTranslator
from ethereum.config import Env
from ethereum.slogging import LogRecorder
from ethereum._solidity import get_solidity
from ethereum.utils import to_string, sha3, privtoaddr, int_to_addr

TRACE_LVL_MAP = [
    ':info',
    'eth.vm.log:trace',
    ':info,eth.vm.log:trace,eth.vm.exit:trace',
    ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace',
    ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,' +
    'eth.vm.storage:trace,eth.vm.memory:trace'
]

GAS_LIMIT = 3141592
GAS_PRICE = 1

# pylint: disable=invalid-name

gas_limit = GAS_LIMIT
gas_price = GAS_PRICE

accounts = []
keys = []
languages = {}

for account_number in range(10):
    keys.append(sha3(to_string(account_number)))
    accounts.append(privtoaddr(keys[-1]))

k0, k1, k2, k3, k4, k5, k6, k7, k8, k9 = keys[:10]
a0, a1, a2, a3, a4, a5, a6, a7, a8, a9 = accounts[:10]

try:
    import serpent  # pylint: disable=wrong-import-position
    languages['serpent'] = serpent
except ImportError:
    pass

_solidity = get_solidity()
if _solidity:
    languages['solidity'] = _solidity

DEFAULT_KEY = k0
DEFAULT_ACCOUNT = a0


def dict_without(base_dict, *args):
    """ Return a copy of the dictionary without the `keys`. """
    without_keys = dict(base_dict)

    for key in args:
        without_keys.pop(key, None)

    return without_keys


def dict_with(base_dict, **kwargs):
    """ Return a copy of the dictionary with the added elements. """
    full_dict = dict(base_dict)
    full_dict.update(**kwargs)

    return full_dict


def rand():
    """ Return a pseudo random number.

    Pseudo-RNG (deterministic for now for testing purposes).
    """
    rand.seed = pow(rand.seed, 2, 2 ** 512)
    return rand.seed % 2 ** 256


# initialize the rand function
rand.seed = 3 ** 160


class TransactionFailed(Exception):
    pass


class ContractCreationFailed(Exception):
    pass


class ABIContract(object):  # pylint: disable=too-few-public-methods

    def __init__(self, _state, _abi, address, listen=True,  # pylint: disable=too-many-arguments
                 log_listener=None, default_key=None):
        self.address = address
        self.default_key = default_key or DEFAULT_KEY

        if isinstance(_abi, ContractTranslator):
            abi_translator = _abi
        else:
            abi_translator = ContractTranslator(_abi)

        self.translator = abi_translator

        def listener(log):
            result = self.translator.listen(log, noprint=False)

            if result and log_listener:
                log_listener(result)

        if listen:
            _state.block.log_listeners.append(listener)

        for function_name in self.translator.function_data:
            function = self.method_factory(_state, function_name)
            method = types.MethodType(function, self)
            setattr(self, function_name, method)

    @staticmethod
    def method_factory(test_state, function_name):
        """ Return a proxy for calling a contract method with automatic encoding of
        argument and decoding of results.
        """

        def kall(self, *args, **kwargs):
            key = kwargs.get('sender', self.default_key)

            result = test_state._send(  # pylint: disable=protected-access
                key,
                self.address,
                kwargs.get('value', 0),
                self.translator.encode(function_name, args),
                **dict_without(kwargs, 'sender', 'value', 'output')
            )

            if kwargs.get('output', '') == 'raw':
                outdata = result['output']
            elif not result['output']:
                outdata = None
            else:
                outdata = self.translator.decode(function_name, result['output'])
                outdata = outdata[0] if len(outdata) == 1 else outdata

            if kwargs.get('profiling', ''):
                return dict_with(result, output=outdata)

            return outdata
        return kall


class state(object):

    def __init__(self, num_accounts=len(keys)):
        self.temp_data_dir = tempfile.mkdtemp()
        self.db = db.EphemDB()
        self.env = Env(self.db)
        self.last_tx = None

        initial_balances = {}

        for i in range(num_accounts):
            account = accounts[i]
            initial_balances[account] = {'wei': 10 ** 24}

        for i in range(1, 5):
            address = int_to_addr(i)
            initial_balances[address] = {'wei': 1}

        self.block = blocks.genesis(
            self.env,
            start_alloc=initial_balances,
        )
        self.blocks = [self.block]
        self.block.timestamp = 1410973349
        self.block.coinbase = DEFAULT_ACCOUNT
        self.block.gas_limit = 10 ** 9

    def __del__(self):
        shutil.rmtree(self.temp_data_dir)

    def contract(self, sourcecode, sender=DEFAULT_KEY, endowment=0,  # pylint: disable=too-many-arguments
                 language='serpent', libraries=None, path=None,
                 constructor_call=None, **kwargs):
        if language not in languages:
            languages[language] = __import__(language)

        compiler = languages[language]
        bytecode = compiler.compile(sourcecode, path=path, libraries=libraries, **kwargs)

        if constructor_call is not None:
            bytecode += constructor_call

        address = self.evm(bytecode, sender, endowment)

        if len(self.block.get_code(address)) == 0:
            raise Exception('Contract code empty')

        return address

    def abi_contract(self, sourcecode, sender=DEFAULT_KEY, endowment=0,  # pylint: disable=too-many-arguments
                     language='serpent', log_listener=None, listen=True,
                     libraries=None, path=None, constructor_parameters=None,
                     **kwargs):
        # pylint: disable=too-many-locals

        compiler = languages[language]
        contract_interface = compiler.mk_full_signature(sourcecode, path=path, **kwargs)
        translator = ContractTranslator(contract_interface)

        encoded_parameters = None
        if constructor_parameters is not None:
            encoded_parameters = translator.encode_constructor_arguments(constructor_parameters)

        address = self.contract(
            sourcecode,
            sender,
            endowment,
            language,
            libraries,
            path,
            constructor_call=encoded_parameters,
            **kwargs
        )

        return ABIContract(
            self,
            translator,
            address,
            listen=listen,
            log_listener=log_listener,
        )

    def clear_listeners(self):
        while len(self.block.log_listeners):
            self.block.log_listeners.pop()

    def evm(self, code, sender=DEFAULT_KEY, endowment=0, gas=None):
        sendnonce = self.block.get_nonce(privtoaddr(sender))

        transaction = transactions.contract(sendnonce, gas_price, gas_limit, endowment, code)
        transaction.sign(sender)

        if gas is not None:
            transaction.startgas = gas

        (success, output) = processblock.apply_transaction(self.block, transaction)

        if not success:
            raise ContractCreationFailed()

        return output

    def call(*args, **kwargs):  # pylint: disable=unused-argument,no-method-argument
        raise Exception(
            'Call deprecated. Please use the abi_contract mechanism or '
            'send(sender, to, value, data) directly, using the abi module to '
            'generate data if needed.'
        )

    def _send(self, sender, to, value, evmdata='', funid=None, abi=None,  # pylint: disable=too-many-arguments
              profiling=0):
        # pylint: disable=too-many-locals

        if funid is not None or abi is not None:
            raise Exception(
                'Send with funid+abi is deprecated. Please use the abi_contract mechanism'
            )

        start_time = time.time()
        gas_used = self.block.gas_used

        sendnonce = self.block.get_nonce(privtoaddr(sender))
        transaction = transactions.Transaction(sendnonce, gas_price, gas_limit, to, value, evmdata)
        self.last_tx = transaction
        transaction.sign(sender)
        recorder = None

        if profiling > 1:
            recorder = LogRecorder(
                disable_other_handlers=True,
                log_config=TRACE_LVL_MAP[3],
            )

        try:
            (success, output) = processblock.apply_transaction(self.block, transaction)

            if not success:
                raise TransactionFailed()

            out = {
                'output': output,
            }

            if profiling > 0:
                zero_bytes_count = transaction.data.count(ascii_chr(0))
                non_zero_bytes_count = len(transaction.data) - zero_bytes_count

                zero_bytes_cost = opcodes.GTXDATAZERO * zero_bytes_count
                nonzero_bytes_cost = opcodes.GTXDATANONZERO * non_zero_bytes_count

                base_gas_cost = opcodes.GTXCOST
                intrinsic_gas_used = base_gas_cost + zero_bytes_cost + nonzero_bytes_cost

                out['time'] = time.time() - start_time
                out['gas'] = self.block.gas_used - gas_used - intrinsic_gas_used

            if profiling > 1:
                trace = recorder.pop_records()
                vm_operations = [
                    event['op']
                    for event in trace
                    if event['event'] == 'vm'
                ]
                opdict = {}
                for operation in vm_operations:
                    opdict[operation] = opdict.get(operation, 0) + 1
                out['ops'] = opdict

            return out
        finally:
            # ensure LogRecorder has been disabled
            if recorder:
                recorder.pop_records()

    def profile(self, *args, **kwargs):
        kwargs['profiling'] = True
        return self._send(*args, **kwargs)

    def send(self, *args, **kwargs):
        return self._send(*args, **kwargs)["output"]

    def mkspv(self, sender, to, value, data=None, funid=None, abi=None):  # pylint: disable=too-many-arguments
        # TODO: rewrite the method without using encode_abi/encode_datalist
        # since both function were removed.
        raise NotImplementedError()

        # if not HAS_SERPENT:
        #     raise RuntimeError('ethereum-serpent package not installed')
        # data = data or list()
        # sendnonce = self.block.get_nonce(privtoaddr(sender))
        # if funid is not None:
        #     evmdata = serpent.encode_abi(funid, *abi)
        # else:
        #     evmdata = serpent.encode_datalist(*data)
        # transaction = transactions.Transaction(sendnonce, gas_price, gas_limit,
        #                                        to, value, evmdata)
        # self.last_tx = transaction
        # transaction.sign(sender)
        # return spv.mk_transaction_spv_proof(self.block, transaction)

    def verifyspv(self, sender, to, value, data=None, funid=None, abi=None, proof=None):  # pylint: disable=too-many-arguments
        # TODO: rewrite the method without using encode_abi/encode_datalist
        # since both function were removed.
        raise NotImplementedError()

        # if not HAS_SERPENT:
        #     raise RuntimeError('ethereum-serpent package not installed')
        # data = data or list()
        # proof = proof or list()
        # sendnonce = self.block.get_nonce(privtoaddr(sender))
        # if funid is not None:
        #     evmdata = serpent.encode_abi(funid, *abi)
        # else:
        #     evmdata = serpent.encode_datalist(*data)
        # transaction = transactions.Transaction(sendnonce, gas_price,
        #                                        gas_limit, to, value, evmdata)
        # self.last_tx = transaction
        # transaction.sign(sender)
        # return spv.verify_transaction_spv_proof(self.block, transaction, proof)

    def trace(self, sender, to, value, data=None):
        # collect log events (independent of loglevel filters)
        data = data or list()
        recorder = LogRecorder()
        self.send(sender, to, value, data)
        return recorder.pop_records()

    def mine(self, number_of_blocks=1, coinbase=DEFAULT_ACCOUNT, **kwargs):
        if 'n' in kwargs:  # compatibility
            number_of_blocks = kwargs['n']
            warnings.warn(
                "The argument 'n' is deprecated and its support will be removed "
                "in the future versions. Please use the name 'number_of_blocks'."
            )

        for _ in range(number_of_blocks):
            self.block.finalize()
            self.block.commit_state()
            self.db.put(self.block.hash, rlp.encode(self.block))
            timestamp = self.block.timestamp + 6 + rand() % 12

            block = blocks.Block.init_from_parent(
                self.block,
                coinbase,
                timestamp=timestamp,
            )

            self.block = block
            self.blocks.append(self.block)

    def snapshot(self):
        return rlp.encode(self.block)

    def revert(self, data):
        self.block = rlp.decode(data, blocks.Block, env=self.env)
        # pylint: disable=protected-access
        self.block._mutable = True
        self.block.header._mutable = True
        self.block._cached_rlp = None
        self.block.header._cached_rlp = None
