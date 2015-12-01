data nextUser # map to storage index 0
data users[2**40](address, prevsubmission, deposit_size, time_inducted, time_withdrawn, validationCode, seq, prevhash, blockhashes[2**40], stateroots[2**40], probs[2**40])
data deletedUserIds[2**40]
data nextDeletedUserId

macro MIN_DEPOSIT: 1500 * 10**18

macro MAX_DEPOSIT: 100000 * 10**18

macro ENTER_EXIT_DELAY: 10000

macro WITHDRAWAL_WAITTIME: 10000000

macro SCORING_REWARD_DIVISOR: 2**35


# Become a validator
def join(validationCode:bytes):
    assert msg.value >= MIN_DEPOSIT and msg.value <= MAX_DEPOSIT
    if self.nextDeletedUserId:
        userIndex = self.nextDeletedUserId - 1
        self.nextDeletedUserId -= 1
    else:
        userIndex = self.nextUser
        self.nextUser += 1
    self.users[userIndex].address = msg.sender
    ~sstorebytes(ref(self.users[userIndex].validationCode), validationCode, len(validationCode))
    self.users[userIndex].deposit_size = msg.value
    self.users[userIndex].time_inducted = if(block.number, block.number + ENTER_EXIT_DELAY, 0)
    self.users[userIndex].time_withdrawn = 2**100
    self.users[userIndex].prevhash = 0
    self.users[userIndex].seq = 0
    return(userIndex:uint256)


# Queue up to leave the validator pool
def startWithdrawal(index:uint256, sig:bytes):
    if 1: # callStatic(text("withdraw"), sig):
        self.users[index].time_withdrawn = min(self.users[index].time_withdrawn, block.number + ENTER_EXIT_DELAENTER_EXIT_DELAY)
        return(1:bool)
    return(0:bool)


# Leave the validator pool
def withdraw(index:uint256):
    if self.users[index].time_withdrawn + WITHDRAWAL_WAITTIME <= block.number:
        send(self.users[index].address, self.users[index].deposit_size)
        self.users[index].address = 0
        self.users[index].deposit_size = 0
        self.deletedUserIds[self.nextDeletedUserId] = index
        self.nextDeletedUserId += 1
        return(1:bool)
    return(0:bool)


# Submit a bet
def submitBet(index:uint256, max_height:uint256, prob:bytes, blockhashes:bytes32[], stateroots:bytes32[], prevhash:bytes, seqnum:uint256, sig:bytes):
    # TODO: crypto verify
    # assert cryptoVerify(sig, users[index].validationCode)
    assert prevhash == self.users[index].prevhash
    assert max_height <= block.number
    assert self.users[index].prevsubmission <= block.number - 1
    i = 0
    while i < len(newHashes):
        self.users[index].blockhashes[max_height - i] = blockhashes[i]
        i += 1
    i = 0
    while i < len(newStates):
        self.users[index].stateroots[max_height - i] = stateroots[i]
        i += 1
    i = 0
    x = self.users[index].probs[max_height / 32]
    while i < len(newProbs):
        with h = max_height - i:
            x = x & -(256**(h % 32)*255) + getch(probs, i)
            if h % 32 == 0:
                self.users[index].probs[h] = x
        i += 1
    self.users[index].prevsubmission = block.number
    return(1:bool)

# Interpret prob as odds in scientific notation: 5 bit exponent
# (-16….15), 3 bit mantissa (1….1.875). Convert to odds per 2**-30
# This allows 3.125% granularity, with odds between 65536:1 against
# and 1:61440 for
macro convertProbReprToOdds($probRepr):
    2**($probRepr / 8) * (8 + $probRepr % 8) * 2048

macro convertOddsToProb($odds):
    $odds * 2**30 / (2**30 + $odds)

macro convertProbToOdds($prob):
    $prob * 2**30 / (2**30 - $prob)


# Apply the scoring rule on users' bets
def incentivize(uint index, uint[] recentProbs, bytes32[] recentProbHashes):
    i = maxIncentivizationDepth
    netProb = 2**30
    while i >= 1:
        blockOdds = convertProbReprToOdds(self.users[index].probs[H])
        netProb = netProb * convertOddsToProb(blockOdds) / 2**30
        H = block.number - i

        # If there is no block at height H, then apply the scoring rule
        if blockhash(H) == 0:
            profitFactor = self.scoreCorrect(2**60 / blockOdds) + self.scoreIncorrect(blockOdds)

        # If there is a block at height H and we guessed correctly,
        # then apply the scoring rule based on a TRUE result
        elif self.users[index].blockhashes[H] == ~blockhash(H):
            profitFactor = self.scoreCorrect(blockOdds) + self.scoreIncorrect(2**60 / blockOdds)

        # If there is a block but we guessed wrong on which one it is,
        # then apply just a scoring rule penalty
        else:
            profitFactor = self.scoreIncorrect(blockOdds)

        # Check if the state root bet that was made is correct.
        if self.users[index].stateroots[H]:
            if self.users[index].stateroots[H] == ~stateroot(H):
                profitFactor += self.scoreCorrect(convertProbToOdds(netProb))
            else:
                profitFactor += self.scoreIncorrect(convertProbToOdds(netProb))
        
        self.users[index].deposit_size += self.users[index].deposit_size * profitFactor / SCORING_REWARD_DIVISOR
        i -= 1


# This is a simple quadratic scoring rule.
def scoreCorrect(odds:uint256):
    return odds


def scoreIncorrect(odds:uint256):
    return -odds * odds / 2**30


# Randomly select a validator using a las vegas algorithm
def const sampleValidator(seedhash:bytes32, blknumber:uint256):
    n = seedhash % 2**64
    seedhash = sha3([seedhash, blknumber]:arr)
    while 1:
        with index = seedhash % n:
            if (div(seedhash, 2**128) * MAX_DEPOSIT < 2**128 * self.users[index].deposit_size):
                if blknumber >= self.users[index].time_inducted and blknumber <= self.users[index].time_withdrawn:
                    return(index)
        seedhash = sha3(seedhash)


# Getter methods 
def const getNextUserId():
    return self.nextUser

def const getUserStatus(i:uint256):
    if not self.users[i].address: # inactive
        return 0
    elif block.number < self.users[i].time_inducted: # not yet inducted
        return 1
    elif block.number < self.users[i].time_withdrawn: # now inducted
        return 2
    else: # withdrawing
        return 3

def const getUserAddress(i:uint256):
    return(self.users[i].address:address)

def const getUserValidationCode(i:uint256):
    a = string(~ssize(ref(self.users[i].validationCode)))
    ~sloadbytes(ref(self.users[i].validationCode), a, len(a))
    return(a:str)

def const getSeq(i:uint256):
    return(self.users[i].seq:uint256)

def const getPrevhash(i:uint256):
    return(self.users[i].prevhash:bytes32)
