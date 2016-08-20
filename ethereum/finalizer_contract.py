SYSTEM = 2**160 - 2
CASPER = 255

extern casper: [finalize:[bytes]:_]

if msg.sender == SYSTEM:
    ~log1(8, 8, 8)
    header = string(~calldatasize())
    ~calldatacopy(header, 0, ~calldatasize())
    CASPER.finalize(header)
