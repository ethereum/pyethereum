data nextUserPos # map to storage index 0
data users[2**50](address, orig_deposit_size, induction_height, withdrawal_height, validationCode, pos, blockhashes[2**50], stateroots[2**50], probs[2**50], profits[2**50], basicinfo)
data deletedUserPositions[2**50]
data nextDeletedUserPos
data userPosToIndexMap[2**50]
data nextUserIndex
data activeValidators

macro SEQ_POS: 0
macro PREVHASH_POS: 1
macro DEPOSIT_SIZE_POS: 2
macro BET_MAXHEIGHT_POS: 3
macro PROFITS_PROCESSED_TO_POS: 4

macro MIN_DEPOSIT: 1500 * 10**18

macro MAX_DEPOSIT: 60000 * 10**18

macro ENTER_EXIT_DELAY: 110

macro WITHDRAWAL_WAITTIME: 20

macro SCORING_REWARD_DIVISOR: 10**16 # 300000 * 10**9 * 300000 * 10**9 / 10**13 / 10**16 ~= 1, so a max probability bet gone wrong is a full slashing

macro INCENTIVIZATION_EMA_COEFF: 160

macro PROFIT_PACKING_NUM: 32
macro PPN: 32

macro PROFIT_PACKING_BYTES: 10
macro PPB: 10

macro VALIDATOR_ROUNDS: 6

macro maskinclude($top, $bottom):
    256**$top - 256**$bottom

macro maskexclude($top, $bottom):
    ~not(256**$top - 256**$bottom)


macro newArrayChunk($bytesPerValue, $valuesPerChunk):
    string($bytesPerValue * $valuesPerChunk)

macro(80) loadArrayChunk($bytesPerValue, $valuesPerChunk, $storearray, $memaddr, $index):
    ~sloadbytes(ref($storearray[div($index, $valuesPerChunk)]), $memaddr, $bytesPerValue * $valuesPerChunk)

macro(80) loadArrayValue($bytesPerValue, $valuesPerChunk, $memaddr, $index):
    mod(~mload($memaddr + $bytesPerValue * mod($index, $valuesPerChunk) - 32 + $bytesPerValue), 256**$bytesPerValue)

macro(80) saveArrayValue($bytesPerValue, $valuesPerChunk, $memaddr, $index, $value):
    mcopy_small2($memaddr + $bytesPerValue * mod($index, $valuesPerChunk) - 32 + $bytesPerValue, $value, $bytesPerValue)

macro(80) mcopy_small2($to, $frm, $bytes):
    ~mstore($to, (~mload($to) & sub(0, 256**$bytes)) + ($frm & (256**$bytes - 1)))

macro(80) saveArrayChunk($bytesPerValue, $valuesPerChunk, $storearray, $memaddr, $index):
    ~sstorebytes(ref($storearray[div($index, $valuesPerChunk)]), $memaddr, $bytesPerValue * $valuesPerChunk)

macro mcopy_small($to, $frm, $bytes):
    ~mstore($to, (~mload($to) & sub(0, 256**$bytes)) + ($frm & (256**$bytes - 1)))

event Reward(blockNumber, profit, blockdiff, totProfit, bmh)
event ProcessingBet(bettor, seq, curBlock, prevBlock, maxHeightProcessed, max_height)
event RecordingTotProfit(bettor, block, totProfit)
event Joined(userIndex)

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
    basicinfo = array(10)
    ~sloadbytes(ref(self.users[userIndex].basicinfo), basicinfo, 320)
    basicinfo[DEPOSIT_SIZE_POS] = msg.value
    self.users[userIndex].orig_deposit_size = msg.value
    self.users[userIndex].induction_height = if(block.number, block.number + ENTER_EXIT_DELAY, 0)
    self.users[userIndex].withdrawal_height = 2**100
    ~sstorebytes(ref(self.users[userIndex].basicinfo), basicinfo, 320)
    return(userIndex:uint256)


# Leave the validator pool
def withdraw(index:uint256):
    if self.users[index].withdrawal_height + WITHDRAWAL_WAITTIME <= block.number:
        basicinfo = array(10)
        ~sloadbytes(ref(self.users[index].basicinfo), basicinfo, 320)
        send(self.users[index].address, basicinfo[DEPOSIT_SIZE_POS])
        self.users[index].address = 0
        basicinfo[DEPOSIT_SIZE_POS] = 0
        self.deletedUserPositions[self.nextDeletedUserPos] = self.users[index].pos
        self.nextDeletedUserPos += 1
        ~sstorebytes(ref(self.users[index].basicinfo), basicinfo, 320)
        return(1:bool)
    return(0:bool)


# Submit a bet
def submitBet(index:uint256, max_height:uint256, probs:bytes, blockhashes:bytes32[], stateroots:bytes32[], prevhash:bytes32, seqnum:uint256, sig:bytes):
    # if seqnum != self.users[index].seq:
    #     log3(20, index, block.number, seqnum, self.users[index].seq)
    basicinfo = array(10)
    ~sloadbytes(ref(self.users[index].basicinfo), basicinfo, 320)
    assert seqnum == basicinfo[SEQ_POS]
    assert prevhash == basicinfo[PREVHASH_POS]
    assert max_height <= block.number
    assert self.users[index].withdrawal_height > block.number
    assert len(probs) >= len(blockhashes)
    assert len(probs) >= len(stateroots)
    # Compute the signature hash
    _calldata = string(~calldatasize())
    ~calldatacopy(_calldata, 0, ~calldatasize())
    signing_hash = ~sha3(_calldata, ~calldatasize() - 32 - ceil32(len(sig)))
    basicinfo[PREVHASH_POS] = ~sha3(_calldata, ~calldatasize())
    basicinfo[SEQ_POS] = seqnum + 1
    # Check the sig against the user validation code
    user_validation_code = string(~ssize(ref(self.users[index].validationCode)))
    ~sloadbytes(ref(self.users[index].validationCode), user_validation_code, len(user_validation_code))
    sig_verified = 0
    with L = len(sig):
        sig[-1] = signing_hash
        ~callstatic(msg.gas - 20000, user_validation_code, len(user_validation_code), sig - 32, L + 32, ref(sig_verified), 32)
        sig[-1] = L
    assert sig_verified == 1
    # Process profits from last bet
    userBalance = basicinfo[DEPOSIT_SIZE_POS]
    with bmh = basicinfo[BET_MAXHEIGHT_POS]:
        # log(type=ProcessingBet, index, seqnum, block.number, pbp, bmh, max_height)
        with CURPROFITBLOCK = newArrayChunk(PPB, PPN):
            loadArrayChunk(PPB, PPN, self.users[index].profits, CURPROFITBLOCK, bmh)
            with profit = loadArrayValue(PPB, PPN, CURPROFITBLOCK, bmh):
                with blockdiff = block.number - basicinfo[PROFITS_PROCESSED_TO_POS]:
                    with totProfit = 0:
                        with i = 0:
                            while i < blockdiff:
                                totProfit += profit
                                profit = profit * (INCENTIVIZATION_EMA_COEFF - 1) / INCENTIVIZATION_EMA_COEFF
                                i += 1
                        userBalance = max(0, userBalance + userBalance * totProfit / SCORING_REWARD_DIVISOR)
                        # log(type=Reward, i, profit, blockdiff, totProfit, bmh)
        basicinfo[BET_MAXHEIGHT_POS] = max(bmh, max_height)
    basicinfo[PROFITS_PROCESSED_TO_POS] = block.number
    basicinfo[DEPOSIT_SIZE_POS] = userBalance
    # Bet with max height 2**256 - 1 to start withdrawal
    if max_height == ~sub(0, 1):
        self.users[index].withdrawal_height = block.number
        ~sstorebytes(ref(self.users[index].basicinfo), basicinfo, 320)
        return(1:bool)
    # Update blockhashes, storing blockhash correctness info in groups of 32
    with i = 0:
        with v = self.users[index].blockhashes[max_height / 32]:
            while i < len(blockhashes):
                with h = max_height - i:
                    byte = not(not(~blockhash(h))) * 2 + (blockhashes[i] == ~blockhash(h))
                    with offset = h % 32:
                        v = (v & maskexclude(offset + 1, offset)) + byte * 256**offset
                        if offset == 0 or i == len(blockhashes) - 1:
                            self.users[index].blockhashes[h / 32] = v
                            v = self.users[index].blockhashes[(h / 32) - 1]
                i += 1
    # Update stateroots, storing stateroot correctness info in groups of 32
    with i = 0:
        with v = self.users[index].stateroots[max_height / 32]:
            while i < len(stateroots):
                with h = max_height - i:
                    byte = not(not(~stateroot(h))) * 2 + (stateroots[i] == ~stateroot(h))
                    with offset = h % 32:
                        v = (v & maskexclude(offset + 1, offset)) + byte * 256**offset
                        if offset == 0 or i == len(stateroots) - 1:
                            self.users[index].stateroots[h / 32] = v
                            v = self.users[index].stateroots[(h / 32) - 1]
                i += 1
    # Update probabilities; paste the probs into the self.users[index].probs
    # array at the correct positions, assuming the probs array stores probs
    # in groups of 32
    with h = max_height + 1:
        with i = 0:
            while i < len(probs):
                with top = (h % 32) or 32:
                    with bottom = max(top - len(probs) + i, 0):
                        x = (self.users[index].probs[(h - 1) / 32] & maskexclude(top, bottom)) + (~mload(probs + i - 32 + top) & maskinclude(top, bottom))
                        self.users[index].probs[(h - 1) / 32] = x
                        h -= top
                        i += top

    minChanged = max_height - max(max(len(blockhashes), len(stateroots)), len(probs)) + 1
    # Incentivization
    with H = max(self.users[index].induction_height, minChanged):
        # log(type=ProgressWithDataArray, 1, [minChanged, H, max_height, len(blockhashes), len(stateroots), len(probs)])
        netProb = 10**9
        with PROFITBLOCK = newArrayChunk(PPB, PPN):
            loadArrayChunk(PPB, PPN, self.users[index].profits, PROFITBLOCK, H - 1)
            CURPROFIT = loadArrayValue(PPB, PPN, PROFITBLOCK, H - 1)
            if H % PROFIT_PACKING_NUM == 0:
                loadArrayChunk(PPB, PPN, self.users[index].profits, PROFITBLOCK, H)
            # log(type=ProgressWithData, 2, H, max_height)
            while H <= max_height:
                # Determine the byte that was saved as the probability
                # Convert the byte to odds * 1 billion
                with blockOdds = convertProbReprToOdds(getch(probs, max_height - H)): # mod((self.users[index].probs[H / 32] / 256**(H % 32)), 256) or 128
                    # log(type=Progress, 3)
                    blockHashInfo = mod(div(self.users[index].blockhashes[H / 32], 256**(H % 32)), 256)
            
                    if blockOdds >= 10**9 and blockHashInfo >= 2:
                        profitFactor = if(blockHashInfo % 2, scoreCorrect(blockOdds), scoreIncorrect(blockOdds))
                    else:
                        profitFactor = if(blockHashInfo % 2 or blockHashInfo == 0, scoreCorrect(10**18 / blockOdds), scoreIncorrect(10**18 / blockOdds))

                    if profitFactor < 0:
                        log(type=BlockLoss, blockOdds, profitFactor)
            
                    # Check if the state root bet that was made is correct.
                    # log(type=Progress, 4)
                    if netProb:
                        stateRootInfo = mod(div(self.users[index].stateroots[H / 32], 256**(H % 32)), 256)
                        netProb = netProb * convertOddsToProb(blockOdds) / 10**9
                        if stateRootInfo >= 2:
                            if stateRootInfo % 2:
                                profitFactor += scoreCorrect(convertProbToOdds(netProb))
                            else:
                                negs = scoreIncorrect(convertProbToOdds(netProb))
                                log(type=StateLoss, convertProbToOdds(netProb), profitFactor, H)
                                profitFactor += negs
                        else:
                            netProb = 0
                    # Update the profit counter
                    CURPROFIT = (CURPROFIT * (INCENTIVIZATION_EMA_COEFF - 1) + profitFactor) / INCENTIVIZATION_EMA_COEFF
                    # log2(4, H, profitFactor2 + profitFactor, CURPROFIT)
                    saveArrayValue(PPB, PPN, PROFITBLOCK, H, CURPROFIT)
                    # log(type=DebugPBForBlock, PROFITBLOCK, H, CURPROFIT)
                    if (mod(H, PROFIT_PACKING_NUM) == (PROFIT_PACKING_NUM - 1) or H == max_height):
                        saveArrayChunk(PPB, PPN, self.users[index].profits, PROFITBLOCK, H)
                        loadArrayChunk(PPB, PPN, self.users[index].profits, PROFITBLOCK, H + 1)
                    # self.users[index].profits[H] = profitFactor + profitFactor2 + self.users[index].profits[H - 1]
                    # log3(1000 + H, msg.gas, blockOdds, profitFactor, profitFactor2)
                    # log3(1001, block.number, H, blockHashInfo, stateRootInfo)
                    H += 1
            # log0(100, profit)
            # Optional verification code
            # h = max_height
            # while h >= 0:
            #     log0(10000 + h, getProfit(index, h))
            #     h -= 1
            # log1(51, 54, profit)
            # log0(1000 * block.number, profit)
            # log1(1000 + H, netProb, profitFactor2)
            # log3(500 + index, block.number, profitFactor + profitFactor2, CURPROFIT, prevProfit)
            loadArrayChunk(PPB, PPN, self.users[index].profits, PROFITBLOCK, H - 1)
            # log(type=DebugPB, PROFITBLOCK)
            # log(type=RecordingTotProfit, index, H, loadArrayValue(PPB, PPN, PROFITBLOCK, H - 1))
            # log4(500 + index, seqnum, len(probs), len(blockhashes), len(stateroots), txexecgas() - msg.gas)
            ~sstorebytes(ref(self.users[index].basicinfo), basicinfo, 320)
            return(1:bool)

event DebugPB(pblock:str)
event DebugPBForBlock(pblock:str, blocknum, curprofit)
event Progress(stage)
event ProgressWithData(stage, h, mh)
event ProgressWithDataArray(stage, data:arr)
event BlockLoss(odds, loss)
event StateLoss(odds, loss, height)

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
    $odds / 10000


macro scoreIncorrect($odds):
    (0 - $odds * $odds / 10**13)


# Randomly select a validator using a las vegas algorithm
def const sampleValidator(orig_seedhash:bytes32, blknumber:uint256):
    n = mod(orig_seedhash, 2**64)
    seedhash = sha3([orig_seedhash, blknumber]:arr)
    while 1:
        with index = self.userPosToIndexMap[mod(seedhash, n)]:
            if (div(seedhash, 2**128) * MAX_DEPOSIT / 2**128 < self.users[index].orig_deposit_size):
                if blknumber >= self.users[index].induction_height and blknumber <= self.users[index].withdrawal_height:
                    return(self.userPosToIndexMap[index])
        seedhash = sha3(seedhash)


# Getter methods 
def const getNextUserPos():
    return(self.nextUserPos:uint256)

def const getUserAtPosition(pos:uint256):
    return(self.userPosToIndexMap[pos]:uint256)

def const getUserStatus(index:uint256):
    if not self.users[index].address: # inactive
        return 0
    elif block.number < self.users[index].induction_height: # not yet inducted
        return 1
    elif block.number < self.users[index].withdrawal_height: # now inducted
        return 2
    else: # withdrawing
        return 3

def const getUserAddress(index:uint256):
    return(self.users[index].address:address)

def const getUserInductionHeight(index:uint256):
    return(self.users[index].induction_height:uint256)

def const getUserWithdrawalHeight(index:uint256):
    return(self.users[index].withdrawal_height:uint256)

def const getUserValidationCode(index:uint256):
    a = string(~ssize(ref(self.users[index].validationCode)))
    ~sloadbytes(ref(self.users[index].validationCode), a, len(a))
    return(a:str)

def const getUserSeq(index:uint256):
    basicinfo = array(10)
    ~sloadbytes(ref(self.users[index].basicinfo), basicinfo, 320)
    return(basicinfo[SEQ_POS]:uint256)

def const getUserPrevhash(index:uint256):
    basicinfo = array(10)
    ~sloadbytes(ref(self.users[index].basicinfo), basicinfo, 320)
    return(basicinfo[PREVHASH_POS]:bytes32)

def const getValidatorSignups():
    return(self.nextUserIndex:uint256)

def const getUserDeposit(index:uint256):
    basicinfo = array(10)
    ~sloadbytes(ref(self.users[index].basicinfo), basicinfo, 320)
    return(basicinfo[DEPOSIT_SIZE_POS]:uint256)
