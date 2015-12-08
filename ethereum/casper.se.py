data nextUserPos # map to storage index 0
data users[2**50](address, prevsubmission, deposit_size, induction_height, withdrawal_height, validationCode, seq, prevhash, pos, blockhashes[2**50], stateroots[2**50], probs[2**50], profits[2**50])
data deletedUserPositions[2**50]
data nextDeletedUserPos
data userPosToIndexMap[2**50]
data nextUserIndex
data activeValidators

macro MIN_DEPOSIT: 1500 * 10**18

macro MAX_DEPOSIT: 60000 * 10**18

macro ENTER_EXIT_DELAY: 60

macro WITHDRAWAL_WAITTIME: 20

macro SCORING_REWARD_DIVISOR: 3 * 10**18 # 61440 * 61440 * 10**9 / (3 * 10**18) ~= 1, so a max probability bet gone wrong is a full slashing

macro MAX_INCENTIVIZATION_DEPTH: 160


# Become a validator
def join(validationCode:bytes):
    assert msg.value >= MIN_DEPOSIT and msg.value <= MAX_DEPOSIT
    if self.nextDeletedUserPos:
        userPos = self.deletedUserPositions[self.nextDeletedUserPos - 1]
        self.nextDeletedUserPos -= 1
    else:
        userPos = self.nextUserPos
        self.nextUserPos = userPos + 1
    userIndex = self.nextUserIndex
    self.userPosToIndexMap[userPos] = userIndex
    self.nextUserIndex = userIndex + 1
    self.users[userIndex].address = msg.sender
    self.users[userIndex].pos = userPos
    ~sstorebytes(ref(self.users[userIndex].validationCode), validationCode, len(validationCode))
    self.users[userIndex].deposit_size = msg.value
    self.users[userIndex].induction_height = if(block.number, block.number + ENTER_EXIT_DELAY, 0)
    self.users[userIndex].withdrawal_height = 2**100
    return(userIndex:uint256)


# Leave the validator pool
def withdraw(index:uint256):
    if self.users[index].withdrawal_height + WITHDRAWAL_WAITTIME <= block.number:
        send(self.users[index].address, self.users[index].deposit_size)
        self.users[index].address = 0
        self.users[index].deposit_size = 0
        self.deletedUserPositions[self.nextDeletedUserPos] = self.users[index].pos
        self.nextDeletedUserPos += 1
        return(1:bool)
    return(0:bool)


# Submit a bet
def submitBet(index:uint256, max_height:uint256, probs:bytes, blockhashes:bytes32[], stateroots:bytes32[], prevhash:bytes32, seqnum:uint256, sig:bytes):
    # TODO: crypto verify
    # assert cryptoVerify(sig, users[index].validationCode)
    assert seqnum == self.users[index].seq
    assert prevhash == self.users[index].prevhash
    assert max_height <= block.number
    blksActive = (block.number - self.users[index].prevsubmission)
    assert blksActive >= 1
    assert self.users[index].withdrawal_height > block.number
    # Bet with max height 2**256 - 1 to start withdrawal
    if max_height == ~sub(0, 1):
        self.users[index].withdrawal_height = self.users[index].withdrawal_height
    i = 0
    while i < len(blockhashes):
        self.users[index].blockhashes[max_height - i] = blockhashes[i]
        i += 1
    i = 0
    while i < len(stateroots):
        self.users[index].stateroots[max_height - i] = stateroots[i]
        i += 1
    i = 0
    x = self.users[index].probs[max_height / 32]
    while i < len(probs):
        with h = max_height - i:
            x = (x & -(256**(h % 32)*255+1)) + getch(probs, i) * 256**(h % 32)
            if h % 32 == 0 or (i == len(probs) - 1):
                self.users[index].probs[h / 32] = x
                x = self.users[index].probs[(h-1) / 32]
        i += 1

    self.users[index].prevsubmission = block.number
    self.users[index].seq = seqnum + 1
    minChanged = max_height - max(max(len(blockhashes), len(stateroots)), len(probs)) + 1
    # log1(51, msg.gas, minChanged)
    # Incentivization
    i = min(MAX_INCENTIVIZATION_DEPTH, block.number)
    netProb = 10**9
    while i >= 1:
        H = block.number - i
        if H >= minChanged:
            # Determine the byte that was saved as the probability
            probByte = mod((self.users[index].probs[H / 32] / 256**(H % 32)), 256) or 128
            # Convert the byte to odds * 1 billion
            blockOdds = convertProbReprToOdds(probByte)
            netProb = netProb * convertOddsToProb(blockOdds) / 10**9
    
            # If there is no block at height H, then apply the scoring rule to the inverse odds
            if blockhash(H) == 0:
                profitFactor = self.scoreCorrect(10**18 / blockOdds) + self.scoreIncorrect(blockOdds)
    
            # If there is a block at height H and we guessed correctly,
            # then apply the scoring rule based on a TRUE result
            elif self.users[index].blockhashes[H] == ~blockhash(H):
                profitFactor = self.scoreCorrect(blockOdds) + self.scoreIncorrect(10**18 / blockOdds)
    
            # If there is a block but we guessed wrong on which one it is,
            # then apply just a scoring rule penalty
            else:
                profitFactor = self.scoreIncorrect(blockOdds)
    
            # Check if the state root bet that was made is correct.
            if self.users[index].stateroots[H]:
                if self.users[index].stateroots[H] == ~stateroot(H):
                    profitFactor2 = self.scoreCorrect(convertProbToOdds(netProb))
                else:
                    profitFactor2 = self.scoreIncorrect(convertProbToOdds(netProb))
            else:
                profitFactor2 = 0
            # log4(1000 * block.number + H, msg.gas, probByte, blockOdds, profitFactor, profitFactor2)
            self.users[index].profits[H] = profitFactor + profitFactor2 + self.users[index].profits[H - 1]
        i -= 1
    profit = self.users[index].deposit_size * (self.users[index].profits[block.number - 1] - self.users[index].profits[minChanged]) / SCORING_REWARD_DIVISOR * blksActive
    # log0(1000 * block.number, profit)
    # log1(1000 + H, netProb, profitFactor2)
    self.users[index].deposit_size += profit
    # log0(51, msg.gas)


    with s = ~msize():
        ~calldatacopy(s, 0, ~calldatasize())
        self.users[index].prevhash = ~sha3(s, ~calldatasize())
        # log2(1, 53, seqnum, msg.gas)
        return(1:bool)

# Interpret prob as odds in scientific notation: 5 bit exponent
# (-16….15), 3 bit mantissa (1….1.875). Convert to odds per billion
# This allows 3.125% granularity, with odds between 65536:1 against
# and 1:61440 for
macro convertProbReprToOdds($probRepr):
    2**($probRepr / 8) * (8 + $probRepr % 8) * 1907

macro convertOddsToProb($odds):
    $odds * 10**9 / (10**9 + $odds)

macro convertProbToOdds($prob):
    $prob * 10**9 / (10**9 - $prob)


# This is a simple quadratic scoring rule.
def scoreCorrect(odds:uint256):
    return odds


def scoreIncorrect(odds:uint256):
    return (0 - odds * odds / 2**30)


# Randomly select a validator using a las vegas algorithm
def const sampleValidator(seedhash:bytes32, blknumber:uint256):
    n = mod(seedhash, 2**64)
    seedhash = sha3([seedhash, blknumber]:arr)
    while 1:
        with index = seedhash % n:
            if (div(seedhash, 2**128) * MAX_DEPOSIT < 2**128 * self.users[index].deposit_size):
                if blknumber >= self.users[index].induction_height and blknumber <= self.users[index].withdrawal_height:
                    return(self.userPosToIndexMap[index])
        seedhash = sha3(seedhash)


# Getter methods 
def const getNextUserPos():
    return(self.nextUserPos:uint256)

def const getUserAtPosition(pos:uint256):
    return(self.userPosToIndexMap[pos]:uint256)

def const getUserStatus(i:uint256):
    if not self.users[i].address: # inactive
        return 0
    elif block.number < self.users[i].induction_height: # not yet inducted
        return 1
    elif block.number < self.users[i].withdrawal_height: # now inducted
        return 2
    else: # withdrawing
        return 3

def const getUserAddress(i:uint256):
    return(self.users[i].address:address)

def const getUserInductionHeight(i:uint256):
    return(self.users[i].induction_height:uint256)

def const getUserWithdrawalHeight(i:uint256):
    return(self.users[i].withdrawal_height:uint256)

def const getUserValidationCode(i:uint256):
    a = string(~ssize(ref(self.users[i].validationCode)))
    ~sloadbytes(ref(self.users[i].validationCode), a, len(a))
    return(a:str)

def const getUserSeq(i:uint256):
    return(self.users[i].seq:uint256)

def const getUserPrevhash(i:uint256):
    return(self.users[i].prevhash:bytes32)

def const getValidatorSignups():
    return(self.nextUserIndex:uint256)

def const getUserDeposit(i:uint256):
    return(self.users[i].deposit_size:uint256)
