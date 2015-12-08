from config import BLOCKHASHES, STATEROOTS, BLKNUMBER, CASPER, GAS_CONSUMED, GASLIMIT, NULL_SENDER, ETHER, ECRECOVERACCT
from utils import normalize_address, zpad, encode_int, big_endian_to_int, encode_int32, sha3
from utils import privtoaddr as _privtoaddr
import bitcoin
from serenity_transactions import Transaction
from serenity_blocks import mk_contract_address, tx_state_transition, State
import serpent
import db

# This file provides helper methods for managing ECDSA-based accounts
# on top of Serenity

# Code stored on the blockchain that outputs the blockchain code for
# an ECDSA-secured account. Note that serpent compiling this outputs
# init code, which is essentially code that outputs the desired code.
# Hence, we can take this init code and directly paste it into an
# account and we have a contract which hands out a copy of the ECDSA
# code
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
~mstore(0, ~txexecgas())
~calldatacopy(32, 96, ~calldatasize() - 96)
~mstore(0, ~sha3(0, ~calldatasize() - 64))
~calldatacopy(32, 0, 96)
# Call ECRECOVER contract to get the sender
~call(5000, 1, 0, 0, 128, 0, 32)
# Check sender correctness; exception if not
if ~mload(0) != 0x82a978b3f5962a5b0957d9ee9eef472ee55b42f1:
    ~invalid()
# Sequence number operations
with minusone = ~sub(0, 1):
    with curseq = self.storage[minusone]:
        # Check sequence number correctness, exception if not
        if ~calldataload(96) != curseq:
            ~invalid()
        # Increment sequence number
        self.storage[minusone] = curseq + 1
# Make the sub-call and discard output
with x = ~msize():
    ~call(msg.gas - 50000, ~calldataload(160), ~calldataload(192), 160, ~calldatasize() - 224, x, 1000)
    # Pay for gas
    ~mstore(0, ~calldataload(128))
    ~mstore(32, (~txexecgas() - msg.gas + 50000))
    ~call(12000, ~sub(0, %d), 0, 0, 64, 0, 0)
    ~return(x, ~msize() - x)
""" % (2**160 - big_endian_to_int(ETHER))
constructor_code = serpent.compile(cc)

s = State('', db.EphemDB())
tx_state_transition(s, Transaction(None, 1000000, '', constructor_code))
constructor_output_code = s.get_storage(mk_contract_address(code=constructor_code), '')
index = constructor_output_code.index('\x82\xa9x\xb3\xf5\x96*[\tW\xd9\xee\x9e\xefG.\xe5[B\xf1')

# The init code for an ECDSA account. Calls the constructor storage contract to
# get the ECDSA account code, then uses mcopy to swap the default address for
# the user's pubkeyhash
account_code = serpent.compile("""
def init():
        ~call(100000, ~sub(0, %d), 0, 0, 0, 32, %d)
        ~mstore(0, 0x82a978b3f5962a5b0957d9ee9eef472ee55b42f1)
        ~mcopy(%s + 32, 12, 20)
        ~return(32, %d)
""" % (2**160 - big_endian_to_int(ECRECOVERACCT), len(constructor_code), index, len(constructor_code)))

# Make the account code for a particular pubkey hash
def mk_code(pubkeyhash):
    return account_code.replace('\x82\xa9x\xb3\xf5\x96*[\tW\xd9\xee\x9e\xefG.\xe5[B\xf1', pubkeyhash)

# Provide the address corresponding to a particular public key
def privtoaddr(k):
    return mk_contract_address(code=mk_code(_privtoaddr(k)))

# The code to validate bets made by an account in Casper
validation_code = serpent.compile("""
# We assume that data takes the following schema:
# bytes 0-31: hash
# bytes 32-63: v (ECDSA sig)
# bytes 64-95: r (ECDSA sig)
# bytes 96-127: s (ECDSA sig)

# Call ECRECOVER contract to get the sender
~calldatacopy(0, 0, 128)
~call(5000, 1, 0, 0, 128, 0, 32)
# Check sender correctness
return(~mload(0) == 0x82a978b3f5962a5b0957d9ee9eef472ee55b42f1)
""")

# Make the validation code for a particular address, using a similar
# replacement technique as previously
def mk_validation_code(k):
    pubkeyhash = _privtoaddr(k)
    code3 = validation_code.replace('\x82\xa9x\xb3\xf5\x96*[\tW\xd9\xee\x9e\xefG.\xe5[B\xf1', normalize_address(pubkeyhash))
    s = State('', db.EphemDB())
    tx_state_transition(s, Transaction(None, 1000000, '', code3))
    return s.get_storage(mk_contract_address(code=code3), '')

# Helper function for signing a block
def sign_block(block, key):
    sigdata = sha3(encode_int32(block.number) + block.txroot)
    v, r, s = bitcoin.ecdsa_raw_sign(sigdata, key)
    block.sig = encode_int32(v) + encode_int32(r) + encode_int32(s)
    return block

# Helper function for signing a bet
def sign_bet(bet, key):
    bet.sig = ''
    sigdata = sha3(bet.serialize())
    v, r, s = bitcoin.ecdsa_raw_sign(sigdata, key)
    bet.sig = encode_int32(v) + encode_int32(r) + encode_int32(s)
    s = bet.serialize()
    bet._hash = sha3(s)
    b = __import__('bet')
    b.invhash[bet._hash] = s
    return bet

# Creates data for a transaction with the given gasprice, to address,
# value and data
def mk_txdata(seq, gasprice, to, value, data):
    return encode_int32(seq) + encode_int32(gasprice) + \
        '\x00' * 12 + normalize_address(to) + encode_int32(value) + data

# Signs data+startgas
def sign_txdata(data, gas, key):
    v, r, s = bitcoin.ecdsa_raw_sign(sha3(encode_int32(gas) + data), key)
    return encode_int32(v) + encode_int32(r) + encode_int32(s) + data

# The equivalent of transactions.Transaction(nonce, gasprice, startgas,
# to, value, data).sign(key) in 1.0
def mk_transaction(seq, gasprice, gas, to, value, data, key, create=False):
    code = mk_code(_privtoaddr(key))
    addr = mk_contract_address(code=code)
    data = sign_txdata(mk_txdata(seq, gasprice, to, value, data), gas, key)
    return Transaction(addr, gas, data, code if create else b'')
