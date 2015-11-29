from serenity_blocks import State, tx_state_transition, mk_contract_address
from serenity_transactions import Transaction
import db
import serpent
from config import BLOCKHASHES, STATEROOTS, BLKNUMBER, CASPER, GAS_CONSUMED, GASLIMIT, NULL_SENDER, ETHER, ECRECOVERACCT
from utils import privtoaddr, normalize_address, zpad, encode_int, big_endian_to_int, encode_int32
import ecdsa_accounts
import abi
import sys

genesis = State('', db.EphemDB())
gc = genesis.clone()
# Create and get the casper contract code
code = serpent.compile('casper.se.py')
tx_state_transition(gc, Transaction(None, 1000000, '', code), 0)
genesis.set_storage(CASPER, '', gc.get_storage(mk_contract_address(code=code), ''))
# Get the code for the basic ecrecover account
# Note that the code outputted by serpent is code that returns the desired code, so
# it is the correct thing to place in this slot
genesis.set_storage(ECRECOVERACCT, '', ecdsa_accounts.constructor_code)

ct = abi.ContractTranslator(serpent.mk_full_signature('casper.se.py'))
    
# Call a method of a function with no effect
def call_method(state, addr, ct, fun, args):
    tx = Transaction(addr, 1000000, ct.encode(fun, args))
    o = tx_state_transition(state.clone(), tx, 0)
    print 'baa', o, len(o)
    return ct.decode(fun, ''.join(map(chr, tx_state_transition(state.clone(), tx, 0))))
    
from ethereum.slogging import LogRecorder, configure_logging, set_level
config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace'
# configure_logging(config_string=config_string)

keys = [zpad(encode_int(x), 32) for x in range(1, 13)][:3]
for i, k in enumerate(keys):
    a = ecdsa_accounts.privtoaddr(k)
    genesis.set_storage(ETHER, a, 1600 * 10**18)
    vcode = ecdsa_accounts.mk_validation_code(a)
    print 'Length of validation code:', len(vcode)
    txdata = ct.encode('join', [vcode])
    tx = ecdsa_accounts.mk_transaction(0, 1, 1000000, CASPER, 0, '', k, create=True)
    v = tx_state_transition(genesis, tx, i * 2 + 1)
    print 'seq', big_endian_to_int(genesis.get_storage(a, 2**256 - 1))
    print 'Length of account code:', len(genesis.get_storage(mk_contract_address(code=ecdsa_accounts.mk_code(a)), ''))
    tx = ecdsa_accounts.mk_transaction(1, 1, 1000000, CASPER, 1500 * 10**18, txdata, k)
    print 'seq', big_endian_to_int(genesis.get_storage(a, 2**256 - 1))
    v = tx_state_transition(genesis, tx, i * 2 + 2)
    print 'nonce', repr(v)
    print 'seq', big_endian_to_int(genesis.get_storage(a, 2**256 - 1))
    print 'vee', v
    print ct.function_data['getUserValidationCode']
    v = ct.decode('join', ''.join(map(chr, v)))
    print 'Joined with index', v
    vcode2 = call_method(genesis, CASPER, ct, 'getUserValidationCode', v)[0]
    assert vcode2 == vcode
