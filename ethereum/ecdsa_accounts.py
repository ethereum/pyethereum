from config import BLOCKHASHES, STATEROOTS, BLKNUMBER, CASPER, GASLIMIT, NULL_SENDER, ETHER, ECRECOVERACCT, BASICSENDER, GAS_REMAINING, ADDR_BYTES
from utils import normalize_address, zpad, encode_int, big_endian_to_int, \
    encode_int32, sha3, shardify
from utils import privtoaddr as _privtoaddr
import bitcoin
from serenity_transactions import Transaction
from serenity_blocks import mk_contract_address, tx_state_transition, State, initialize_with_gas_limit, get_code
from mandatory_account_code import mandatory_account_code
import serpent
import db
import abi

# This file provides helper methods for managing ECDSA-based accounts
# on top of Serenity

# The "signature checker" code for ECDSA accounts
cc = """
# We assume that data takes the following schema:
# bytes 0-31: v (ECDSA sig)
# bytes 32-63: r (ECDSA sig)
# bytes 64-95: s (ECDSA sig)
# bytes 96-127: gasprice
# bytes 128-159: sequence number (formerly called "nonce")
# bytes 172-191: to
# bytes 192-223: value
# bytes 224+: data
# ~calldatacopy(0, 0, ~calldatasize())
# Prepare the transaction data for hashing: gas + non-sig data
~mstore(128, ~txexecgas())
~calldatacopy(160, 96, ~calldatasize() - 96)
# Hash it
~mstore(0, ~sha3(128, ~calldatasize() - 64))
~calldatacopy(32, 0, 96)
# Call ECRECOVER contract to get the sender
~call(5000, 1, 0, 0, 128, 0, 32)
# Check sender correctness; exception if not
if ~mload(0) != self.storage[2]:
    # ~log1(0, 0, 51)
    ~invalid()
# Check value sufficiency
if self.balance < ~calldataload(192) + ~calldataload(0) * ~txexecgas():
    # ~log1(0, 0, 52)
    ~invalid()
# Sequence number operations
with minusone = ~sub(0, 1):
    with curseq = self.storage[minusone]:
        # Check sequence number correctness, exception if not
        if ~calldataload(128) != curseq:
            # ~log3(0, 0, 53, ~calldataload(128), curseq)
            ~invalid()
        # Increment sequence number
        self.storage[minusone] = curseq + 1
        return(~calldataload(96))
"""
constructor_code = serpent.compile(cc)
constructor_ct = abi.ContractTranslator(serpent.mk_full_signature(cc))

#The "runner" code for ECDSA accounts
rc = """
# We assume that data takes the following schema:
# bytes 0-31: gasprice
# bytes 32-63: v (ECDSA sig)
# bytes 64-96: r (ECDSA sig)
# bytes 96-127: s (ECDSA sig)
# bytes 128-159: sequence number (formerly called "nonce")
# bytes 172-191: to
# bytes 192-223: value
# bytes 224+: data
~calldatacopy(0, 0, ~calldatasize())
~call(msg.gas - 50000, ~calldataload(160), ~calldataload(192), 224, ~calldatasize() - 224, ~calldatasize(), 10000)
~return(~calldatasize(), ~msize() - ~calldatasize())
"""

runner_code = serpent.compile(rc)

s = State('', db.EphemDB())
initialize_with_gas_limit(s, 10**9)
tx_state_transition(s, Transaction(None, 1000000, data='', code=constructor_code))
constructor_output_code = get_code(s, mk_contract_address(code=constructor_code))

# The init code for an ECDSA account. Calls the constructor storage contract to
# get the ECDSA account code, then uses mcopy to swap the default address for
# the user's pubkeyhash
account_code = serpent.compile(("""
def init():
    sstore(0, %d)
    sstore(1, %d)
    sstore(2, 0x82a978b3f5962a5b0957d9ee9eef472ee55b42f1)
""" % (big_endian_to_int(ECRECOVERACCT), big_endian_to_int(BASICSENDER))) + '\n' + mandatory_account_code)

# Make the account code for a particular pubkey hash
def mk_code(pubkeyhash):
    return account_code.replace('\x82\xa9x\xb3\xf5\x96*[\tW\xd9\xee\x9e\xefG.\xe5[B\xf1', pubkeyhash)

# Provide the address corresponding to a particular public key
def privtoaddr(k, left_bound=0):
    return mk_contract_address(code=mk_code(_privtoaddr(k)), left_bound=left_bound)

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
    code3 = validation_code.replace('\x82\xa9x\xb3\xf5\x96*[\tW\xd9\xee\x9e\xefG.\xe5[B\xf1', pubkeyhash)
    s = State('', db.EphemDB())
    initialize_with_gas_limit(s, 10**9)
    tx_state_transition(s, Transaction(None, 1000000, data='', code=code3))
    return get_code(s, mk_contract_address(code=code3))

# Helper function for signing a block
def sign_block(block, key):
    sigdata = sha3(encode_int32(block.number) + block.txroot)
    v, r, s = bitcoin.ecdsa_raw_sign(sigdata, key)
    block.sig = encode_int32(v) + encode_int32(r) + encode_int32(s)
    return block

# Helper function for signing a bet
def sign_bet(bet, key, fee=25 * 10**9):
    bet.sig = ''
    sigdata = sha3(bet.serialize()[:-32])
    v, r, s = bitcoin.ecdsa_raw_sign(sigdata, key)
    bet.sig = encode_int32(v) + encode_int32(r) + encode_int32(s) + encode_int32(fee)
    s = bet.serialize()
    bet._hash = sha3(s)
    return bet

# Creates data for a transaction with the given gasprice, to address,
# value and data
def mk_txdata(seq, gasprice, to, value, data):
    return encode_int32(gasprice) + encode_int32(seq) + \
        '\x00' * (32 - ADDR_BYTES) + normalize_address(to) + encode_int32(value) + data

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
    return Transaction(addr, gas, data=data, code=code if create else b'')
