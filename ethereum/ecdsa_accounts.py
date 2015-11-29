from config import BLOCKHASHES, STATEROOTS, BLKNUMBER, CASPER, GAS_CONSUMED, GASLIMIT, NULL_SENDER, ETHER, ECRECOVERACCT
from utils import normalize_address, zpad, encode_int, big_endian_to_int, encode_int32, sha3
from utils import privtoaddr as _privtoaddr
import bitcoin
from serenity_transactions import Transaction
from serenity_blocks import mk_contract_address, tx_state_transition, State
import serpent
import db

cc = """
# We assume that data takes the following schema:
# bytes 0-31: v (ECDSA sig)
# bytes 32-63: r (ECDSA sig)
# bytes 64-95: s (ECDSA sig)
# bytes 96-127: sequence number (formerly called "nonce")
# bytes 128-159: gasprice
# bytes 172-191: to
# bytes 192-223: value
# bytes 224+: data

# Get the hash for transaction signing
sigdata = string(~calldatasize() - 64)
~mstore(sigdata, ~txexecgas())
~calldatacopy(sigdata + 32, 96, ~calldatasize() - 96)
h = ~sha3(sigdata, ~calldatasize() - 64)
# Call ECRECOVER contract to get the sender
~log3(50, h, ~calldataload(0), ~calldataload(32), ~calldataload(64))
~call(5000, 1, 0, [h, ~calldataload(0), ~calldataload(32), ~calldataload(64)], 128, ref(addr), 32)
~log1(51, 51, ~calldatasize())
myaddr = 0x82a978b3f5962a5b0957d9ee9eef472ee55b42f1
~log4(0, 0, addr, myaddr, 0, 0)
# Check sender correctness
assert addr == myaddr
~log2(52, 1, ~calldataload(96), self.storage[~sub(0, 1)])
# Check sequence number correctness
assert ~calldataload(96) == self.storage[~sub(0, 1)]
~log0(53, 1)
# Increment sequence number
self.storage[~sub(0, 1)] += 1
# Make the sub-call and discard output
~log2(54, 1, ~calldataload(160), ~calldataload(192))
x = ~msize()
~call(msg.gas - 50000, ~calldataload(160), ~calldataload(192), sigdata + 160, ~calldatasize() - 224, x, 1000)
# Pay for gas
~call(40000, block.coinbase, ~calldataload(128) * (~txexecgas() - msg.gas + 50000), 0, 0, 0, 0)
~return(x, ~msize() - x)
"""
constructor_code = serpent.compile(cc)

validation_code = """
# We assume that data takes the following schema:
# bytes 0-31: hash
# bytes 32-63: v (ECDSA sig)
# bytes 64-95: r (ECDSA sig)
# bytes 96-127: s (ECDSA sig)

# Call ECRECOVER contract to get the sender
~call(5000, 1, 0, [~calldataload(0), ~calldataload(32), ~calldataload(64), ~calldataload(96)], 128, 0, 32)
# Check sender correctness
return(~mload(0) == 0x82a978b3f5962a5b0957d9ee9eef472ee55b42f1)
"""
s = State('', db.EphemDB())
tx_state_transition(s, Transaction(None, 1000000, '', constructor_code), 0)
constructor_output_code = s.get_storage(mk_contract_address(code=constructor_code), '')
index = constructor_output_code.index('\x82\xa9x\xb3\xf5\x96*[\tW\xd9\xee\x9e\xefG.\xe5[B\xf1')

# Make the account code for a particular address
def mk_code(addr):
    return serpent.compile("""
def init():
        ~call(100000, ~sub(0, %d), 0, 0, 0, 32, %d)
        ~mstore(0, 0x%s)
        ~mcopy(%s + 32, 12, 20)
        ~return(32, %d)
    """ % (2**160 - big_endian_to_int(ECRECOVERACCT), len(constructor_code), normalize_address(addr).encode('hex'), index, len(constructor_code)))

def privtoaddr(k):
    return mk_contract_address(code=mk_code(_privtoaddr(k)))

# Make the validation code for a particular address
def mk_validation_code(addr):
    code3 = serpent.compile(validation_code)
    s = State('', db.EphemDB())
    tx_state_transition(s, Transaction(None, 1000000, '', code3), 0)
    return s.get_storage(mk_contract_address(code=code3), '')

# Creates data for a transaction 
def mk_txdata(seq, gasprice, to, value, data):
    return encode_int32(seq) + encode_int32(gasprice) + \
        '\x00' * 12 + normalize_address(to) + encode_int32(value) + data

# Signs data+startgas
def sign_txdata(data, execgas, key):
    v, r, s = bitcoin.ecdsa_raw_sign(sha3(encode_int32(execgas) + data), key)
    return encode_int32(v) + encode_int32(r) + encode_int32(s) + data

def mk_transaction(seq, gasprice, execgas, to, value, data, key, create=False):
    code = mk_code(_privtoaddr(key))
    addr = mk_contract_address(code=code)
    data = sign_txdata(mk_txdata(seq, gasprice, to, value, data), execgas, key)
    return Transaction(addr, execgas, data, code if create else b'')
