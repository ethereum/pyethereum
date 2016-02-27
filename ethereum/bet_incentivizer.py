from utils import big_endian_to_int
import serpent
from config import CASPER, ETHER
from abi import ContractTranslator

# Code for a contract that anyone can send their bets through. Validators
# should accept transactions to this address because they see that they
# automatically get paid if the transaction is valid
bet_incentivizer_code = """
extern casper.se.py: [getUserAddress:[uint256]:address]
macro CASPER: %d
macro ETHER: %d
data accounts[2**100](balance, gasprice)

def deposit(index):
    self.accounts[index].balance += msg.value
    return(1:bool)

def withdraw(index, val):
    if self.accounts[index].balance >= val and msg.sender == CASPER.getUserAddress(index):
        send(msg.sender, val)
        self.accounts[index].balance -= val
        return(1:bool)
    else:
        return(0:bool)

def finally():
    bet = string(~calldatasize())
    ~calldatacopy(bet, 0, ~calldatasize())
    gasprice = ~calldataload(~calldatasize() - 32)
    if self.accounts[~mload(bet + 4)].balance > gasprice * ~txexecgas():
        output = 0
        ~call(msg.gas - 40000, CASPER, 0, bet, len(bet), ref(output), 32)
        if output:
            with fee = gasprice * (~txexecgas() - msg.gas + 50000):
                ~call(12000, ETHER, 0, [block.coinbase, fee], 64, 0, 0)
                self.accounts[~mload(bet + 4)].balance -= fee
                return(1:bool)

""" % (big_endian_to_int(CASPER), big_endian_to_int(ETHER))

bet_incentivizer_ct = ContractTranslator(serpent.mk_full_signature(bet_incentivizer_code))
