# -*- coding: utf8 -*-
import shutil
import tempfile
import time
import types
import warnings

import rlp
from rlp.utils import ascii_chr

from ethereum import blocks, db, opcodes, transactions, processblock
from ethereum.abi import ContractTranslator
from ethereum.config import Env
from ethereum.slogging import LogRecorder
from ethereum._solidity import get_solidity
from ethereum.utils import to_string, sha3, privtoaddr, int_to_addr
from ethereum.trace import Trace

TRACE_LVL_MAP = [
    ':info',
    'eth.vm.log:trace',
    ':info,eth.vm.log:trace,eth.vm.exit:trace',
    ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace',
    ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,' +
    'eth.vm.storage:trace,eth.vm.memory:trace'
]

GAS_LIMIT = 4712388
GAS_PRICE = 20000000000

# pylint: disable=invalid-name

gas_limit = GAS_LIMIT
gas_price = GAS_PRICE

accounts = [
        u"6e5fd1741e45c966a76a077af9132627c07b0dc1".decode('hex'),
        u"ef057953c56855f16e658bf8fd0d2e300961fc1f".decode('hex'),
        u"2c284ef5a0d50dda177bd8c9fdf20610f6fdac09".decode('hex'),
        u"bd3c601b59f46cc59be3446ba29c66b9182a70b6".decode('hex'),
        u"e6e6033428cfc58af1585c26a823916c8120ca73".decode('hex'),
        u"e2c628c146a9d40c9ed4c5c3e29cd0a609f7c6f1".decode('hex'),
        u"3e2ff0583a5dec1bd3ac0f7b8d26fa96b759fe92".decode('hex'),
        u"2827a89f78d70c422452528634cfe522b5c668c6".decode('hex'),
        u"f56ae85523c6f4773954fe0b25ba1f52e1183689".decode('hex'),
        u"7703aCa0f4ee937C3073ec80c7608B6f7cE2426B".decode('hex'),
        u"153ee6aD2e7e665b8a07ff37d93271d6E5FDc6d4".decode('hex')
]
keys = [
        u"0af37c53fdc5b97bf1f84d30e84f09c84f733e467a3b26c1ce6c5d448f9d7cec".decode('hex'),
        u"0d5c1bd818a4086f28314415cb375a937593efab66f8f7d2903bf2a13ed35070".decode('hex'),
        u"17029bda254fdf118125741e80d2d43e8ac1ffa8cca20c51683bc0735c802e5b".decode('hex'),
        u"8d2fd08f91550712ec0db96bdbb849ec88a560e200c58f05954827b2593cf9e7".decode('hex'),
        u"803ae2f3b0030390092910e0f1e8ec15dbc975d6422ab2274b175c74eed589fb".decode('hex'),
        u"0c71a0e6e4bf22677a5750c123aaf988270e1c4025f80d82b7a18f2efe295cbf".decode('hex'),
        u"9ca1d29731e6302e3e7d7f0ebaf2b4fa48d7b7fd4f5c82f59b3983b0a2160d7e".decode('hex'),
        u"e2631c2443b12abdfc5e70e3b7643f2d340eb49c6102c66835d0c7286903b009".decode('hex'),
        u"f7a590340d042a107ec3c9e82f81d2301ecc5b79f959f7a09d3c7fb7ab7f1024".decode('hex'),
        u"9e256901c752616c231904281333e5dd11fa48fdfd7ffac3515923b1fe60a28e".decode('hex'),
        u"b10ec925fccdaf155fa0b56bd55cf6ce3cc8927b304c0a563476529d925755d5".decode('hex')
]

languages = {}

#for account_number in range(10):
#    keys.append(sha3(to_string(account_number)))
#    accounts.append(privtoaddr(keys[-1]))

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
                raise TransactionFailed(transaction.hash.ecnode('hex'))

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
