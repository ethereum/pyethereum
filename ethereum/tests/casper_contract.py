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
    log(type=NewValidator, i, j)
    return([i, j]:arr)

def const getTotalDeposits():
    return(self.totalDeposits)

def const getValidator(skips):
    validatorGroupIndexSource = sha3(self.randao + skips) % self.totalDeposits
    epoch = max(0, block.number / EPOCH_LENGTH - 1)
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


def any():
    # Block header entry point; expects x+96 bytes in the format:
    # [block header hash, randao, num_skips] + signature
    # where everything after the block header hash is header extradata
    if msg.sender == 254:
        # Check number of skips; with 0 skips, minimum lag is 3 seconds
        skips = ~calldataload(64)
        min_timestamp = self.getMinTimestamp(skips)
        if block.timestamp < min_timestamp:
            ~return(0, 0)
        # Get the validator that should be creating this block
        validatorData = self.getValidator(skips, outitems=2)
        vcIndex = ref(self.validators[validatorData[0]][validatorData[1]].validation_code)
        # Get the validation code
        validation_code = string(~ssize(vcIndex))
        ~sloadbytes(vcIndex, validation_code, len(validation_code))
        randaoIndex = ref(self.validators[validatorData[0]][validatorData[1]].randao)
        # Check correctness of randao
        if sha3(~calldataload(32)) != ~sload(randaoIndex):
            ~return(0, 0)
        # Create a `sigdata` object that stores the hash+signature for verification
        sigdata = string(~calldatasize() - 64)
        sigdata[0] = ~calldataload(0)
        ~calldatacopy(sigdata + 32, 96, ~calldatasize() - 64)
        # Check correctness of signature using validation code
        x = 0
        ~callblackbox(500000, validation_code, len(validation_code), sigdata, len(sigdata), ref(x), 32)
        if x:
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
            # Block header signature valid!
            return(1)
        else:
            # Block header signature invalid
            ~return(0, 0)

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
    
