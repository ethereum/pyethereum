validatorSizes = [64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072]
BLOCK_REWARD = 10**17
EPOCH_LENGTH = 1000
# validator[sizegroup][index]
data validators[2**40][2**40](validation_code, address, start_epoch, end_epoch, deposit, randao, lock_duration)
data historicalValidatorCounts[2**40][2**40]
# validator_group_sizes[epoch][sizegroup]
data validatorCounts[2**40]
data validatorSlotQueue[2**40][2**40]
data validatorSlotQueueLength[2**40]
data totalDeposits
data historicalTotalDeposits[2**40]
data randao
data aunts[]
data genesisTimestamp
data totalSkips
event NewValidator(i, j)

def const getLockDuration():
    return(max(min(self.totalDeposits / 10**18 / 2, 10000000), EPOCH_LENGTH * 2))

def setGenesisTimestamp(t:uint256):
    if not self.genesisTimestamp:
        self.genesisTimestamp = t

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
    epoch = block.number / EPOCH_LENGTH
    if self.validatorSlotQueueLength[i]:
        j = self.validatorSlotQueue[i][self.validatorSlotQueueLength[i] - 1]
        self.validatorSlotQueueLength[i] -= 1
    else:
        j = self.validatorCounts[i]
        self.validatorCounts[i] += 1
    ~sstorebytes(ref(self.validators[i][j].validation_code), validation_code, len(validation_code))
    self.validators[i][j].deposit = msg.value
    self.validators[i][j].start_epoch = if(block.number, (block.number / EPOCH_LENGTH) + 1, 0)
    self.validators[i][j].end_epoch = 2**99
    self.validators[i][j].address = msg.sender
    self.validators[i][j].randao = randao
    self.validators[i][j].lock_duration = self.getLockDuration()
    self.totalDeposits += msg.value
    # Update historical validator counts if needed
    if block.number % EPOCH_LENGTH == 0:
        q = 0
        while q < len(validatorSizes):
            self.historicalValidatorCounts[block.number / EPOCH_LENGTH][i] = self.validatorCounts[i]
            q += 1
        self.historicalTotalDeposits[block.number / EPOCH_LENGTH] = self.totalDeposits
    log(type=NewValidator, i, j)
    return([i, j]:arr)

def const getTotalDeposits():
    return(self.totalDeposits)

def const getValidator(skips):
    epoch = max(0, block.number / EPOCH_LENGTH - 1)
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
        ~stop()

def any():
    # Block header entry point; expects the block header as input
    if msg.sender == 254:
        # Get the block data (max 2048 bytes)
        require(~calldatasize() <= 2048)
        rawheader = string(~calldatasize())
        ~calldatacopy(rawheader, 0, ~calldatasize())
        # RLP decode it
        blockdata = string(3096)
        ~call(50000, 253, 0, rawheader, ~calldatasize(), blockdata, 3096)
        # Extract difficulty
        difficulty = 0
        require(blockdata[8] - blockdata[7] <= 32)
        mcopy(ref(difficulty) + 32 - (blockdata[8] - blockdata[7]), blockdata + blockdata[7], blockdata[8] - blockdata[7])
        # Extract timestamp
        timestamp = 0
        require(blockdata[12] - blockdata[11] <= 32)
        mcopy(ref(timestamp) + 32 - (blockdata[12] - blockdata[11]), blockdata + blockdata[11], blockdata[12] - blockdata[11])
        # Extract extra data (format: randao hash, skip count, signature)
        extra_data = string(blockdata[13] - blockdata[12])
        mcopy(extra_data, blockdata + blockdata[12], blockdata[13] - blockdata[12])
        randao = extra_data[0]
        skips = extra_data[1]
        ~log1(extra_data, len(extra_data), 5)
        # Get the signing hash
        signing_hash = 0
        ~call(50000, 252, 0, rawheader, ~calldatasize(), ref(signing_hash), 32)
        # Check number of skips; with 0 skips, minimum lag is 3 seconds
        min_timestamp = self.getMinTimestamp(skips)
        require(block.timestamp >= min_timestamp)
        require(block.difficulty == 1)
        # Get the validator that should be creating this block
        validatorData = self.getValidator(skips, outitems=2)
        vcIndex = ref(self.validators[validatorData[0]][validatorData[1]].validation_code)
        # Get the validation code
        validation_code = string(~ssize(vcIndex))
        ~sloadbytes(vcIndex, validation_code, len(validation_code))
        randaoIndex = ref(self.validators[validatorData[0]][validatorData[1]].randao)
        # Check correctness of randao
        require(sha3(randao) == ~sload(randaoIndex))
        ~log1(9, 9, 9)
        # Create a `sigdata` object that stores the hash+signature for verification
        sigdata = string(len(extra_data) - 32)
        sigdata[0] = signing_hash
        mcopy(sigdata + 32, extra_data + 64, len(extra_data) - 64)
        ~log1(sigdata, len(sigdata), 10)
        # Check correctness of signature using validation code
        x = 0
        ~callblackbox(500000, validation_code, len(validation_code), sigdata, len(sigdata), ref(x), 32)
        require(x)
        ~log1(12, 12, 12)
        ~sstore(randaoIndex, sigdata[0])
        self.randao += sigdata[0]
        self.validators[validatorData[0]][validatorData[1]].deposit += BLOCK_REWARD
        self.totalSkips += skips
        # Update historical validator counts if needed
        if block.number % EPOCH_LENGTH == 0:
            i = 0
            while i < len(validatorSizes):
                self.historicalValidatorCounts[block.number / EPOCH_LENGTH][i] = self.validatorCounts[i]
                i += 1
            self.historicalTotalDeposits[block.number / EPOCH_LENGTH] = self.totalDeposits
        # Block header signature valid!
        return(1)

# Like uncle inclusion, but this time the reward is negative
def includeAunt(blocknumber, blockdata:str):
    if ~blockhash(blocknumber) != blockdata[0]:
        validatorData = self.getValidator(blocknumber, outitems=2)
        vcIndex = ref(self.validators[validatorData[0]][validatorData[1]].validation_code)
        randaoIndex = ref(self.validators[validatorData[0]][validatorData[1]].randao)
        validation_code = string(~ssize(vcIndex))
        ~sloadbytes(vcIndex, validation_code, len(validation_code))
        sigdata = string(~calldatasize())
        ~calldatacopy(sigdata, 0, ~calldatasize())
        x = 0
        # Check correctness of signature using validation code
        ~callblackbox(500000, validation_code, len(validation_code), sigdata + 32, len(sigdata) - 32, ref(x), 32)
        if x and self.aunts[blockdata[0]]:
            self.validators[validatorData[0]][validatorData[1]].deposit -= BLOCK_REWARD
            self.aunts[blockdata[0]] = 1
        
def startWithdrawal(sig:str):
        # Check correctness of signature using validation code
        x = sha3("withdrawwithdrawwithdrawwithdraw")
        sigsize = len(sig)
        sig[-1] = x
        validatorData = self.getValidator(blocknumber, outitems=2)
        vcIndex = ref(self.validators[validatorData[0]][validatorData[1]].validation_code)
        randaoIndex = ref(self.validators[validatorData[0]][validatorData[1]].randao)
        validation_code = string(~ssize(vcIndex))
        ~callblackbox(500000, validation_code, len(validation_code), sig - 32, sigsize + 32, ref(x), 32)
        if x:
            self.validators[validatorData[0]][validatorData[1]].end_epoch = block.number / EPOCH_LENGTH + 1


def withdraw(i, j):
    if self.validators[i][j].end_epoch * EPOCH_LENGTH + self.validators[i][j].lock_duration < block.timestamp:
        send(self.validators[i][j].address, self.validators[i][j].deposit)
        self.validators[i][j].deposit = 0
    
