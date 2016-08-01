macro calldatachar($x):
    div(calldataload($x), 2**248)

macro calldatabytes_as_int($x, $b):
    div(calldataload($x), 256**(32-$b))

macro REMOVE_POS: 12

def any():
    moose = string(~calldatasize())
    ~calldatacopy(moose, 0, ~calldatasize())
    # ~log1(moose, len(moose), 90)
    # Can only parse lists
    c0 = calldatachar(0)
    if c0 < 248:
        ~invalid()
    # Shortcut: we know the header is >56 bytes anyway (even without ED)
    L = calldatabytes_as_int(i + 1, c0 - 247)
    if ~calldatasize() != 1 + (c0 - 247) + L:
        ~invalid()
    i = 1 + (c0 - 247)
    # Med state: i = position of first element
        
    pos = 0
    ed_start = 0
    ed_next_start = 0
    while pos < REMOVE_POS + 1:
        if pos == REMOVE_POS:
            ed_start = i - (1 + (c0 - 247))
        c = calldatachar(i)
        if c < 128:
            i += 1
        elif c < 184:
            i += c - 128 + 1
        elif c < 192:
            L = calldatabytes_as_int(i + 1, c - 183)
            i += (c - 183) + 1 + L
        else:
            ~invalid()
        pos += 1
    ed_next_start = i - (1 + (c0 - 247))
    hashdata = string(~calldatasize())
    totlen = ~calldatasize() - (1 + (c0 - 247)) - ed_next_start + ed_start
    if totlen < 256:
        setch(hashdata, 0, 248)
        setch(hashdata, 1, totlen)
        calldatacopy(hashdata + 2, 1 + (c0 - 247), ed_start)
        calldatacopy(hashdata + 2 + ed_start, 1 + (c0 - 247) + ed_next_start, ~calldatasize() - ed_next_start)
        # ~log1(hashdata, totlen + 2, 91)
        return(~sha3(hashdata, totlen + 2))
    else:
        setch(hashdata, 0, 249)
        setch(hashdata, 1, div(totlen, 256))
        setch(hashdata, 2, mod(totlen, 256))
        calldatacopy(hashdata + 3, 1 + (c0 - 247), ed_start)
        calldatacopy(hashdata + 3 + ed_start, 1 + (c0 - 247) + ed_next_start, ~calldatasize() - ed_next_start)
        # ~log1(hashdata, totlen + 3, 92)
        return(~sha3(hashdata, totlen + 3))
