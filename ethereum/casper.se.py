data nextUserPos # map to storage index 0
data users[2**50](address, prevsubmission, deposit_size, induction_height, withdrawal_height, validationCode, seq, prevhash, pos, blockhashes[2**50], stateroots[2**50], probs[2**50], profits[2**50])
data deletedUserPositions[2**50]
data nextDeletedUserPos
data userPosToIndexMap[2**50]
data nextUserIndex
data activeValidators

macro MIN_DEPOSIT: 1500 * 10**18

macro MAX_DEPOSIT: 60000 * 10**18

macro ENTER_EXIT_DELAY: 80

macro WITHDRAWAL_WAITTIME: 20

macro SCORING_REWARD_DIVISOR: 10**17 # 300000 * 10**9 * 300000 * 10**9 / 10**12 / 10**17 ~= 1, so a max probability bet gone wrong is a full slashing

macro MAX_INCENTIVIZATION_DEPTH: 160

macro PROFIT_PACKING_NUM: 4

macro PROFIT_PACKING_BYTES: 8 

macro maskinclude($top, $bottom):
    256**$top - 256**$bottom

macro maskexclude($top, $bottom):
    ~not(256**$top - 256**$bottom)

macro getProfit($user, $block):
    mod(div(self.users[$user].profits[div($block, PROFIT_PACKING_NUM)], 256**(PROFIT_PACKING_BYTES * mod($block, PROFIT_PACKING_NUM))), 256**PROFIT_PACKING_BYTES)

macro updateProfit($prevProfitBlock, $pos, $val):
    (maskexclude($pos * PROFIT_PACKING_BYTES + PROFIT_PACKING_BYTES, $pos * PROFIT_PACKING_BYTES) & $prevProfitBlock) + $val * 256**(PROFIT_PACKING_BYTES * $pos)


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
    # log(20, ~ssize(self.users[userIndex].validationCode))
    self.users[userIndex].deposit_size = msg.value
    self.users[userIndex].induction_height = if(block.number, block.number + ENTER_EXIT_DELAY, 0)
    self.users[userIndex].withdrawal_height = 2**100
    log2(32, userIndex, userPos, self.users[userIndex].deposit_size)
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
    # Compute the signature hash
    _calldata = string(~calldatasize())
    ~calldatacopy(_calldata, 0, ~calldatasize())
    signing_hash = ~sha3(_calldata, ~calldatasize() - 32 - ceil32(len(sig)))
    self.users[index].prevhash = ~sha3(_calldata, ~calldatasize())
    # Check the sig against the user validation code
    user_validation_code = string(~ssize(ref(self.users[index].validationCode)))
    ~sloadbytes(ref(self.users[index].validationCode), user_validation_code, len(user_validation_code))
    sig_verified = 0
    with L = len(sig):
        sig[-1] = signing_hash
        ~callstatic(msg.gas - 20000, user_validation_code, len(user_validation_code), sig - 32, L + 32, ref(sig_verified), 32)
        sig[-1] = L
    assert sig_verified == 1
    # Bet with max height 2**256 - 1 to start withdrawal
    if max_height == ~sub(0, 1):
        self.users[index].withdrawal_height = block.number
        self.users[index].prevsubmission = block.number
        self.users[index].seq = seqnum + 1
        return True
    i = 0
    while i < len(blockhashes):
        self.users[index].blockhashes[max_height - i] = blockhashes[i]
        i += 1
    i = 0
    while i < len(stateroots):
        self.users[index].stateroots[max_height - i] = stateroots[i]
        i += 1
    # Update probabilities; paste the probs into the self.users[index].probs
    # array at the correct positions, assuming the probs array stores probs
    # in groups of 32
    h = max_height + 1
    i = 0
    while i < len(probs):
        with top = (h % 32) or 32:
            with bottom = max(top - len(probs) + i, 0):
                x = (self.users[index].probs[(h - 1) / 32] & maskexclude(top, bottom)) + (~mload(probs + i - 32 + top) & maskinclude(top, bottom))
                self.users[index].probs[(h - 1) / 32] = x
                h -= top
                i += top

    self.users[index].prevsubmission = block.number
    self.users[index].seq = seqnum + 1
    minChanged = max_height - max(max(len(blockhashes), len(stateroots)), len(probs)) + 1
    # Incentivization
    with H = max(max(self.users[index].induction_height, block.number - MAX_INCENTIVIZATION_DEPTH), minChanged):
        netProb = 10**9
        CURPROFIT = getProfit(index, H - 1)
        with PROFITBLOCK = self.users[index].profits[div(H, PROFIT_PACKING_NUM)]:
            while H <= max_height:
                # Determine the byte that was saved as the probability
                # Convert the byte to odds * 1 billion
                with blockOdds = convertProbReprToOdds(getch(probs, max_height - H)): # mod((self.users[index].probs[H / 32] / 256**(H % 32)), 256) or 128
                    netProb = netProb * convertOddsToProb(blockOdds) / 10**9
            
                    if blockOdds >= 10**9 and ~blockhash(H):
                        profitFactor = if(self.users[index].blockhashes[H] == ~blockhash(H), scoreCorrect(blockOdds), scoreIncorrect(blockOdds))
                    else:
                        profitFactor = if(~blockhash(H), scoreIncorrect(10**18 / blockOdds), scoreCorrect(10**18 / blockOdds))
            
                    # Check if the state root bet that was made is correct.
                    if self.users[index].stateroots[H]:
                        if self.users[index].stateroots[H] == ~stateroot(H):
                            profitFactor2 = scoreCorrect(convertProbToOdds(netProb))
                        else:
                            profitFactor2 = scoreIncorrect(convertProbToOdds(netProb))
                    else:
                        profitFactor2 = 0
                    # Update the profit counter
                    CURPROFIT += profitFactor2 + profitFactor
                    PROFITBLOCK = updateProfit(PROFITBLOCK, mod(H, PROFIT_PACKING_NUM), CURPROFIT)
                    if (mod(H, PROFIT_PACKING_NUM) == (PROFIT_PACKING_NUM - 1) or H == max_height):
                        self.users[index].profits[div(H, PROFIT_PACKING_NUM)] = PROFITBLOCK
                        PROFITBLOCK = self.users[index].profits[(H + 1) / PROFIT_PACKING_NUM]
                    # self.users[index].profits[H] = profitFactor + profitFactor2 + self.users[index].profits[H - 1]
                    # log4(1000 * block.number + H, msg.gas,blockOdds, profitFactor, profitFactor2, self.users[index].profits[H])
                    H += 1
    profit = self.users[index].deposit_size * (CURPROFIT - getProfit(index, H - MAX_INCENTIVIZATION_DEPTH)) / SCORING_REWARD_DIVISOR * blksActive
    # Optional verification code
    # h = max_height
    # while h >= 0:
    #     log0(10000 + h, getProfit(index, h))
    #     h -= 1
    # log1(51, 54, profit)
    # log0(1000 * block.number, profit)
    # log1(1000 + H, netProb, profitFactor2)
    if profit < 0:
        log4(499, profit, getProfit(index, MAX_INCENTIVIZATION_DEPTH), CURPROFIT, SCORING_REWARD_DIVISOR, blksActive) 
    self.users[index].deposit_size = max(0, self.users[index].deposit_size + profit)
    log4(500 + index, seqnum, len(probs), len(blockhashes), len(stateroots), txexecgas() - msg.gas)
    return(1:bool)

# Interpret prob as odds in scientific notation: 5 bit exponent
# (-16….15), 3 bit mantissa (1….1.875). Convert to odds per billion
# This allows 3.125% granularity, with odds between 65536:1 against
# and 1:61440 for
macro convertProbReprToOdds($probRepr):
    2**(($probRepr + 5) / 7) * (7 + ($probRepr + 5) % 7) * 272

macro convertOddsToProb($odds):
    $odds * 10**9 / (10**9 + $odds)

macro convertProbToOdds($prob):
    $prob * 10**9 / (10**9 - $prob)


# This is a simple quadratic scoring rule.
macro scoreCorrect($odds):
    $odds / 1000


macro scoreIncorrect($odds):
    (0 - $odds * $odds / 10**12)


# Randomly select a validator using a las vegas algorithm
def const sampleValidator(seedhash:bytes32, blknumber:uint256):
    n = mod(seedhash, 2**64)
    seedhash = sha3([seedhash, blknumber]:arr)
    while 1:
        with index = mod(seedhash, n):
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
