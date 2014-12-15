# schema: [opcode, ins, outs, memuses, gas]
#
# memuses are written as an array of (start, len) pairs; values less than
# zero are taken as stackarg indices and values zero or greater are taken
# as literals

opcodes = {
    0x00: ['STOP', 0, 0, 0],
    0x01: ['ADD', 2, 1, 1],
    0x02: ['MUL', 2, 1, 1],
    0x03: ['SUB', 2, 1, 1],
    0x04: ['DIV', 2, 1, 1],
    0x05: ['SDIV', 2, 1, 1],
    0x06: ['MOD', 2, 1, 1],
    0x07: ['SMOD', 2, 1, 1],
    0x08: ['ADDMOD', 3, 1, 1],
    0x09: ['MULMOD', 3, 1, 1],
    0x0a: ['EXP', 2, 1, 1],
    0x0b: ['SIGNEXTEND', 2, 1, 1],
    0x10: ['LT', 2, 1, 1],
    0x11: ['GT', 2, 1, 1],
    0x12: ['SLT', 2, 1, 1],
    0x13: ['SGT', 2, 1, 1],
    0x14: ['EQ', 2, 1, 1],
    0x15: ['ISZERO', 1, 1, 1],
    0x16: ['AND', 2, 1, 1],
    0x17: ['OR', 2, 1, 1],
    0x18: ['XOR', 2, 1, 1],
    0x19: ['NOT', 1, 1, 1],
    0x1a: ['BYTE', 2, 1, 1],
    0x20: ['SHA3', 2, 1, 10],
    0x30: ['ADDRESS', 0, 1, 1],
    0x31: ['BALANCE', 1, 1, 20],
    0x32: ['ORIGIN', 0, 1, 1],
    0x33: ['CALLER', 0, 1, 1],
    0x34: ['CALLVALUE', 0, 1, 1],
    0x35: ['CALLDATALOAD', 1, 1, 1],
    0x36: ['CALLDATASIZE', 0, 1, 1],
    0x37: ['CALLDATACOPY', 3, 0, 1],
    0x38: ['CODESIZE', 0, 1, 1],
    0x39: ['CODECOPY', 3, 0, 1],
    0x3a: ['GASPRICE', 0, 1, 1],
    0x3b: ['EXTCODESIZE', 1, 1, 1],
    0x3c: ['EXTCODECOPY', 4, 0, 1],
    0x40: ['PREVHASH', 0, 1, 1],
    0x41: ['COINBASE', 0, 1, 1],
    0x42: ['TIMESTAMP', 0, 1, 1],
    0x43: ['NUMBER', 0, 1, 1],
    0x44: ['DIFFICULTY', 0, 1, 1],
    0x45: ['GASLIMIT', 0, 1, 1],
    0x50: ['POP', 1, 0, 1],
    0x51: ['MLOAD', 1, 1, 1],
    0x52: ['MSTORE', 2, 0, 1],
    0x53: ['MSTORE8', 2, 0, 1],
    0x54: ['SLOAD', 1, 1, 20],
    0x55: ['SSTORE', 2, 0, 0],
    0x56: ['JUMP', 1, 0, 1],
    0x57: ['JUMPI', 2, 0, 1],
    0x58: ['PC', 0, 1, 1],
    0x59: ['MSIZE', 0, 1, 1],
    0x5a: ['GAS', 0, 1, 1],
    0x5b: ['JUMPDEST', 0, 0, 1],
    0xa0: ['LOG0', 2, 0, 32],
    0xa1: ['LOG1', 3, 0, 64],
    0xa2: ['LOG2', 4, 0, 96],
    0xa3: ['LOG3', 5, 0, 128],
    0xa4: ['LOG4', 6, 0, 160],
    0xf0: ['CREATE', 3, 1, 100],
    0xf1: ['CALL', 7, 1, 20],
    0xf2: ['CALLCODE', 7, 1, 20],
    0xf3: ['RETURN', 2, 1, 1],
    0xff: ['SUICIDE', 1, 1, 0],
}

for i in range(1, 33):
    opcodes[0x5f + i] = ['PUSH' + str(i), 0, 1, 1]

for i in range(1, 17):
    opcodes[0x7f + i] = ['DUP' + str(i), i, i + 1, 1]
    opcodes[0x8f + i] = ['SWAP' + str(i), i + 1, i + 1, 1]

reverse_opcodes = {}
for o in opcodes:
    vars()[opcodes[o][0]] = opcodes[o]
    reverse_opcodes[opcodes[o][0]] = o

# Non-opcode gas prices
GDEFAULT = 1
GMEMORY = 1
GSTORAGEKILL = -100
GSTORAGEMOD = 100
GSTORAGEADD = 300
GEXPONENTBYTE = 1    # cost of EXP exponent per byte
GCOPY = 1            # cost to copy one 32 byte word
GCONTRACTBYTE = 5    # one byte of code in contract creation

GTXCOST = 500        # TX BASE GAS COST
GTXDATAZERO = 1      # TX DATA ZERO BYTE GAS COST
GTXDATANONZERO = 5   # TX DATA NON ZERO BYTE GAS COST
GSHA3WORD = 10       # Cost of SHA3 per word
GSHA256WORD = 50     # Cost of SHA256 per word
GRIPEMD160WORD = 50  # Cost of RIPEMD160 per word
