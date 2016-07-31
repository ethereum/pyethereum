macro calldatachar($x):
    div(calldataload($x), 2**248)

macro calldatabytes_as_int($x, $b):
    div(calldataload($x), 256**(32-$b))

def any():
    positions = array(32)
    positionIndex = 0
    data = string(1024)
    dataPos = 0
    # Can only parse lists
    c = calldatachar(0)
    if c < 192:
        ~invalid()
    if c < 248:
        if ~calldatasize() != 1 + (c - 192):
            ~invalid()
        i = 1
    else:
        L = calldatabytes_as_int(i + 1, c - 247)
        if ~calldatasize() != 1 + (c - 247) + L:
            ~invalid()
        i = 1 + (c - 247)
    while i < ~calldatasize():
        c = calldatachar(i)
        positions[positionIndex] = dataPos
        positionIndex += 1
        if c < 128:
            calldatacopy(data + dataPos, i, 1)
            i += 1
            dataPos += 1
        elif c < 184:
            calldatacopy(data + dataPos, i + 1, c - 128)
            # Output could have been in single-byte format
            if c == 129:
                if calldatachar(i + 1) < 128:
                    ~invalid()
            i += c - 128 + 1
            dataPos += (c - 128)
        elif c < 192:
            L = calldatabytes_as_int(i + 1, c - 183)
            # Forbid leading zero byte
            if calldatachar(i + 1) == 0:
                ~invalid()
            # Forbid too short values
            if L < 56:
                ~invalid()
            calldatacopy(data + dataPos, i + 1 + c - 183, L)
            i += (c - 183) + 1 + L
            dataPos += L
        else:
            # Not handling nested arrays
            ~invalid()
        if dataPos > 1024 or positionIndex > 32:
            ~invalid()
    output = string(2048)
    i = 0
    while i < positionIndex:
        output[i] = positions[i] + positionIndex * 32
        i += 1
    mcopy(output + positionIndex * 32, data, dataPos)
    ~return(output, positionIndex * 32 + dataPos)
