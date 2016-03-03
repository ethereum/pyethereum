data nextGuardianIndex  # map to storage index 0
data guardians[2**50](address, orig_deposit_size, induction_height, withdrawal_height, validationCode, blockhashes[2**50], stateroots[2**50], probs[2**50], profits[2**50], basicinfo, max_seq, counter)
data deletedGuardianIndices[2**50]
data nextDeletedGuardianIndex
data numActiveGuardians
data nextCounter
data slashed[]
data inclusionRewards[]

macro MAX_ODDS: 2**29

# Interpret prob as odds in scientific notation: 5 bit exponent
# (-16….15), 3 bit mantissa (1….1.875). Convert to odds per billion
# This allows 3.125% granularity, with odds between 65536:1 against
# and 1:61440 for
macro logoddsToOdds($logodds):
    2**(($logodds) / 4) * (4 + ($logodds) % 4) * 99 / 1700

macro convertOddsToProb($odds):
    $odds * 10**9 / (10**9 + $odds)

macro convertProbToOdds($prob):
    $prob * 10**9 / (10**9 - $prob)

# This is a simple quadratic scoring rule.
macro scoreCorrect($logodds, $odds):
    (($logodds - 128) * ($logodds > 128) * (3759880483 / 128 * 10**9) + $odds) / 10000

macro scoreIncorrect($odds):
    (0 - ($odds - 10**9) * ($odds > 10**9) * (3759880483 / 128 * 10 / 7 * 4) - $odds * $odds / 2 / 10**9) / 10000

macro SEQ_POS: 0
macro PREVHASH_POS: 1
macro DEPOSIT_SIZE_POS: 2
macro BET_MAXHEIGHT_POS: 3
macro PROFITS_PROCESSED_TO_POS: 4

macro VALIDATOR_ROUNDS: 5

macro INCENTIVIZATION_EMA_COEFF: 300

macro INCLUSION_REWARD_EQUILIBRIUM_PPB: 20

# VALIDATOR_ROUNDS of maximum slashing = 100% loss
# Currently: 51.5 parts per billion theoretical maximum return per block, 24.19% theoretical maximum annual reward
macro SCORING_REWARD_DIVISOR: 15398906716575978534951
macro MIN_BET_BYTE: 0
macro MAX_BET_BYTE: 255
macro PER_BLOCK_BASE_COST: 74 # parts per billion: 36.89% fixed annual penalty
# Net interest rate: 10% theoretical maximum

macro MIN_DEPOSIT: 1250 * 10**18

macro MAX_DEPOSIT: 200000 * 10**18

macro MAX_VALIDATORS: 100

macro ENTER_EXIT_DELAY: 110

macro MAXBETLENGTH: 10000

macro WRAPLENGTH: 40320

macro ETHER: 50

macro RLPGETBYTES32: 8

macro RLPGETSTRING: 9

macro MAX_VALIDATION_DURATION: 4000000 # number of blocks

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

event Reward(blockNumber, totProfit, totLoss, bmh, blockdiff)
event ProcessingBet(bettor, seq, curBlock, prevBlock, maxHeightProcessed, max_height)
event RecordingTotProfit(bettor, block, totProfit)
event Joined(index)
event BetSlashed(index:uint256, bet1:str, bet2:str)
event BlockSlashed(index:uint256, bet1:str, bet2:str)

def const getMinDeposit():
    return self.numActiveGuardians

# Become a guardian
def join(validationCode:bytes):
    min_deposit = MIN_DEPOSIT * MAX_VALIDATORS / (MAX_VALIDATORS - self.numActiveGuardians)
    assert self.numActiveGuardians < MAX_VALIDATORS and msg.value >= min_deposit and msg.value <= MAX_DEPOSIT
    if self.nextDeletedGuardianIndex:
        index = self.deletedGuardianIndices[self.nextDeletedGuardianIndex - 1]
        self.nextDeletedGuardianIndex -= 1
    else:
        index = self.nextGuardianIndex
        self.nextGuardianIndex = index + 1
    self.guardians[index].address = msg.sender
    self.guardians[index].counter = self.nextCounter
    self.nextCounter += 1
    ~sstorebytes(ref(self.guardians[index].validationCode), validationCode, len(validationCode))
    # log(20, ~ssize(self.guardians[index].validationCode))
    basicinfo = array(10)
    basicinfo[DEPOSIT_SIZE_POS] = msg.value
    self.guardians[index].orig_deposit_size = msg.value
    self.guardians[index].induction_height = if(block.number, block.number + ENTER_EXIT_DELAY, 0)
    self.guardians[index].withdrawal_height = 2**100
    basicinfo[PROFITS_PROCESSED_TO_POS] = self.guardians[index].induction_height
    self.numActiveGuardians += 1
    ~sstorebytes(ref(self.guardians[index].basicinfo), basicinfo, 320)
    return(index:uint256)


# Leave the guardian pool
def withdraw(index:uint256):
    if self.guardians[index].withdrawal_height + WITHDRAWAL_WAITTIME <= block.number:
        # Load the guardian's info
        basicinfo = array(10)
        ~sloadbytes(ref(self.guardians[index].basicinfo), basicinfo, 320)
        send(self.guardians[index].address, basicinfo[DEPOSIT_SIZE_POS] + self.inclusionRewards[self.guardians[index].address])
        self.inclusionRewards[self.guardians[index].address] = 0
        self.guardians[index].address = 0
        basicinfo[DEPOSIT_SIZE_POS] = 0
        self.deletedGuardianIndices[self.nextDeletedGuardianIndex] = index
        self.nextDeletedGuardianIndex += 1
        self.numActiveGuardians -= 1
        ~sstorebytes(ref(self.guardians[index].basicinfo), basicinfo, 320)
        return(1:bool)
    return(0:bool)

event LogPre(hash:bytes32)
event LogPost(hash:bytes32)
event SubmitBet(seq, prevhash:bytes32, index, stateroot_prob_from:bytes1)
event ExcessRewardEvent(index, profit, blockdiff, totProfit, newBalance)
event EstProfit(profit)
event EstProfitComb(profit, profit2, lsr, stateInfo)
event ZeroSeq(index:uint256,progress:uint256)

# Submit a bet
def submitBet(index:uint256, max_height:uint256, probs:bytes, blockhashes:bytes32[], stateroots:bytes32[], stateroot_probs:bytes, prevhash:bytes32, seqnum:uint256, sig:bytes):
    # Load basic guardian information
    basicinfo = array(10)
    ~sloadbytes(ref(self.guardians[index].basicinfo), basicinfo, 320)
    # log(type=SubmitBet, basicinfo[SEQ_POS], basicinfo[PREVHASH_POS], index, stateroot_prob_from)
    # Compute the signature hash
    _calldata = string(~calldatasize())
    ~calldatacopy(_calldata, 0, ~calldatasize())
    signing_hash = ~sha3(_calldata, ~calldatasize() - 32 - ceil32(len(sig)))
    # Check the sig against the guardian validation code
    guardian_validation_code = string(~ssize(ref(self.guardians[index].validationCode)))
    ~sloadbytes(ref(self.guardians[index].validationCode), guardian_validation_code, len(guardian_validation_code))
    sig_verified = 0
    with L = len(sig):
        sig[-1] = signing_hash
        ~callstatic(msg.gas - 20000, guardian_validation_code, len(guardian_validation_code), sig - 32, L + 32, ref(sig_verified), 32)
        sig[-1] = L
    assert sig_verified == 1
    # Check sequence number
    if seqnum != basicinfo[SEQ_POS] or prevhash != basicinfo[PREVHASH_POS]:
        # If someone submits a higher-seq bet, register that it has been
        # submitted; we will later force the guardian to supply all bets
        # up to and including this seq in order to withdraw
        self.guardians[index].max_seq = max(self.guardians[index].max_seq, seqnum)
        return(0:bool)
    # Check basic validity
    assert max_height <= block.number
    assert self.guardians[index].withdrawal_height > block.number
    assert len(probs) >= len(blockhashes)
    assert len(probs) >= len(stateroots)
    assert len(probs) >= len(stateroot_probs)
    # Set seq and prevhash
    basicinfo[PREVHASH_POS] = ~sha3(_calldata, ~calldatasize())
    basicinfo[SEQ_POS] = seqnum + 1
    # log(type=ProcessingBet, index, seqnum, 1, 2, 3, 4)
    # Incentivize the validator that included the bet
    reward = basicinfo[DEPOSIT_SIZE_POS] * (block.number - basicinfo[PROFITS_PROCESSED_TO_POS]) * INCLUSION_REWARD_EQUILIBRIUM_PPB / 10**9
    self.inclusionRewards[block.coinbase] += reward
    # Process profits from last bet
    guardianBalance = basicinfo[DEPOSIT_SIZE_POS]
    prevProfit = 0
    with bmh = basicinfo[BET_MAXHEIGHT_POS]:
        with CURPROFITBLOCK = newArrayChunk(PPB, PPN):
            loadArrayChunk(PPB, PPN, self.guardians[index].profits, CURPROFITBLOCK, mod(bmh, WRAPLENGTH))
            with profit = ~signextend(PPB-1, loadArrayValue(PPB, PPN, CURPROFITBLOCK, mod(bmh, WRAPLENGTH))):
                with blockdiff = block.number - basicinfo[PROFITS_PROCESSED_TO_POS]:
                    with totProfit = 0:
                        with i = 0:
                            while i < blockdiff:
                                totProfit += profit
                                profit = profit * (INCENTIVIZATION_EMA_COEFF - 1) / INCENTIVIZATION_EMA_COEFF
                                i += 1
                        guardianBalance = max(0, guardianBalance + guardianBalance * totProfit / SCORING_REWARD_DIVISOR - guardianBalance * blockdiff * PER_BLOCK_BASE_COST / 10**9)
                        # log(type=Reward, block.number, guardianBalance * totProfit / SCORING_REWARD_DIVISOR, guardianBalance * blockdiff * PER_BLOCK_BASE_COST / 10**9, guardianBalance, blockdiff)
                        prevProfit = profit
                        # if guardianBalance > 3000 * 10**18:
                        #     log(type=ExcessRewardEvent, i, profit, blockdiff, totProfit, guardianBalance)
        # Update the maximum height of the previous bet, profits and the guardian deposit size
        basicinfo[BET_MAXHEIGHT_POS] = max(bmh, max_height)
        basicinfo[PROFITS_PROCESSED_TO_POS] = block.number
        basicinfo[DEPOSIT_SIZE_POS] = guardianBalance
    # Bet with max height 2**256 - 1 to start withdrawal
    if max_height == ~sub(0, 1):
        # Make sure that the guardian has submitted all bets
        assert self.guardians[index].max_seq <= seqnum
        # Register the guardian as having withdrawn
        self.guardians[index].withdrawal_height = block.number
        # Compute how many blocks the guardian has validated for
        guardian_validated_for = block.number - self.guardians[index].induction_height
        # Compute a tax for validating too long
        if guardian_validated_for > MAX_VALIDATION_DURATION:
            taxrate = (guardian_validated_for - MAX_VALIDATION_DURATION) * EXCESS_VALIDATION_TAX
            basicinfo[DEPOSIT_SIZE_POS] = max(0, basicinfo[DEPOSIT_SIZE_POS] - basicinfo[DEPOSIT_SIZE_POS] * taxrate / 10**9)
        # Store guardian data
        ~sstorebytes(ref(self.guardians[index].basicinfo), basicinfo, 320)
        return(1:bool)
    # Update blockhashes, storing blockhash correctness info in groups of 32
    with i = 0:
        with v = self.guardians[index].blockhashes[mod(max_height / 32, WRAPLENGTH)]:
            while i < len(blockhashes):
                with h = max_height - i:
                    byte = not(not(~blockhash(h))) * 2 + (blockhashes[i] == ~blockhash(h))
                    with offset = h % 32:
                        v = (v & maskexclude(offset + 1, offset)) + byte * 256**offset
                        if offset == 0 or i == len(blockhashes) - 1:
                            self.guardians[index].blockhashes[mod(h / 32, WRAPLENGTH)] = v
                            v = self.guardians[index].blockhashes[mod((h / 32) - 1, WRAPLENGTH)]
                i += 1
    # Update stateroots, storing stateroot correctness info in groups of 32
    with i = 0:
        with v = self.guardians[index].stateroots[mod(max_height / 32, WRAPLENGTH)]:
            while i < len(stateroots):
                with h = max_height - i:
                    byte = not(not(stateroots[i])) * 2 + (stateroots[i] == ~stateroot(h))
                    with offset = h % 32:
                        v = (v & maskexclude(offset + 1, offset)) + byte * 256**offset
                        if offset == 0 or i == len(stateroots) - 1:
                            self.guardians[index].stateroots[mod(h / 32, WRAPLENGTH)] = v
                            v = self.guardians[index].stateroots[mod((h / 32) - 1, WRAPLENGTH)]
                i += 1
    # Update probabilities; paste the probs into the self.guardians[index].probs
    # array at the correct positions, assuming the probs array stores probs
    # in groups of 32
    # with h = max_height + 1:
    #     with i = 0:
    #         while i < len(probs):
    #             with top = (h % 32) or 32:
    #                 with bottom = max(top - len(probs) + i, 0):
    #                     x = (self.guardians[index].probs[mod((h - 1) / 32, WRAPLENGTH)] & maskexclude(top, bottom)) + (~mload(probs + i - 32 + top) & maskinclude(top, bottom))
    #                     self.guardians[index].probs[mod((h - 1) / 32, WRAPLENGTH)] = x
    #                     h -= top
    #                     i += top

    minChanged = max_height - max(max(len(blockhashes), len(stateroots)), len(probs)) + 1
    # Incentivization
    with H = max(self.guardians[index].induction_height, minChanged):
        # log(type=ProgressWithDataArray, 1, [minChanged, H, max_height, len(blockhashes), len(stateroots), len(probs)])
        # log(type=Progress, 50000 + logStaterootOdds)
        with PROFITBLOCK = newArrayChunk(PPB, PPN):
            loadArrayChunk(PPB, PPN, self.guardians[index].profits, PROFITBLOCK, mod(H - 1, WRAPLENGTH))
            CURPROFIT = loadArrayValue(PPB, PPN, PROFITBLOCK, mod(H - 1, WRAPLENGTH))
            if H % PROFIT_PACKING_NUM == 0:
                loadArrayChunk(PPB, PPN, self.guardians[index].profits, PROFITBLOCK, mod(H, WRAPLENGTH))
            stateRootInfo = div(self.guardians[index].stateroots[mod(H / 32, WRAPLENGTH)], 256**(H % 32))
            # log(type=ProgressWithData, 2, H, max_height)
            while H <= max_height:
                # Determine the byte that was saved as the probability
                # Convert the byte to odds * 1 billion
                # logodds = min(MAX_BET_BYTE, max(MIN_BET_BYTE, getch(probs, max_height - H)))
                with logBlockOdds = getch(probs, max_height - H):
                    with blockOdds = logoddsToOdds(logBlockOdds): # mod((self.guardians[index].probs[H / 32] / 256**(H % 32)), 256) or 128
                        # log(type=Progress, 3)
                        blockHashInfo = mod(div(self.guardians[index].blockhashes[mod(H / 32, WRAPLENGTH)], 256**(H % 32)), 256)
                        with invBlockOdds = 10**18 / blockOdds: 
                            if blockHashInfo >= 2 and blockHashInfo % 2: # block hashes match, and there is a block
                                profitFactor = scoreCorrect(logBlockOdds, blockOdds) + scoreIncorrect(invBlockOdds)
                            elif blockHashInfo < 2: # there is no block
                                profitFactor = scoreCorrect(256 - logBlockOdds, invBlockOdds) + scoreIncorrect(blockOdds)
                            else: # block hashes do not match, there is a block
                                profitFactor = scoreIncorrect(blockOdds) + scoreIncorrect(invBlockOdds)
    
                        # if profitFactor < 0 and (blockOdds < 10**8 or blockOdds > 10**10):
                        #     log(type=BlockLoss, blockOdds, profitFactor, H, index, blockHashInfo)
                        # log(type=Progress, 1000000000 + logodds * 100000 + logStaterootOdds)
                        # Check if the state root bet that was made is correct.
                        # log(type=Progress, 4)
                with logStaterootOdds = getch(stateroot_probs, max_height - H):
                    if (stateRootInfo & 2):
                        if stateRootInfo % 2:
                            profitFactor2 = scoreCorrect(logStaterootOdds, logoddsToOdds(logStaterootOdds))
                        else:
                            profitFactor2 = scoreIncorrect(logoddsToOdds(logStaterootOdds))
                    else:
                        profitFactor2 = 0
                    if H % 32 == 31:
                        stateRootInfo = self.guardians[index].stateroots[mod((H + 1) / 32, WRAPLENGTH)]
                    else:
                        stateRootInfo = div(stateRootInfo, 256)
                    # log(type=EstProfitComb, profitFactor * basicinfo[DEPOSIT_SIZE_POS] / SCORING_REWARD_DIVISOR, profitFactor2 * basicinfo[DEPOSIT_SIZE_POS] / SCORING_REWARD_DIVISOR, logStaterootOdds, stateRootInfo)
                # log(type=Progress, 80000 + logStaterootOdds)
                # Update the profit counter
                CURPROFIT = (CURPROFIT * (INCENTIVIZATION_EMA_COEFF - 1) + profitFactor + profitFactor2) / INCENTIVIZATION_EMA_COEFF
                # log(type=EstProfitComb, profitFactor * basicinfo[DEPOSIT_SIZE_POS] / SCORING_REWARD_DIVISOR)
                # log2(4, H, profitFactor2 + profitFactor, CURPROFIT)
                saveArrayValue(PPB, PPN, PROFITBLOCK, H, CURPROFIT)
                # log(type=DebugPBForBlock, PROFITBLOCK, H, CURPROFIT)
                if (mod(H, PROFIT_PACKING_NUM) == (PROFIT_PACKING_NUM - 1) or H == max_height):
                    saveArrayChunk(PPB, PPN, self.guardians[index].profits, PROFITBLOCK, mod(H, WRAPLENGTH))
                    loadArrayChunk(PPB, PPN, self.guardians[index].profits, PROFITBLOCK, mod(H + 1, WRAPLENGTH))
                H += 1
            # loadArrayChunk(PPB, PPN, self.guardians[index].profits, PROFITBLOCK, H - 1)
            # log(type=DebugPB, PROFITBLOCK)
            # log(type=RecordingTotProfit, index, H, loadArrayValue(PPB, PPN, PROFITBLOCK, H - 1))
            ~sstorebytes(ref(self.guardians[index].basicinfo), basicinfo, 320)
            return(1:bool)

event DebugPB(pblock:str)
event DebugPBForBlock(pblock:str, blocknum, curprofit)
event Progress(stage)
event ProgressWithData(stage, h, mh)
event ProgressWithDataArray(stage, data:arr)
event BlockLoss(odds, loss, height, index, blockHashInfo)
# event StateLoss(odds, loss, height, actualRoot:bytes32, index, stateRootCorrectness:bytes32, probs:bytes, maxHeight)
event StateLoss(odds, loss, height, index, stateRootInfo)


# Randomly select a guardian using a las vegas algorithm
def const sampleGuardian(orig_seedhash:bytes32, blknumber:uint256):
    n = self.nextGuardianIndex
    seedhash = sha3([orig_seedhash, blknumber]:arr)
    while 1:
        with index = mod(seedhash, n):
            if (div(seedhash, 2**128) * MAX_DEPOSIT / 2**128 < self.guardians[index].orig_deposit_size):
                if blknumber >= self.guardians[index].induction_height and blknumber <= self.guardians[index].withdrawal_height:
                    return(index)
        seedhash = sha3(seedhash)


# Getter methods 
def const getNextGuardianIndex():
    return(self.nextGuardianIndex:uint256)

def const getGuardianStatus(index:uint256):
    if not self.guardians[index].address: # inactive
        return 0
    elif block.number < self.guardians[index].induction_height: # not yet inducted
        return 1
    elif block.number < self.guardians[index].withdrawal_height: # now inducted
        return 2
    else: # withdrawing
        return 3

def const getGuardianAddress(index:uint256):
    return(self.guardians[index].address:address)

def const getGuardianInductionHeight(index:uint256):
    return(self.guardians[index].induction_height:uint256)

def const getGuardianWithdrawalHeight(index:uint256):
    return(self.guardians[index].withdrawal_height:uint256)

def const getGuardianCounter(index:uint256):
    return(self.guardians[index].counter)

def const getGuardianValidationCode(index:uint256):
    a = string(~ssize(ref(self.guardians[index].validationCode)))
    ~sloadbytes(ref(self.guardians[index].validationCode), a, len(a))
    return(a:str)

def const getGuardianSeq(index:uint256):
    basicinfo = array(10)
    ~sloadbytes(ref(self.guardians[index].basicinfo), basicinfo, 320)
    return(basicinfo[SEQ_POS]:uint256)

def const getGuardianPrevhash(index:uint256):
    basicinfo = array(10)
    ~sloadbytes(ref(self.guardians[index].basicinfo), basicinfo, 320)
    return(basicinfo[PREVHASH_POS]:bytes32)

def const getGuardianSignups():
    return(self.nextGuardianIndex:uint256)

def const getGuardianDeposit(index:uint256):
    basicinfo = array(10)
    ~sloadbytes(ref(self.guardians[index].basicinfo), basicinfo, 320)
    return(basicinfo[DEPOSIT_SIZE_POS]:uint256)

# Get information about a bet (internal method for slashing purposes)
def getBetInfo(index:uint256, max_height:uint256, probs:bytes, blockhashes:bytes32[], stateroots:bytes32[], stateroot_prob_from:bytes1, prevhash:bytes32, seqnum:uint256, sig:bytes):
    _calldata = string(~calldatasize())
    ~calldatacopy(_calldata, 0, ~calldatasize())
    my_prefix = prefix(self.submitBet)
    _calldata[0] = (_calldata[0] & ~sub(2**224, 1)) + my_prefix
    signing_hash = ~sha3(_calldata, ~calldatasize() - 32 - ceil32(len(sig)))
    # Check the sig against the guardian validation code
    guardian_validation_code = string(~ssize(ref(self.guardians[index].validationCode)))
    ~sloadbytes(ref(self.guardians[index].validationCode), guardian_validation_code, len(guardian_validation_code))
    sig_verified = 0
    with L = len(sig):
        sig[-1] = signing_hash
        ~callstatic(msg.gas - 20000, guardian_validation_code, len(guardian_validation_code), sig - 32, L + 32, ref(sig_verified), 32)
        sig[-1] = L
    assert sig_verified == 1
    return([signing_hash, index, seqnum]:arr)

event Diagnostic(data:str)
event ListOfNumbers(foo:arr)
event TryingToSlashBets(bytes1:str, bytes2:str)
event TryingToSlashBlocks(bytes1:str, bytes2:str)

# Slash two bets from the same guardian at the same height
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
        ~sloadbytes(ref(self.guardians[index].basicinfo), basicinfo, 320)
        deposit = basicinfo[DEPOSIT_SIZE_POS]
        basicinfo[DEPOSIT_SIZE_POS] /= 2
        ~sstorebytes(ref(self.guardians[index].basicinfo), basicinfo, 320)
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
    index = self.sampleGuardian(preseed, blknumber)
    assert proposer == self.guardians[index].address
    block[-1] = 3
    ~call(msg.gas - 20000, RLPGETSTRING, 0, block - 32, sz + 32, o, sz)
    sig = o + 32
    # Check the sig against the guardian validation code
    guardian_validation_code = string(~ssize(ref(self.guardians[index].validationCode)))
    ~sloadbytes(ref(self.guardians[index].validationCode), guardian_validation_code, len(guardian_validation_code))
    sig_verified = 0
    signing_hash = sha3([blknumber, txroot]:arr)
    with L = len(sig):
        sig[-1] = signing_hash
        ~callstatic(msg.gas - 20000, guardian_validation_code, len(guardian_validation_code), sig - 32, L + 32, ref(sig_verified), 32)
        sig[-1] = L
    assert sig_verified == 1
    return([signing_hash, index, blknumber]:arr)

# Slash two blocks from the same guardian at the same height
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
        ~sloadbytes(ref(self.guardians[index].basicinfo), basicinfo, 320)
        deposit = basicinfo[DEPOSIT_SIZE_POS]
        basicinfo[DEPOSIT_SIZE_POS] /= 2
        ~sstorebytes(ref(self.guardians[index].basicinfo), basicinfo, 320)
        ~mstore(0, block.coinbase)
        ~mstore(32, deposit / 10)
        ~call(12000, (self - self % 2**160) + ETHER, 0, 0, 64, 0, 0)
        bytes1[0] = (bytes1[0] & ~sub(2**224, 1)) + my_old_prefix
        bytes2[0] = (bytes2[0] & ~sub(2**224, 1)) + my_old_prefix
        log(type=BlockSlashed, output1[1], bytes1, bytes2)


