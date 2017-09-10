# Not finished, needs to be properly hooked in
# Example code:
# J1 J2 J3 B B B S1 B B R1 B B B P1 P2 C1 C2 B S1 B B B
# B100 for 1 epoch? B5 B1 B2 etc for blocks, B is just mining 1 block!
# Translates into:
# Join with validators 1, 2 and 3. Then create 3 blocks, save a
# checkpoint 1. Create 2 more blocks, then revert to checkpoint 1.
# Create 3 more blocks, then prepare and commit with validators
# 1 and 2. Finally create 3 more blocks.

from ethereum.hybrid_casper import chain
from ethereum.common import verify_execution_results, mk_block_from_prevstate, set_execution_results
from ethereum.utils import sha3
# hybrid casper + casper utils, all in NEW casper contract
#from <INSERT HERE> import casper_init_txs, validation_code_addr_from_privkey, call_casper
from ethereum.hybrid_casper import validator
import re

#validator_lookup_map = {validation_code_addr_from_privkey(sha3(str(i))): i for i in range(20)}

# TODO: Pydoc documentation
# Basic formatting for test language is as follows:
#

class TestLang:
    def __init__(self, test=""):
        self.test = test


    def parse(self):
        for token in self.test.split(' '):
            letters, numbers = re.match('([A-Za-z]*)([0-9]*)', token).groups()
            if letters+numbers != token:
                raise Exception("Bad token: %s" % token)
            if numbers != '':
                numbers = int(numbers)
            # Mines X blocks to the current head
            # If no number specified, adds an epoch of blocks [100]
            # t.mine(number_of_blocks=number)
