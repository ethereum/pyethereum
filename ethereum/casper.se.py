data nextUserIndex  # map to storage index 0
data users[2**50](address, orig_deposit_size, induction_height, withdrawal_height, validationCode, blockhashes[2**50], stateroots[2**50], probs[2**50], profits[2**50], basicinfo, max_seq, counter)
data deletedUserIndices[2**50]
data nextDeletedUserIndex
data numActiveValidators
data nextCounter
data slashed[]

# Interpret prob as odds in scientific notation: 5 bit exponent
# (-16….15), 3 bit mantissa (1….1.875). Convert to odds per billion
# This allows 3.125% granularity, with odds between 65536:1 against
# and 1:61440 for
macro convertProbReprToOdds($probRepr):
    2**(($probRepr) / 4) * (4 + ($probRepr) % 4) * 99 / 1700

macro convertOddsToProb($odds):
    $odds * 10**9 / (10**9 + $odds)

macro convertProbToOdds($prob):
    $prob * 10**9 / (10**9 - $prob)

# This is a simple quadratic scoring rule.
macro scoreCorrect($odds):
    $odds / 10000

macro scoreIncorrect($odds):
    (0 - $odds * $odds / 10**13)

macro SEQ_POS: 0
macro PREVHASH_POS: 1
macro DEPOSIT_SIZE_POS: 2
macro BET_MAXHEIGHT_POS: 3
macro PROFITS_PROCESSED_TO_POS: 4

macro MAX_ODDS: 2**29

macro VALIDATOR_ROUNDS: 5

macro BLKTIME: 7500 # milliseconds

macro INCENTIVIZATION_EMA_COEFF: 200

# VALIDATOR_ROUNDS of maximum slashing = 100% loss
# Currently: 62.0 parts per billion theoretical maximum return per block, 29.8% theoretical maximum annual reward
macro SCORING_REWARD_DIVISOR: (MAX_ODDS * 10**9) * (MAX_ODDS * 10**9) / 10**13 / INCENTIVIZATION_EMA_COEFF * VALIDATOR_ROUNDS
macro MIN_BET_BYTE: 12
macro MAX_BET_BYTE: 244
macro PER_BLOCK_BASE_COST: 45 # parts per billion: 17.25% fixed annual penalty
# Net interest rate: 7.45% theoretical maximum

macro MIN_DEPOSIT: 1250 * 10**18

macro MAX_DEPOSIT: 200000 * 10**18

macro MAX_VALIDATORS: 100

macro ENTER_EXIT_DELAY: 110

macro MAXBETLENGTH: 10000

macro WRAPLENGTH: 40320

macro ETHER: 50

macro RLPGETBYTES32: 8

macro RLPGETSTRING: 9

macro MAX_VALIDATION_DURATION: 1000000 # number of blocks

macro EXCESS_VALIDATION_TAX: 100 # parts per billion per block

macro WITHDRAWAL_WAITTIME: 20

macro PROFIT_PACKING_NUM: 32
macro PPN: 32

macro PROFIT_PACKING_BYTES: 10
macro PPB: 10

macro ADDRBYTES: 23

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

event Reward(blockNumber, profit, blockdiff, totProfit, totLoss, bmh)
event ProcessingBet(bettor, seq, curBlock, prevBlock, maxHeightProcessed, max_height)
event RecordingTotProfit(bettor, block, totProfit)
event Joined(userIndex)
event BetSlashed(userIndex:uint256, bet1:str, bet2:str)
event BlockSlashed(userIndex:uint256, bet1:str, bet2:str)

def const getMinDeposit():
    return self.numActiveValidators

# Become a validator
def join(validationCode:bytes):
    min_deposit = MIN_DEPOSIT * MAX_VALIDATORS / (MAX_VALIDATORS - self.numActiveValidators)
    assert self.numActiveValidators < MAX_VALIDATORS and msg.value >= min_deposit and msg.value <= MAX_DEPOSIT
    if self.nextDeletedUserIndex:
        userIndex = self.deletedUserIndices[self.nextDeletedUserIndex - 1]
        self.nextDeletedUserIndex -= 1
    else:
        userIndex = self.nextUserIndex
        self.nextUserIndex = userIndex + 1
    self.users[userIndex].address = msg.sender
    self.users[userIndex].counter = self.nextCounter
    self.nextCounter += 1
    ~sstorebytes(ref(self.users[userIndex].validationCode), validationCode, len(validationCode))
    # log(20, ~ssize(self.users[userIndex].validationCode))
    basicinfo = array(10)
    basicinfo[DEPOSIT_SIZE_POS] = msg.value
    self.users[userIndex].orig_deposit_size = msg.value
    self.users[userIndex].induction_height = if(block.number, block.number + ENTER_EXIT_DELAY, 0)
    self.users[userIndex].withdrawal_height = 2**100
    self.numActiveValidators += 1
    ~sstorebytes(ref(self.users[userIndex].basicinfo), basicinfo, 320)
    return(userIndex:uint256)


# Leave the validator pool
def withdraw(index:uint256):
    if self.users[index].withdrawal_height + WITHDRAWAL_WAITTIME <= block.number:
        # Load the validator's info
        basicinfo = array(10)
        ~sloadbytes(ref(self.users[index].basicinfo), basicinfo, 320)
        send(self.users[index].address, basicinfo[DEPOSIT_SIZE_POS])
        self.users[index].address = 0
        basicinfo[DEPOSIT_SIZE_POS] = 0
        self.deletedUserIndices[self.nextDeletedUserIndex] = index
        self.nextDeletedUserIndex += 1
        self.numActiveValidators -= 1
        ~sstorebytes(ref(self.users[index].basicinfo), basicinfo, 320)
        return(1:bool)
    return(0:bool)

event LogPre(hash:bytes32)
event LogPost(hash:bytes32)
event SubmitBet(seq, prevhash:bytes32, index, stateroot_prob_from:bytes1)
event ExcessRewardEvent(index, profit, blockdiff, totProfit, newBalance)

# Submit a bet
def submitBet(index:uint256, max_height:uint256, probs:bytes, blockhashes:bytes32[], stateroots:bytes32[], stateroot_prob_from:bytes1, prevhash:bytes32, seqnum:uint256, sig:bytes):
    # Load basic user information
    basicinfo = array(10)
    ~sloadbytes(ref(self.users[index].basicinfo), basicinfo, 320)
    # log(type=SubmitBet, basicinfo[SEQ_POS], basicinfo[PREVHASH_POS], index, stateroot_prob_from)
    # Compute the signature hash
    _calldata = string(~calldatasize())
    ~calldatacopy(_calldata, 0, ~calldatasize())
    signing_hash = ~sha3(_calldata, ~calldatasize() - 32 - ceil32(len(sig)))
    # Check the sig against the user validation code
    user_validation_code = string(~ssize(ref(self.users[index].validationCode)))
    ~sloadbytes(ref(self.users[index].validationCode), user_validation_code, len(user_validation_code))
    sig_verified = 0
    with L = len(sig):
        sig[-1] = signing_hash
        ~callstatic(msg.gas - 20000, user_validation_code, len(user_validation_code), sig - 32, L + 32, ref(sig_verified), 32)
        sig[-1] = L
    assert sig_verified == 1
    # Check sequence number
    if seqnum != basicinfo[SEQ_POS] or prevhash != basicinfo[PREVHASH_POS]:
        # If someone submits a higher-seq bet, register that it has been
        # submitted; we will later force the user to supply all bets up
        # to and including this seq in order to withdraw
        self.users[index].max_seq = max(self.users[index].max_seq, seqnum)
        return(0:bool)
    # Check basic validity
    assert max_height <= block.number
    assert self.users[index].withdrawal_height > block.number
    assert len(probs) >= len(blockhashes)
    assert len(probs) >= len(stateroots)
    # Set seq and prevhash
    basicinfo[PREVHASH_POS] = ~sha3(_calldata, ~calldatasize())
    basicinfo[SEQ_POS] = seqnum + 1
    # log(type=ProcessingBet, index, seqnum, 1, 2, 3, 4)
    # Process profits from last bet
    userBalance = basicinfo[DEPOSIT_SIZE_POS]
    with bmh = basicinfo[BET_MAXHEIGHT_POS]:
        with CURPROFITBLOCK = newArrayChunk(PPB, PPN):
            loadArrayChunk(PPB, PPN, self.users[index].profits, CURPROFITBLOCK, mod(bmh, WRAPLENGTH))
            with profit = ~signextend(PPB-1, loadArrayValue(PPB, PPN, CURPROFITBLOCK, mod(bmh, WRAPLENGTH))):
                with blockdiff = block.number - basicinfo[PROFITS_PROCESSED_TO_POS]:
                    with totProfit = 0:
                        with i = 0:
                            while i < blockdiff:
                                totProfit += profit
                                profit = profit * (INCENTIVIZATION_EMA_COEFF - 1) / INCENTIVIZATION_EMA_COEFF
                                i += 1
                        userBalance = max(0, userBalance + userBalance * totProfit / SCORING_REWARD_DIVISOR - userBalance * blockdiff * PER_BLOCK_BASE_COST / 10**9)
                        # log(type=Reward, i, profit, blockdiff, userBalance * totProfit / SCORING_REWARD_DIVISOR, userBalance * blockdiff * PER_BLOCK_BASE_COST / 10**9, userBalance)
                        if userBalance > 3000 * 10**18:
                            log(type=ExcessRewardEvent, i, profit, blockdiff, totProfit, userBalance)
        # Update the maximum height of the previous bet, profits and the user deposit size
        basicinfo[BET_MAXHEIGHT_POS] = max(bmh, max_height)
        basicinfo[PROFITS_PROCESSED_TO_POS] = block.number
        basicinfo[DEPOSIT_SIZE_POS] = userBalance
    # Bet with max height 2**256 - 1 to start withdrawal
    if max_height == ~sub(0, 1):
        # Make sure that the validator has submitted all bets
        assert self.users[index].max_seq <= seqnum
        # Register the validator as having withdrawn
        self.users[index].withdrawal_height = block.number
        # Compute how many blocks the validator has validated for
        user_validated_for = block.number - self.users[index].induction_height
        # Compute a tax for validating too long
        if user_validated_for > MAX_VALIDATION_DURATION:
            taxrate = (user_validated_for - MAX_VALIDATION_DURATION) * EXCESS_VALIDATION_TAX
            basicinfo[DEPOSIT_SIZE_POS] = max(0, basicinfo[DEPOSIT_SIZE_POS] - basicinfo[DEPOSIT_SIZE_POS] * taxrate / 10**9)
        # Store validator data
        ~sstorebytes(ref(self.users[index].basicinfo), basicinfo, 320)
        return(1:bool)
    # Update blockhashes, storing blockhash correctness info in groups of 32
    with i = 0:
        with v = self.users[index].blockhashes[mod(max_height / 32, WRAPLENGTH)]:
            while i < len(blockhashes):
                with h = max_height - i:
                    byte = not(not(~blockhash(h))) * 2 + (blockhashes[i] == ~blockhash(h))
                    with offset = h % 32:
                        v = (v & maskexclude(offset + 1, offset)) + byte * 256**offset
                        if offset == 0 or i == len(blockhashes) - 1:
                            self.users[index].blockhashes[mod(h / 32, WRAPLENGTH)] = v
                            v = self.users[index].blockhashes[mod((h / 32) - 1, WRAPLENGTH)]
                i += 1
    # Update stateroots, storing stateroot correctness info in groups of 32
    with i = 0:
        with v = self.users[index].stateroots[mod(max_height / 32, WRAPLENGTH)]:
            while i < len(stateroots):
                with h = max_height - i:
                    byte = not(not(stateroots[i])) * 2 + (stateroots[i] == ~stateroot(h))
                    with offset = h % 32:
                        v = (v & maskexclude(offset + 1, offset)) + byte * 256**offset
                        if offset == 0 or i == len(stateroots) - 1:
                            self.users[index].stateroots[mod(h / 32, WRAPLENGTH)] = v
                            v = self.users[index].stateroots[mod((h / 32) - 1, WRAPLENGTH)]
                i += 1
    # Update probabilities; paste the probs into the self.users[index].probs
    # array at the correct positions, assuming the probs array stores probs
    # in groups of 32
    # with h = max_height + 1:
    #     with i = 0:
    #         while i < len(probs):
    #             with top = (h % 32) or 32:
    #                 with bottom = max(top - len(probs) + i, 0):
    #                     x = (self.users[index].probs[mod((h - 1) / 32, WRAPLENGTH)] & maskexclude(top, bottom)) + (~mload(probs + i - 32 + top) & maskinclude(top, bottom))
    #                     self.users[index].probs[mod((h - 1) / 32, WRAPLENGTH)] = x
    #                     h -= top
    #                     i += top

    minChanged = max_height - max(max(len(blockhashes), len(stateroots)), len(probs)) + 1
    # Incentivization
    with H = max(self.users[index].induction_height, minChanged):
        # log(type=ProgressWithDataArray, 1, [minChanged, H, max_height, len(blockhashes), len(stateroots), len(probs)])
        netProb = 10**9 * convertOddsToProb(convertProbReprToOdds(~byte(0, stateroot_prob_from)))
        with PROFITBLOCK = newArrayChunk(PPB, PPN):
            loadArrayChunk(PPB, PPN, self.users[index].profits, PROFITBLOCK, mod(H - 1, WRAPLENGTH))
            CURPROFIT = loadArrayValue(PPB, PPN, PROFITBLOCK, mod(H - 1, WRAPLENGTH))
            if H % PROFIT_PACKING_NUM == 0:
                loadArrayChunk(PPB, PPN, self.users[index].profits, PROFITBLOCK, mod(H, WRAPLENGTH))
            # log(type=ProgressWithData, 2, H, max_height)
            while H <= max_height:
                # Determine the byte that was saved as the probability
                # Convert the byte to odds * 1 billion
                c = min(MAX_BET_BYTE, max(MIN_BET_BYTE, getch(probs, max_height - H)))
                with blockOdds = convertProbReprToOdds(c): # mod((self.users[index].probs[H / 32] / 256**(H % 32)), 256) or 128
                    # log(type=Progress, 3)
                    blockHashInfo = mod(div(self.users[index].blockhashes[mod(H / 32, WRAPLENGTH)], 256**(H % 32)), 256)
                    with invBlockOdds = 10**18 / blockOdds: 
                        if blockHashInfo >= 2 and blockHashInfo % 2: # block hashes match, and there is a block
                            profitFactor = scoreCorrect(blockOdds) + scoreIncorrect(invBlockOdds)
                        elif blockHashInfo < 2: # there is no block
                            profitFactor = scoreCorrect(invBlockOdds) + scoreIncorrect(blockOdds)
                        else: # block hashes do not match, there is a block
                            profitFactor = scoreIncorrect(blockOdds) + scoreIncorrect(invBlockOdds)

                    # if profitFactor < 0 and (blockOdds < 10**8 or blockOdds > 10**10):
                    #     log(type=BlockLoss, blockOdds, profitFactor, H, index, blockHashInfo)
            
                    # Check if the state root bet that was made is correct.
                    # log(type=Progress, 4)
                    if netProb:
                        stateRootInfo = mod(div(self.users[index].stateroots[mod(H / 32, WRAPLENGTH)], 256**(H % 32)), 256)
                        netProb = netProb * convertOddsToProb(blockOdds) / 10**9
                        if stateRootInfo >= 2:
                            if stateRootInfo % 2:
                                profitFactor += scoreCorrect(convertProbToOdds(netProb))
                            else:
                                odds = convertProbToOdds(netProb)
                                if odds > 10**10:
                                    log(type=StateLoss, odds, scoreIncorrect(odds), H, index, stateRootInfo)
                                profitFactor += scoreIncorrect(odds)
                        else:
                            netProb = 0
                    # Update the profit counter
                    CURPROFIT = (CURPROFIT * (INCENTIVIZATION_EMA_COEFF - 1) + profitFactor) / INCENTIVIZATION_EMA_COEFF
                    # log2(4, H, profitFactor2 + profitFactor, CURPROFIT)
                    saveArrayValue(PPB, PPN, PROFITBLOCK, H, CURPROFIT)
                    # log(type=DebugPBForBlock, PROFITBLOCK, H, CURPROFIT)
                    if (mod(H, PROFIT_PACKING_NUM) == (PROFIT_PACKING_NUM - 1) or H == max_height):
                        saveArrayChunk(PPB, PPN, self.users[index].profits, PROFITBLOCK, mod(H, WRAPLENGTH))
                        loadArrayChunk(PPB, PPN, self.users[index].profits, PROFITBLOCK, mod(H + 1, WRAPLENGTH))
                    H += 1
            # loadArrayChunk(PPB, PPN, self.users[index].profits, PROFITBLOCK, H - 1)
            # log(type=DebugPB, PROFITBLOCK)
            # log(type=RecordingTotProfit, index, H, loadArrayValue(PPB, PPN, PROFITBLOCK, H - 1))
            ~sstorebytes(ref(self.users[index].basicinfo), basicinfo, 320)
            return(1:bool)

event DebugPB(pblock:str)
event DebugPBForBlock(pblock:str, blocknum, curprofit)
event Progress(stage)
event ProgressWithData(stage, h, mh)
event ProgressWithDataArray(stage, data:arr)
event BlockLoss(odds, loss, height, index, blockHashInfo)
# event StateLoss(odds, loss, height, actualRoot:bytes32, index, stateRootCorrectness:bytes32, probs:bytes, maxHeight)
event StateLoss(odds, loss, height, index, stateRootInfo)


# Randomly select a validator using a las vegas algorithm
def const sampleValidator(orig_seedhash:bytes32, blknumber:uint256):
    n = self.nextUserIndex
    seedhash = sha3([orig_seedhash, blknumber]:arr)
    while 1:
        with index = mod(seedhash, n):
            if (div(seedhash, 2**128) * MAX_DEPOSIT / 2**128 < self.users[index].orig_deposit_size):
                if blknumber >= self.users[index].induction_height and blknumber <= self.users[index].withdrawal_height:
                    return(index)
        seedhash = sha3(seedhash)


# Getter methods 
def const getNextUserIndex():
    return(self.nextUserIndex:uint256)

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

def const getUserCounter(index:uint256):
    return(self.users[index].counter)

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

# Get information about a bet (internal method for slashing purposes)
def getBetInfo(index:uint256, max_height:uint256, probs:bytes, blockhashes:bytes32[], stateroots:bytes32[], stateroot_prob_from:bytes1, prevhash:bytes32, seqnum:uint256, sig:bytes):
    _calldata = string(~calldatasize())
    ~calldatacopy(_calldata, 0, ~calldatasize())
    my_prefix = prefix(self.submitBet)
    _calldata[0] = (_calldata[0] & ~sub(2**224, 1)) + my_prefix
    signing_hash = ~sha3(_calldata, ~calldatasize() - 32 - ceil32(len(sig)))
    # Check the sig against the user validation code
    user_validation_code = string(~ssize(ref(self.users[index].validationCode)))
    ~sloadbytes(ref(self.users[index].validationCode), user_validation_code, len(user_validation_code))
    sig_verified = 0
    with L = len(sig):
        sig[-1] = signing_hash
        ~callstatic(msg.gas - 20000, user_validation_code, len(user_validation_code), sig - 32, L + 32, ref(sig_verified), 32)
        sig[-1] = L
    assert sig_verified == 1
    return([signing_hash, index, seqnum]:arr)

event Diagnostic(data:str)
event ListOfNumbers(foo:arr)
event TryingToSlashBets(bytes1:str, bytes2:str)
event TryingToSlashBlocks(bytes1:str, bytes2:str)

# Slash two bets from the same validator at the same height
def slashBets(bytes1:bytes, bytes2:bytes):
    log(type=TryingToSlashBets, bytes1, bytes2)
    assert len(bytes1) > 32
    assert len(bytes2) > 32
    my_prefix = prefix(self.getBetInfo)
    my_old_prefix = prefix(self.submitBet)
    bytes1[0] = (bytes1[0] & ~sub(2**224, 1)) + my_prefix
    output1 = array(5)
    ~call(msg.gas - 200000, self, 0, bytes1, len(bytes1), output1, 160)
    bytes2[0] = (bytes2[0] & ~sub(2**224, 1)) + my_prefix
    output2 = array(5)
    ~call(msg.gas - 200000, self, 0, bytes2, len(bytes2), output2, 160)
    assert output1[0] == 32
    assert output2[0] == 32
    assert output1[1] == 3
    assert output2[1] == 3
    assert not self.slashed[output1[2]]
    assert not self.slashed[output2[2]]
    # Two distinct signatures with the same index and seqnum...
    if output1[3] == output2[3] and output1[4] == output2[4] and output1[2] != output2[2]:
        self.slashed[output1[2]] = 1
        self.slashed[output2[2]] = 1
        basicinfo = array(10)
        index = output1[3]
        ~sloadbytes(ref(self.users[index].basicinfo), basicinfo, 320)
        deposit = basicinfo[DEPOSIT_SIZE_POS]
        basicinfo[DEPOSIT_SIZE_POS] /= 2
        ~sstorebytes(ref(self.users[index].basicinfo), basicinfo, 320)
        ~mstore(0, block.coinbase)
        ~mstore(32, deposit / 10)
        ~call(12000, (self - self % 2**160) + ETHER, 0, 0, 64, 0, 0)
        bytes1[0] = (bytes1[0] & ~sub(2**224, 1)) + my_old_prefix
        bytes2[0] = (bytes2[0] & ~sub(2**224, 1)) + my_old_prefix
        log(type=BetSlashed, output1[3], bytes1, bytes2)

# Get information about a block (internal method for slashing purposes)
def getBlockInfo(block:bytes):
    sz = len(block)
    block[-1] = 0
    o = string(sz)
    ~call(msg.gas - 20000, RLPGETBYTES32, 0, block - 32, sz + 32, o, sz)
    blknumber = o[0]
    assert blknumber <= block.number
    block[-1] = 1
    ~call(msg.gas - 20000, RLPGETBYTES32, 0, block - 32, sz + 32, o, sz)
    txroot = o[0]
    block[-1] = 2
    ~call(msg.gas - 20000, RLPGETBYTES32, 0, block - 32, sz + 32, o, sz)
    proposer = o[0]
    if blknumber >= ENTER_EXIT_DELAY:
        preseed = ~rngseed(blknumber - ENTER_EXIT_DELAY)
    else:
        preseed = ~rngseed(-1)
    index = self.sampleValidator(preseed, blknumber)
    assert proposer == self.users[index].address
    block[-1] = 3
    ~call(msg.gas - 20000, RLPGETSTRING, 0, block - 32, sz + 32, o, sz)
    sig = o + 32
    # Check the sig against the user validation code
    user_validation_code = string(~ssize(ref(self.users[index].validationCode)))
    ~sloadbytes(ref(self.users[index].validationCode), user_validation_code, len(user_validation_code))
    sig_verified = 0
    signing_hash = sha3([blknumber, txroot]:arr)
    with L = len(sig):
        sig[-1] = signing_hash
        ~callstatic(msg.gas - 20000, user_validation_code, len(user_validation_code), sig - 32, L + 32, ref(sig_verified), 32)
        sig[-1] = L
    assert sig_verified == 1
    return([signing_hash, index, blknumber]:arr)

# Slash two blocks from the same validator at the same height
def slashBlocks(bytes1:bytes, bytes2:bytes):
    log(type=TryingToSlashBlocks, bytes1, bytes2)
    assert len(bytes1) > 32
    assert len(bytes2) > 32
    output1 = self.getBlockInfo(bytes1, outitems=3)
    output2 = self.getBlockInfo(bytes2, outitems=3)
    assert not self.slashed[output1[0]]
    assert not self.slashed[output2[0]]
    # Two distinct signatures with the same index and seqnum...
    if output1[1] == output2[1] and output1[2] == output2[2] and output1[0] != output2[0]:
        self.slashed[output1[0]] = 1
        self.slashed[output2[0]] = 1
        basicinfo = array(10)
        index = output1[1]
        ~sloadbytes(ref(self.users[index].basicinfo), basicinfo, 320)
        deposit = basicinfo[DEPOSIT_SIZE_POS]
        basicinfo[DEPOSIT_SIZE_POS] /= 2
        ~sstorebytes(ref(self.users[index].basicinfo), basicinfo, 320)
        ~mstore(0, block.coinbase)
        ~mstore(32, deposit / 10)
        ~call(12000, (self - self % 2**160) + ETHER, 0, 0, 64, 0, 0)
        bytes1[0] = (bytes1[0] & ~sub(2**224, 1)) + my_old_prefix
        bytes2[0] = (bytes2[0] & ~sub(2**224, 1)) + my_old_prefix
        log(type=BlockSlashed, output1[1], bytes1, bytes2)


