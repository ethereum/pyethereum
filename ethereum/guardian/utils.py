import sys
import serpent

from ethereum.config import (
    CASPER,
    CONST_CALL_SENDER,
    ENTER_EXIT_DELAY,
    RNGSEEDS,
    NULL_SENDER,
)
import ethereum.fastvm as vm
from ethereum.abi import ContractTranslator
from ethereum.utils import (
    safe_ord,
    sha3,
    encode_int32,
    normalize_address,
)
from ethereum.serenity_blocks import (
    apply_msg,
    VMExt,
    get_code,
    EmptyVMExt,
)


# Call a method of a function with no effect
def call_method(state, addr, ct, fun, args, gas=1000000):
    data = ct.encode(fun, args)
    message_data = vm.CallData([safe_ord(x) for x in data], 0, len(data))
    message = vm.Message(CONST_CALL_SENDER, addr, 0, gas, message_data)
    result, gas_remained, data = apply_msg(VMExt(state.clone()), message, get_code(state, addr))
    output = ''.join(map(chr, data))
    return ct.decode(fun, output)[0]


# Helper method for calling Casper
casper_ct = ContractTranslator(serpent.mk_full_signature('ethereum/casper.se.py'))


def call_casper(state, fun, args, gas=1000000):
    return call_method(state, CASPER, casper_ct, fun, args, gas)


# Helper method for getting the guardian index for a particular block number
gvi_cache = {}


def get_guardian_index(state, blknumber):
    if blknumber not in gvi_cache:
        preseed = state.get_storage(RNGSEEDS, blknumber - ENTER_EXIT_DELAY if blknumber >= ENTER_EXIT_DELAY else 2**256 - 1)
        gvi_cache[blknumber] = call_casper(state, 'sampleGuardian', [preseed, blknumber], gas=3000000)
    return gvi_cache[blknumber]


# Accepts any state less than ENTER_EXIT_DELAY blocks old
def is_block_valid(state, block):
    # Determine the desired proposer address and the validation code
    guardian_index = get_guardian_index(state, block.number)
    guardian_address = call_casper(state, 'getGuardianAddress', [guardian_index])
    guardian_code = call_casper(state, 'getGuardianValidationCode', [guardian_index])
    assert isinstance(guardian_code, (str, bytes))
    # Check block proposer correctness
    if block.proposer != normalize_address(guardian_address):
        sys.stderr.write('Block proposer check for %d failed: actual %s desired %s\n' %
                         (block.number, block.proposer.encode('hex'), guardian_address))
        return False
    # Check signature correctness
    message_data = vm.CallData([safe_ord(x) for x in (sha3(encode_int32(block.number) + block.txroot) + block.sig)], 0, 32 + len(block.sig))
    message = vm.Message(NULL_SENDER, '\x00' * 20, 0, 1000000, message_data)
    _, _, signature_check_result = apply_msg(EmptyVMExt, message, guardian_code)
    if signature_check_result != [0] * 31 + [1]:
        sys.stderr.write('Block signature check failed. Actual result: %s\n' % str(signature_check_result))
        return False
    return True


# Convert probability from a number to one-byte encoded form
# using scientific notation on odds with a 3-bit mantissa;
# 0 = 65536:1 odds = 0.0015%, 128 = 1:1 odds = 50%, 255 =
# 1:61440 = 99.9984%
def encode_prob(p):
    lastv = '\x00'
    while 1:
        q = p / (1.0 - p)
        exp = 0
        while q < 1:
            q *= 2.0
            exp -= 1
        while q >= 2:
            q /= 2.0
            exp += 1
        mantissa = int(q * 4 - 3.9999)
        v = chr(max(0, min(255, exp * 4 + 128 + mantissa)))
        return v


# Convert probability from one-byte encoded form to a number
def decode_prob(c):
    c = ord(c)
    q = 2.0**((c - 128) // 4) * (1 + 0.25 * ((c - 128) % 4))
    return q / (1.0 + q)

FINALITY_LOW, FINALITY_HIGH = decode_prob('\x00'), decode_prob('\xff')

# Be VERY careful about updating the above algorithms; if the assert below
# fails (ie. encode and decode are not inverses) then bet serialization will
# break and so casper will break
assert map(encode_prob, map(decode_prob, map(chr, range(256)))) == map(chr, range(256)), map(encode_prob, map(decode_prob, map(chr, range(256))))
