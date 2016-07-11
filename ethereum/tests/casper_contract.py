validatorSizes = [64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072]
BLOCK_REWARD = 10**17
data validators[][](validation_code, address, withdrawal_time, deposit, randao, lock_duration)
data validatorCounts[]
data totalDeposits
data randao
data aunts[]

def const getLockDuration():
    return(max(min(self.totalDeposits / 10**18 / 2, 10000000), 3600))

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
    j = self.validatorCounts[i]
    ~sstorebytes(ref(self.validators[i][j].validation_code), validation_code, len(validation_code))
    self.validators[i][j].deposit = msg.value
    self.validators[i][j].withdrawal_time = 2**99
    self.validators[i][j].address = msg.sender
    self.validators[i][j].randao = randao
    self.validators[i][j].lock_duration = self.getLockDuration()
    self.validatorCounts[i] += 1
    self.totalDeposits += msg.value

def const getTotalDeposits():
    return(self.totalDeposits)

def getValidator(blknum):
    validatorGroupIndexSource = sha3(self.randao) % self.totalDeposits
    # return([validatorGroupIndexSource]:arr)
    validatorGroupIndex = 0
    validatorIndex = 0
    done = 0
    while done == 0:
        if validatorGroupIndexSource < self.validatorCounts[validatorGroupIndex] * validatorSizes[validatorGroupIndex] * 10**18:
            validatorIndex = validatorGroupIndexSource / validatorSizes[validatorGroupIndex] / 10**18
            done = 1
        else:
            validatorGroupIndexSource -= self.validatorCounts[validatorGroupIndex] * validatorSizes[validatorGroupIndex] * 10**18
            validatorGroupIndex += 1
    return([validatorGroupIndex, validatorIndex]:arr)


def any():
    # Block header entry point; expects x+64 bytes where the first 32 are the block header hash
    # without the extra data, the next 32 are the randao and the remainder is the signature
    if msg.sender == 254:
        validatorData = self.getValidator(block.number, outitems=2)
        vcIndex = ref(self.validators[validatorData[0]][validatorData[1]].validation_code)
        randaoIndex = ref(self.validators[validatorData[0]][validatorData[1]].randao)
        validation_code = string(~ssize(vcIndex))
        ~sloadbytes(vcIndex, validation_code, len(validation_code))
        sigdata = string(~calldatasize())
        ~calldatacopy(sigdata, 0, ~calldatasize())
        # Check correctness of randao
        if len(sigdata) < 64 or sha3(sigdata[1]) != ~sload(randaoIndex):
            return(0)
        sigdata[1] = sigdata[0]
        x = 0
        # Check correctness of signature using validation code
        ~callblackbox(500000, validation_code, len(validation_code), sigdata + 32, len(sigdata) - 32, ref(x), 32)
        if x:
            ~sstore(randaoIndex, sigdata[0])
            self.randao += sigdata[0]
            self.validators[validatorData[0]][validatorData[1]].deposit += BLOCK_REWARD
            # Block header signature valid!
            return(1)
        else:
            # Block header signature invalid
            return(0)

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
            self.validators[validatorData[0]][validatorData[1]].withdrawal_time = block.timestamp + 10000000


def withdraw(i, j):
    if self.validators[i][j].withdrawal_time < block.timestamp:
        send(self.validators[i][j].address, self.validators[i][j].deposit)
        self.validators[i][j].deposit = 0
    
