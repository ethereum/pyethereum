from utils import big_endian_to_int
from config import GAS_DEPOSIT, NULL_SENDER
import serpent
from abi import ContractTranslator

# The code that every account must have in order for miners to accept
# transactions going to it
mandatory_account_code = """
# Copy the calldata to bytes 32...x+32
~calldatacopy(64, 0, ~calldatasize())
# If we are getting a message NOT from the origin object, then just
# pass it along to the runner code
if msg.sender != %d:
    ~mstore(0, 0)
    ~delegatecall(msg.gas - 50000, self.storage[1], 64, ~calldatasize(), 64 + ~calldatasize(), 10000)
    ~return(64 + ~calldatasize(), ~msize() - 64 - ~calldatasize())
# Run the sig checker code; self.storage[0] = sig checker
# sig checker should return gas price
if not ~delegatecall(250000, self.storage[0], 64, ~calldatasize(), 32, 32):
    ~invalid()
# Compute the gas payment deposit
~mstore(0, ~mload(32) * ~txexecgas())
# Send the gas payment into the deposit contract
if self.balance < ~mload(0):
    ~invalid()
~call(2000, %d, ~mload(0), 0, 0, 0, 32)
# Do the main call; self.storage[1] = main running code
~breakpoint()
~delegatecall(msg.gas - 50000, self.storage[1], 64, ~calldatasize(), 64, 10000)
# Call the deposit contract to refund
~mstore(0, ~mload(32) * msg.gas)
~call(2000, %d, ~mload(0), 0, 32, 0, 32)
~return(64, ~msize() - 64)
""" % (big_endian_to_int(NULL_SENDER), big_endian_to_int(GAS_DEPOSIT), big_endian_to_int(GAS_DEPOSIT))

mandatory_account_evm = serpent.compile(mandatory_account_code)
# Strip off the initiation wrapper
mandatory_account_evm = mandatory_account_evm[mandatory_account_evm.find('\x56')+1:]
mandatory_account_evm = mandatory_account_evm[:mandatory_account_evm[:-1].rfind('\xf3')+1]

mandatory_account_ct = ContractTranslator(serpent.mk_full_signature(mandatory_account_code))
