validatorSizes = [64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072]
BLOCK_REWARD = 10**17
SYSTEM = 2**160 - 2
FINALIZER = 254
STATEROOT_STORE = 10
BLOCKHASH_STORE = 20
# validator[sizegroup][index]
data validators[2**40][2**40](validation_code, address, start_epoch, end_epoch, deposit, randao, lock_duration, active)
data historicalValidatorCounts[2**40][2**40]
# validator_group_sizes[epoch][sizegroup]
data validatorCounts[2**40]
data validatorSlotQueue[2**40][2**40]
data validatorSlotQueueLength[2**40]
data totalDeposits
data historicalTotalDeposits[2**40]
data totalDepositDeltas[2**40]
data randao
data dunkles[]
data genesisTimestamp
data totalSkips
data totalDunklesIncluded
data currentEpoch
data initialized
data blockNumber
event NewValidator(i, j)
data epochLength
event DunkleAdded(hash:bytes32)

# 1 part-per-billion per block = ~1.05% annual interest assuming 3s blocks
# 1 ppb per second = 3.20% annual interest
BLOCK_MAKING_PPB = 10
NO_END_EPOCH = 2**99

def const getBlockReward():
    return(max(self.totalDeposits, 1000000 * 10**18) * BLOCK_MAKING_PPB / 1000000000)

def const getLockDuration():
    return(max(min(self.totalDeposits / 10**18 / 2, 10000000), self.epochLength * 2))

def const getEpochLength():
    return(self.epochLength)

def initialize(timestamp:uint256, epoch_length:uint256, number:uint256):
    require(not self.initialized)
    self.initialized = 1
    self.genesisTimestamp = timestamp
    self.epochLength = epoch_length
    self.currentEpoch = -1
    self.blockNumber = number

def const getValidationCode(i, j):
    storage_index = ref(self.validators[i][j].validation_code)
    o = string(~ssize(storage_index))
    ~sloadbytes(storage_index, o, len(o))
    return(o:str)

def const getHistoricalValidatorCount(epoch, i):
    return(self.historicalValidatorCounts[epoch][i])

def const getHistoricalTotalDeposits(epoch):
    return(self.historicalTotalDeposits[epoch])

def deposit(validation_code:str, randao):
    i = 0
    success = 0
    while i < len(validatorSizes) and not success:
        if msg.value == validatorSizes[i] * 10**18:
            success = 1
        else:
            i += 1
    if not success:
        ~invalid()
    if self.validatorSlotQueueLength[i]:
        j = self.validatorSlotQueue[i][self.validatorSlotQueueLength[i] - 1]
        self.validatorSlotQueueLength[i] -= 1
    else:
        j = self.validatorCounts[i]
        self.validatorCounts[i] += 1
    ~sstorebytes(ref(self.validators[i][j].validation_code), validation_code, len(validation_code))
    self.validators[i][j].deposit = msg.value
    self.validators[i][j].start_epoch = self.currentEpoch + 1
    self.validators[i][j].end_epoch = NO_END_EPOCH
    self.validators[i][j].address = msg.sender
    self.validators[i][j].randao = randao
    self.validators[i][j].lock_duration = self.getLockDuration()
    self.totalDepositDeltas[self.validators[i][j].start_epoch] += msg.value
    log(type=NewValidator, i, j)
    return([i, j]:arr)

# Housekeeping to be done at the start of any epoch
def newEpoch():
    currentEpoch = block.number / self.epochLength
    log2(3, 3, 3, currentEpoch)
    if self.currentEpoch != currentEpoch - 1:
        stop
    q = 0
    while q < len(validatorSizes):
        log3(4, 4, 4, q, self.validatorCounts[q])
        self.historicalValidatorCounts[currentEpoch][q] = self.validatorCounts[q]
        q += 1
    self.totalDeposits += self.totalDepositDeltas[currentEpoch]
    self.historicalTotalDeposits[currentEpoch] = self.totalDeposits
    self.currentEpoch = currentEpoch

def const getTotalDeposits():
    return(self.totalDeposits)

def const getEpoch():
    return(self.currentEpoch)

def const getValidator(skips):
    epoch = max(0, self.currentEpoch - 1)
    validatorGroupIndexSource = mod(sha3(self.randao + skips), self.historicalTotalDeposits[epoch])
    while 1:
        # return([validatorGroupIndexSource]:arr)
        validatorGroupIndex = 0
        validatorIndex = 0
        done = 0
        while done == 0:
            numValidators = self.historicalValidatorCounts[epoch][validatorGroupIndex]
            if validatorGroupIndexSource < numValidators * validatorSizes[validatorGroupIndex] * 10**18:
                validatorIndex = validatorGroupIndexSource / validatorSizes[validatorGroupIndex] / 10**18
                done = 1
            else:
                validatorGroupIndexSource -= numValidators * validatorSizes[validatorGroupIndex] * 10**18
                validatorGroupIndex += 1
        if self.validators[validatorGroupIndex][validatorIndex].start_epoch <= epoch:
            if epoch < self.validators[validatorGroupIndex][validatorIndex].end_epoch:
                return([validatorGroupIndex, validatorIndex]:arr)


def const getMinTimestamp(skips):
    return(self.genesisTimestamp + block.number * 3 + (self.totalSkips + skips) * 6)


def const getRandao(i, j):
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
    ~return($text, len($text))

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
        ~call(50000, BLOCKHASH_STORE, 0, bn, 32, shouldbe_prevhash, 32)
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
        # Extract and check block number
        extractRLPint(blockdata, 8, ref(number), "Failed to extract block number")
        if number != self.blockNumber + 1:
            Exception("Block number mismatch")
        # Extract and check gas limit
        extractRLPint(blockdata, 9, ref(gas_limit), "Failed to extract gas limit")
        if gas_limit >= 2**63:
            Exception("Gas limit too high")
        # Extract and check gas used
        extractRLPint(blockdata, 10, ref(gas_used), "Failed to extract gas used")
        if gas_limit > gas_limit:
            Exception("Gas used exceeds gas limit")
        # Extract timestamp
        extractRLPint(blockdata, 11, ref(timestamp), "Failed to extract timestamp")
        # Extract extra data (format: randao hash, skip count, i, j, signature)
        extra_data = string(blockdata[13] - blockdata[12])
        mcopy(extra_data, blockdata + blockdata[12], blockdata[13] - blockdata[12])
        randao = extra_data[0]
        skips = extra_data[1]
        i = extra_data[2]
        j = extra_data[3]
        # Get the signing hash
        ~call(50000, 252, 0, rawheader, ~calldatasize(), ref(signing_hash), 32)
        # Check number of skips; with 0 skips, minimum lag is 3 seconds
        if timestamp < self.getMinTimestamp(skips):
            Exception("Timestamp too early")
        # Get the validator that should be creating this block
        validatorData = self.getValidator(skips, outitems=2)
        require(validatorData[0] == i)
        require(validatorData[1] == j)
        # Get the validation code
        vcIndex = ref(self.validators[i][j].validation_code)
        validation_code = string(~ssize(vcIndex))
        ~sloadbytes(vcIndex, validation_code, len(validation_code))
        randaoIndex = ref(self.validators[i][j].randao)
        # Check correctness of randao
        require(sha3(randao) == ~sload(randaoIndex))
        # Create a `sigdata` object that stores the hash+signature for verification
        sigdata = string(len(extra_data) - 32)
        sigdata[0] = signing_hash
        mcopy(sigdata + 32, extra_data + 128, len(extra_data) - 128)
        # Check correctness of signature using validation code
        ~callblackbox(500000, validation_code, len(validation_code), sigdata, len(sigdata), ref(verified), 32)
        require(verified)
        # ~sstore(randaoIndex, randao)
        # self.randao += randao
        # self.totalSkips += skips
        # Block header signature valid!
        ~return(0, 0)


def finalize(rawheader:str):
    if msg.sender == FINALIZER:
        # RLP decode the header
        blockdata = string(3096)
        ~call(50000, 253, 0, rawheader, len(rawheader), blockdata, 3096)
        # Extract extra data (format: randao hash, skip count, i, j, signature)
        extra_data = string(blockdata[13] - blockdata[12])
        mcopy(extra_data, blockdata + blockdata[12], blockdata[13] - blockdata[12])
        randao = extra_data[0]
        skips = extra_data[1]
        i = extra_data[2]
        j = extra_data[3]
        self.randao += randao
        self.validators[i][j].randao = randao
        self.validators[i][j].deposit += self.getBlockReward()
        # Housekeeping if this block starts a new epoch
        if (block.number % self.epochLength == 0):
            self.newEpoch()
    

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
    i = extra_data[2]
    j = extra_data[3]
    # Get the validation code
    vcIndex = ref(self.validators[i][j].validation_code)
    validation_code = string(~ssize(vcIndex))
    ~sloadbytes(vcIndex, validation_code, len(validation_code))
    # Create a `sigdata` object that stores the hash+signature for verification
    sigdata = string(len(extra_data) - 32)
    sigdata[0] = signing_hash
    mcopy(sigdata + 32, extra_data + 128, len(extra_data) - 128)
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
def startWithdrawal(i, j, sig:str):
    # Check correctness of signature using validation code
    x = sha3("withdrawwithdrawwithdrawwithdraw")
    sigsize = len(sig)
    sig[-1] = x
    vcIndex = ref(self.validators[i][j].validation_code)
    validation_code = string(~ssize(vcIndex))
    ~sloadbytes(vcIndex, validation_code, len(validation_code))
    ~callblackbox(500000, validation_code, len(validation_code), sig - 32, sigsize + 32, ref(verified), 32)
    require(verified)
    if self.validators[i][j].end_epoch == NO_END_EPOCH:
        self.validators[i][j].end_epoch = self.currentEpoch + 2
        self.totalDepositDeltas[self.validators[i][j].end_epoch] -= validatorSizes[i]

def const getStartEpoch(i, j):
    return(self.validators[i][j].start_epoch)

def const getEndEpoch(i, j):
    return(self.validators[i][j].end_epoch)

def const getCurrentEpoch():
    return(self.currentEpoch)

# Finalize withdrawing and take one's money out
def withdraw(i, j):
    if self.validators[i][j].end_epoch * self.epochLength + self.validators[i][j].lock_duration < block.timestamp:
        send(self.validators[i][j].address, self.validators[i][j].deposit)
        self.validators[i][j].deposit = 0
        self.validatorSlotQueue[i][self.validatorSlotQueueLength[i]] = j
        self.validatorSlotQueueLength[i] += 1
