# Validator size groups
validatorSizes = [128, 512, 2048, 8192, 32768, 131072]
# Smallest allowed validator size
minValidatorSize = 32
# Largest allowed validator size
maxValidatorSize = 131072
# Base block reward
BLOCK_REWARD = 10**17
# An epoch number that represents a validator "intending to stay forever"
NO_END_EPOCH = 2**99
# Address of "system" entry point
SYSTEM = 2**160 - 2
# Address of block finalization entry point
FINALIZER = 254
# Store of state roots
STATEROOT_STORE = 0x10
# Store of block hashes
BLOCKHASH_STORE = 0x20
# validator[sizegroup][index]
data validators[2**40][2**40](vchash, validation_code, address, start_epoch, end_epoch, deposit, origDeposit, randao, lock_duration, active)
# Historical sizes of validator groups `(epoch, sizegroup) -> size`
data historicalValidatorCounts[2**40][2**40]
# Current sizes of validator groups
data validatorCounts[2**40]
# A queue for validator slots that have been emptied and can be re-filled
data validatorSlotQueue[2**40][2**40]
# Length of the queue
data validatorSlotQueueLength[2**40]
# Total amount of ETH deposited
data totalDeposits
# Total amount of ETH deposited during previous epochs
data historicalTotalDeposits[2**40]
# Keep track of future changes to total deposits
data totalDepositDeltas[2**40]
# Map of validation code hash to (i, j) indices
data vchashToIndices[]
# The "global randao" used as the seed for consensus
data randao
# Dunkles that have already been included and are thus no longer eligible for inclusion
data dunkles[]
# Timestamp of the genesis block
data genesisTimestamp
# Total number of skips that have taken place
data totalSkips
# Total number of dunkles that has been included
data totalDunklesIncluded
# The current epoch
data currentEpoch
# Has Casper already been initialized?
data initialized
# Current block number
data blockNumber
# Current gas limit
data gasLimit
# Length of an epoch (set during initialization)
data epochLength
# Event for validator induction
event NewValidator()
# Event when a dunkle is added
event DunkleAdded(hash:bytes32)

# 1 part-per-billion per block = ~1.05% annual interest assuming 3s blocks
# 1 ppb per second = 3.20% annual interest
BLOCK_MAKING_PPB = 10

macro abs($x):
    with $w = $x:
        $w * (1 - 2 * ($w < 0))

def const getBlockReward():
    return(max(self.totalDeposits, 1000000 * 10**18) * BLOCK_MAKING_PPB / 1000000000)

def const getLockDuration():
    return(max(min(self.totalDeposits / 10**18 / 2, 10000000), self.epochLength * 2))

def const getEpochLength():
    return(self.epochLength)

def initialize(timestamp:uint256, epoch_length:uint256, number:uint256, gas_limit:uint256):
    require(not self.initialized)
    self.initialized = 1
    self.genesisTimestamp = timestamp
    self.epochLength = epoch_length
    self.currentEpoch = -2
    self.blockNumber = number
    self.gasLimit = gas_limit

def const getHistoricalValidatorCount(epoch, i):
    return(self.historicalValidatorCounts[epoch][i])

def const getValidatorCount(i):
    return(self.validatorCounts[i])

def const getHistoricalTotalDeposits(epoch):
    return(self.historicalTotalDeposits[epoch])

def deposit(validation_code:str, randao):
    # Deposit too small
    if msg.value < minValidatorSize * 10**18:
        ~invalid()
    # Deposit too large
    if msg.value > maxValidatorSize * 10**18:
        ~invalid()
    # Validation code used yet?
    validation_code_hash = sha3(validation_code:str)
    if ~ssize(ref(self.vchashToIndices[validation_code_hash])):
        ~invalid()
    # Max length: 2kb
    if len(validation_code) > 2048:
        ~invalid()
    # Find which bucket to put the validator in
    i = 0
    success = 0
    while i < len(validatorSizes) and not success:
        if msg.value <= validatorSizes[i] * 10**18:
            success = 1
        else:
            i += 1
    if self.validatorSlotQueueLength[i]:
        j = self.validatorSlotQueue[i][self.validatorSlotQueueLength[i] - 1]
        self.validatorSlotQueueLength[i] -= 1
    else:
        j = self.validatorCounts[i]
        self.validatorCounts[i] += 1
    # Store data about the validator
    self.validators[i][j].vchash = sha3(validation_code:str)
    ~sstorebytes(ref(self.validators[i][j].validation_code), validation_code, len(validation_code))
    self.validators[i][j].deposit = msg.value
    self.validators[i][j].origDeposit = msg.value
    self.validators[i][j].start_epoch = self.currentEpoch + 2
    self.validators[i][j].end_epoch = NO_END_EPOCH
    self.validators[i][j].address = msg.sender
    self.validators[i][j].randao = randao
    self.validators[i][j].lock_duration = self.getLockDuration()
    self.totalDepositDeltas[self.validators[i][j].start_epoch] += msg.value
    ~sstorebytes(ref(self.vchashToIndices[validation_code_hash]), [i, j], 64)
    log(type=NewValidator)
    return(1:bool)

# Housekeeping to be done at the start of any epoch
def newEpoch(epoch):
    if msg.sender != self:
        stop
    q = 0
    while q < len(validatorSizes):
        self.historicalValidatorCounts[epoch][q] = self.validatorCounts[q]
        q += 1
    self.totalDeposits += self.totalDepositDeltas[epoch]
    self.historicalTotalDeposits[epoch] = self.totalDeposits
    self.currentEpoch = epoch

def const getTotalDeposits():
    return(self.totalDeposits)

def const getBlockNumber():
    return(self.blockNumber)

def const getGasLimit():
    return(self.gasLimit)

def const getEpoch():
    return(self.currentEpoch)

def const getValidationCode(vchash:bytes32):
    extractIndices(ref(i), ref(j), vchash)
    vcindex = ref(self.validators[i][j].validation_code)
    s = string(~ssize(vcindex))
    ~sloadbytes(vcindex, s, len(s))
    return(s:str)

def const getValidator(skips):
    prevEpoch = max(0, self.currentEpoch - 1)
    # Get the value to mod the seed by
    v = 0
    i = 0
    while i < len(validatorSizes):
        v += validatorSizes[i] * self.historicalValidatorCounts[prevEpoch][i]
        i += 1
    # Get the seed
    validatorGroupIndexSource = mod(sha3(self.randao + skips), v * 10**18)
    # Try to find a validator based on the seed
    while 1:
        # Select a validator group, then select an index in that group
        validatorGroupIndex = 0
        validatorIndex = 0
        done = 0
        while done == 0:
            numValidators = self.historicalValidatorCounts[prevEpoch][validatorGroupIndex]
            if validatorGroupIndexSource < numValidators * validatorSizes[validatorGroupIndex] * 10**18:
                validatorIndex = validatorGroupIndexSource / validatorSizes[validatorGroupIndex] / 10**18
                done = 1
            else:
                validatorGroupIndexSource -= numValidators * validatorSizes[validatorGroupIndex] * 10**18
                validatorGroupIndex += 1
        # Should never happen
        if not done:
            ~invalid()
        # Check if that validator is present, and if the validator's deposit is equal
        # to the max deposit from that category then accept them; if it's less than
        # accept them probabilistically
        if self.validators[validatorGroupIndex][validatorIndex].start_epoch <= self.currentEpoch:
            if self.currentEpoch < self.validators[validatorGroupIndex][validatorIndex].end_epoch:
                origDeposit = self.validators[validatorGroupIndex][validatorIndex].origDeposit
                if mod(sha3(validatorGroupIndexSource), validatorSizes[validatorGroupIndex] * 10**18) < origDeposit:
                    return(self.validators[validatorGroupIndex][validatorIndex].vchash:bytes32)
        validatorGroupIndexSource = mod(sha3(validatorGroupIndexSource), v * 10**18)


def const getMinTimestamp(skips):
    return(self.genesisTimestamp + block.number * 3 + (self.totalSkips + skips) * 6)


def const getRandao(vchash:bytes32):
    extractIndices(ref(i), ref(j), vchash)
    return(self.validators[i][j].randao:bytes32)

macro require($x):
    if not($x):
        ~invalid()

macro extractRLPint($blockdata, $ind, $saveTo, $errMsg):
    if $blockdata[$ind + 1] - blockdata[$ind] > 32:
        return(text($errMsg):str)
    mcopy($saveTo + 32 - ($blockdata[$ind+1] - $blockdata[$ind]), $blockdata + $blockdata[$ind], $blockdata[$ind+1] - $blockdata[$ind])

macro extractRLPint($blockdata, $ind, $saveTo):
    if $blockdata[$ind + 1] - blockdata[$ind] > 32:
        ~invalid()
    mcopy($saveTo + 32 - ($blockdata[$ind+1] - $blockdata[$ind]), $blockdata + $blockdata[$ind], $blockdata[$ind+1] - $blockdata[$ind])

macro validateRLPint($blockdata, $ind, $errMsg):
    if $blockdata[$ind + 1] - $blockdata[$ind] > 32:
        return(text($errMsg):str)

macro validateRLPint($blockdata, $ind):
    if $blockdata[$ind + 1] - $blockdata[$ind] > 32:
        ~invalid()

macro RLPlength($blockdata):
    $blockdata[0] / 32

macro RLPItemLength($blockdata, $i):
    $blockdata[$i + 1] - $blockdata[$i]

macro Exception($text):
    ~return(text($text), len(text($text)))

macro extractIndices($i, $j, $vchash):
    with $indices = array(2):
        ~sloadbytes(ref(self.vchashToIndices[$vchash]), $indices, 64)
        ~mstore($i, $indices[0])
        ~mstore($j, $indices[1])

def any():
    # Block header entry point; expects the block header as input
    if msg.sender == SYSTEM:
        # Get the block data (max 2048 bytes)
        if ~calldatasize() > 2048:
            Exception("Block header too large (max 2048 bytes)")
        rawheader = string(~calldatasize())
        ~calldatacopy(rawheader, 0, ~calldatasize())
        # RLP decode it
        blockdata = string(3096)
        ~call(50000, 253, 0, rawheader, ~calldatasize(), blockdata, 3096)
        # Check length of RLP data
        if RLPlength(blockdata) != 15:
            Exception("Block data has wrong length")
        # Check prevhash
        if RLPItemLength(blockdata, 0) != 32:
            Exception("Prevhash has wrong length")
        extractRLPint(blockdata, 0, ref(prevhash), "")
        bn = self.blockNumber
        ~call(50000, BLOCKHASH_STORE, 0, ref(bn), 32, ref(shouldbe_prevhash), 32)
        if prevhash != shouldbe_prevhash:
            Exception("Prevhash mismatch")
        # Check formatting of miscellaneous params
        if RLPItemLength(blockdata, 1) != 32:
            Exception("Uncles hash must be 32 bytes")
        if RLPItemLength(blockdata, 2) != 20 and RLPItemLength(blockdata, 2) != 0:
            Exception("Coinbase must be 0 or 20 bytes")
        if RLPItemLength(blockdata, 3) != 32 and RLPItemLength(blockdata, 3) != 0:
            Exception("State root must be 0 or 32 bytes")
        if RLPItemLength(blockdata, 4) != 32 and RLPItemLength(blockdata, 4) != 0:
            Exception("Tx list root must be 0 or 32 bytes")
        if RLPItemLength(blockdata, 5) != 32 and RLPItemLength(blockdata, 5) != 0:
            Exception("Receipt root must be 0 or 32 bytes")
        if RLPItemLength(blockdata, 6) != 256:
            Exception("Bloom must be 32 bytes")
        # Extract difficulty
        extractRLPint(blockdata, 7, ref(difficulty), "Failed to extract difficulty")
        if difficulty != 1:
            Exception("Difficulty must equal 1")
        # Extract and check block number
        extractRLPint(blockdata, 8, ref(number), "Failed to extract block number")
        if number != self.blockNumber + 1:
            Exception("Block number mismatch")
        # Extract and check gas limit
        extractRLPint(blockdata, 9, ref(gas_limit), "Failed to extract gas limit")
        if (abs(gas_limit - self.gasLimit) * 1024 > self.gasLimit):
            Exception("Gas limit out of bounds")
        if gas_limit >= 2**63:
            Exception("Gas limit exceeds 2**63 bound")
        # Extract and check gas used
        extractRLPint(blockdata, 10, ref(gas_used), "Failed to extract gas used")
        if gas_used > gas_limit:
            Exception("Gas used exceeds gas limit")
        # Extract timestamp
        extractRLPint(blockdata, 11, ref(timestamp), "Failed to extract timestamp")
        # Extract extra data (format: randao hash, skip count, signature)
        extra_data = string(blockdata[13] - blockdata[12])
        mcopy(extra_data, blockdata + blockdata[12], blockdata[13] - blockdata[12])
        randao = extra_data[0]
        skips = extra_data[1]
        vchash = extra_data[2]
        # Get the signing hash
        ~call(50000, 252, 0, rawheader, ~calldatasize(), ref(signing_hash), 32)
        # Check number of skips; with 0 skips, minimum lag is 3 seconds
        if timestamp < self.getMinTimestamp(skips):
            Exception("Timestamp too early")
        # Get the validator that should be creating this block
        vchash2 = self.getValidator(skips)
        if vchash2 != vchash:
            Exception("Validation code mismatch")
        # Get the validator's indices
        extractIndices(ref(i), ref(j), vchash)
        validation_code = self.getValidationCode(vchash, outchars=3072)
        # Get the randao
        randaoIndex = ref(self.validators[i][j].randao)
        # Check correctness of randao
        require(sha3(randao) == ~sload(randaoIndex))
        # Create a `sigdata` object that stores the hash+signature for verification
        sigdata = string(len(extra_data) - 32)
        sigdata[0] = signing_hash
        mcopy(sigdata + 32, extra_data + 96, len(extra_data) - 96)
        # Check correctness of signature using validation code
        ~callblackbox(500000, validation_code, len(validation_code), sigdata, len(sigdata), ref(verified), 32)
        if not verified:
            Exception("Invalid signature")
        # Block header signature valid!
        ~return(0, 0)


def finalize(rawheader:str):
    if msg.sender == FINALIZER:
        # RLP decode the header
        blockdata = string(3096)
        ~call(50000, 253, 0, rawheader, len(rawheader), blockdata, 3096)
        # Extract extra data (format: randao hash, skip count, validation code hash, signature)
        extra_data = string(blockdata[13] - blockdata[12])
        mcopy(extra_data, blockdata + blockdata[12], blockdata[13] - blockdata[12])
        randao = extra_data[0]
        skips = extra_data[1]
        vchash = extra_data[2]
        # Get the validator's indices
        extractIndices(ref(i), ref(j), vchash)
        self.randao += randao
        self.validators[i][j].randao = randao
        self.validators[i][j].deposit += self.getBlockReward()
        # Extract gas limit
        extractRLPint(blockdata, 9, ref(gas_limit))
        self.gasLimit = gas_limit
        # Extract state root and block hash
        extractRLPint(blockdata, 3, ref(stateroot))
        blockhash = sha3(rawheader:str)
        # Housekeeping if this block starts a new epoch
        self.blockNumber += 1
        if (block.number % self.epochLength == self.epochLength - 1):
            self.newEpoch((block.number + 1) / self.epochLength)
        ~call(70000, STATEROOT_STORE, 0, [block.number, stateroot], 64, 0, 0)
        ~call(70000, BLOCKHASH_STORE, 0, [block.number, blockhash], 64, 0, 0)
    

# Like uncle inclusion, but this time the reward is negative
def includeDunkle(rawheader:str):
    require(len(rawheader) < 2048)
    # RLP decode it
    blockdata = string(3096)
    ~call(50000, 253, 0, rawheader, len(rawheader), blockdata, 3096)
    # Get the signing hash
    ~call(50000, 252, 0, rawheader, len(rawheader), ref(signing_hash), 32)
    # Extract extra data (format: randao hash, skip count, signature)
    extra_data = string(blockdata[13] - blockdata[12])
    mcopy(extra_data, blockdata + blockdata[12], blockdata[13] - blockdata[12])
    skips = extra_data[1]
    vchash = extra_data[2]
    # Get the validation code
    validation_code = self.getValidationCode(vchash, outchars=3072)
    # Create a `sigdata` object that stores the hash+signature for verification
    sigdata = string(len(extra_data) - 32)
    sigdata[0] = signing_hash
    mcopy(sigdata + 32, extra_data + 96, len(extra_data) - 96)
    # Check correctness of signature using validation code
    ~callblackbox(500000, validation_code, len(validation_code), sigdata, len(sigdata), ref(verified), 32)
    require(verified)
    # Make sure the dunkle has not yet been included
    require(not self.dunkles[sha3(rawheader:str)])
    # Extract block number, make sure that the dunkle is not a block
    # at that number, and make sure that the block number is in the
    # past
    extractRLPint(blockdata, 8, ref(number))
    header_hash = sha3(rawheader:str)
    require(header_hash != ~blockhash(number))
    require(number < block.number)
    # Mark the dunkle included
    self.dunkles[header_hash] = block.timestamp
    # Penalize the dunkle creator
    self.validators[i][j].deposit -= (self.getBlockReward() - 1)
    self.totalDunklesIncluded += 1
    log(type=DunkleAdded, header_hash)
    return(1:bool)

# Incentivize cleanup of old dunkles
def removeOldDunkleRecords(hashes):
    i = 0
    while i < len(hashes):
        require(self.dunkles[hashes[i]] and (self.dunkles[hashes[i]] < block.timestamp - 10000000))
        self.dunkles[hashes[i]] = 0
        i += 1
    send(msg.sender, BLOCK_REWARD * len(hashes) / 250)

def const isDunkleIncluded(hash):
    return(self.dunkles[hash] > 0:bool)

def const getTotalDunklesIncluded():
    return(self.totalDunklesIncluded)
        
# Start the process of withdrawing
def startWithdrawal(vchash:bytes32, sig:str):
    # Check correctness of signature using validation code
    x = sha3("withdrawwithdrawwithdrawwithdraw")
    sigsize = len(sig)
    sig[-1] = x
    extractIndices(ref(i), ref(j), vchash)
    vcIndex = ref(self.validators[i][j].validation_code)
    validation_code = string(~ssize(vcIndex))
    ~sloadbytes(vcIndex, validation_code, len(validation_code))
    ~callblackbox(500000, validation_code, len(validation_code), sig - 32, sigsize + 32, ref(verified), 32)
    require(verified)
    if self.validators[i][j].end_epoch == NO_END_EPOCH:
        self.validators[i][j].end_epoch = self.currentEpoch + 2
        self.totalDepositDeltas[self.validators[i][j].end_epoch] -= validatorSizes[i]

def const getStartEpoch(vchash:bytes32):
    extractIndices(ref(i), ref(j), vchash)
    return(self.validators[i][j].start_epoch)

def const getEndEpoch(vchash:bytes32):
    extractIndices(ref(i), ref(j), vchash)
    return(self.validators[i][j].end_epoch)

def const getCurrentEpoch():
    return(self.currentEpoch)

# Finalize withdrawing and take one's money out
def withdraw(vchash:bytes32):
    extractIndices(ref(i), ref(j), vchash)
    if self.validators[i][j].end_epoch * self.epochLength + self.validators[i][j].lock_duration < block.timestamp:
        send(self.validators[i][j].address, self.validators[i][j].deposit)
        self.validators[i][j].deposit = 0
        self.validatorSlotQueue[i][self.validatorSlotQueueLength[i]] = j
        self.validatorSlotQueueLength[i] += 1
