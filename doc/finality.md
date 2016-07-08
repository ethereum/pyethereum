# The Finality Cycle

The purpose of the "finality cycle" is to provide an overlay that can be added onto blockchain-style PoS protocols that provides the following properties:

1.  **Economic finality**, meaning that medium-range forks become exponentially more expensive to participate in and quickly reach a point where attampting to double-spend more than, say, 10 minutes worth of blocks would cost all participating validators their entire deposit.
2.  **O(1) light client syncing**, as a small set of signatures is sufficient to convince a light client that a very large amount of economic power fully backs a given chain.
3.  **Offline consensus validation**, as the O(1) light client syncing process can show that 2/3 of all available validators support a given blockchain, and so **there is no possibility** that some longer chain exists (as might be the case in proof of work).

In a PoS blockchain, we assume that there exists some map `USERS` mapping `address => (uint256 balance, uint256 withdrawalTime)`, where `balance` is the size of the deposit that they hold and `withdrawalTime` is the earliest timestamp at which they could withdraw the balance. We also assume that any block that is produced is produced by an address with a balance in the system, and that the probability of the user creating a block is proportional to the balance (see the paper on randomness for different ways to do this). We assume that there is a master contract with address `C` that manages this mechanism, and further assume that there is a function `processBlockHeader` of `C` which gets called during every block execution, before processing any transactions, with the block header as the input data.

The following constants apply:

*   `WITHDRAWAL_PERIOD`: the time needed to withdraw one's coins from the scheme. Set to 10**8 seconds (~4 months).
*   `MAX_INTEREST_RATE`: the maximum possible interest rate a validator can receive assuming perfect predictions, expressed in parts per billion per second (1 ppb/s = 3.2% APR). Set to 4 ppb/s.
*   `MAX_BET_ODDS`: the highest implied betting odds of a finality bet. Set to 10**9.
*   `MIN_DEPOSIT_SIZE`: the minimal deposit size required to get a full reward (note that smaller deposit sizes are allowed, they just get lower returns). Set to 1500 ETH.

### The mechanism

In the block header, we assume that there is a field `FINALITY_CYCLE_BETS`, and this field is part of the data that is signed by the signature in the block header so it is authenticated. We ask validators to provide a byte array `33n-1` bytes long, where bytes `33k...33k+31` represents the state root of the most recent block with a block number that is a multiple of 4<sup>k + 1</sup> and byte `33k+32` represents the probability that that state root is correct, expressed as logarithmic odds. The last probability is omitted because it is assumed to be the maximum (ie. 255).

    <32 bytes: state root of most recent block 4k> <1 byte: logodds> <32 bytes: state root of most recent block 16k> <1 byte: logodds> ... <32 bytes: state root of most recent block 4^i * k>

We process these bets according to the following logic.

First, let `TOTAL_DEPOSIT_SIZE` be the sum of all deposits in the system, and `BLKTIME` be the average block time. We can see that the average time between votes for an address `AVG_VOTING_PERIOD(addr) = TOTAL_DEPOSIT / USERS[addr].balance * BLKTIME`. Hence, assuming that the maximum possible return for a bet is `MAX_RETURN`, we want `MAX_RETURN / AVG_VOTING_PERIOD(addr) = MAX_INTEREST_RATE * USERS[addr].balance`, so `MAX_RETURN / TOTAL_DEPOSIT / BLKTIME = MAX_INTEREST_RATE`, ie. we can target `MAX_RETURN = MAX_INTEREST_RATE * TOTAL_DEPOSIT * BLKTIME`.

For example, suppose that the total set of deposits is 10<sup>7</sup> ETH, and we want a max interest rate of 4 ppb/s (13.4% APR), and the block time is 3 seconds; then, we set the max return to `10**7 * 4 / 10**9 * 3 = 0.12 ETH`. A validator with 10000 ETH would on average get a block every ~3000 seconds, and so would get a return of ~0.144 ETH per hour ~= 1261 ETH per year, close to the expected 13.4% APR (the discrepancy is due to the lack of compounding in the interest calculation).

Hence, in this scenario we want the maximum possible gain to be `MAX_RETURN = 0.12 ETH`, and the maximum loss to be `BET_MAXLOSS = MIN_DEPOSIT_SIZE = 1500 ETH`. It makes no sense to bet more than `WITHDRAWAL_PERIOD / BLKTIME` blocks back, so we set `MAX_BET_LENGTH = floor(log_4(WITHDRAWAL_PERIOD / BLKTIME))`, eg. with the above settings `MAX_BET_LENGTH = floor(log_4(3333333)) = 10`. Hence, we allocate to each bet a `BET_MAXGAIN = MAX_RETURN / MAX_BET_LENGTH`, in this case 0.012 ETH; the last bet has a maximum gain of `BET_MAXGAIN` multiplied by the number of bets missing, eg. if there are only 6 bets then it is multiplied by 5 because it "stands in for" bets 5, 6, 7, 8 and 9.

From these constants, we can compute three parameters `A`, `B`, `MAXODDS` such that `score_correct(255) = BET_MAXGAIN`, `score_incorrect(255) = BET_MAXLOSS` as well as targeting a condition about the shape of the functions, where we define `score_correct` and `score_incorrect` as follows:

    def score_correct(logodds):
        odds = MAXODDS**(logodds / 255.)
        return math.log(odds) * A + odds * B

    def score_incorrect(logodds):
        odds = MAXODDS**(logodds / 255.)
        return -odds * A - odds**2/2 * B

These functions together make up a scoring rule, allowing users to bet with odds from `1:1` to `MAXODDS:1` on a given state root; the idea is that for each claim made in the bet about a previous state root, if the claim is correct then `score_correct` is used to compute an increase to the user's balance otherwise `score_incorrect` is used to compute a decrease to the user's balance. The functions make up a proper scoring rule, ie. given a particular opinion about the odds of a given state root being "final", the validator's incentive is to provide that opinion in their bet.

Note that since a block has a parent and hence a defined history, if the block makes it into the main chain and the validator bets consistently, the state roots are guaranteed to be correct and so `score_correct` is guaranteed to be called. If a block does not make it into the main chain, there is a function by which the block can be included later (this is the same function that penalizes the validator), and in this case `score_correct` cannot be called (to disincentivize deliberately creating a block too late and other attacks) but `score_incorrect` can be, so in all cases the block header's bet has "economic weight" in the sense that a light client that receives the bet can be sure that either (i) the claim is correct, or (ii) the validator will lose money.

If a validator has less than `MIN_DEPOSIT_SIZE` ETH in the deposit, then they are restricted to making only bets such that `score_incorrect` returns a value smaller than their deposit size; they do not get rewarded for more confident bets.

The code for computing the paramters above can be found here: [https://github.com/ethereum/economic-modeling/blob/master/casper/compute_scoring_rule_constants.py](https://github.com/ethereum/economic-modeling/blob/master/casper/compute_scoring_rule_constants.py)

### The strategy

Given this mechanism, the next question is: how do validators decide how to bet? This is heavily up to the discretion of each validator. A simple initial betting strategy is to use a running Laplacian prior, which works as follows. The validator would keep a running tally of all the situations they have seen in which a given block has had N confirmations (eg. the dominant chain containing that block scored N points higher than the dominant chain not containing that block), and they will keep track of how often in those situations the block is later reverted. If, for example, a block in such a position has been reverted 2 out of 637 times, then the validator will believe that the block has a 2+1 in 637+1 (ie. 3 in 638) chance of reverting.

An alternative strategy is a guaranteed-bounded-loss strategy: for each situation, suppose you are willing to take a maximum loss `MAXLOSS`. Let `BAL` be the validator's total gains in that situation so far, and `BETS` be the number of bets the validator has made in that situation so far. The validator will take the most optimistic possible bet such that the loss from the bet going wrong is `(BAL + MAXLOSS) / (BETS + 1)`. A possible optimization is to put situations into groups, ie. treat the set of situations consisting of 64....127 confirmation differences between the dominant chain containing a block and not containing a block as a single situation.

The above is a pure prediction market; the next step is incorporating the results into the fork choice rule itself, ie. making the choice of which fork is correct take these bets into account. Here, an important concern is preventing the mechanism for doing this from being a vector for launching medium-length forks; for example, if a large bet is guaranteed to have a large impact on the score of a block, then ten blocks after a given block an attacker may make a highly confident bet in favor of a competing block, flipping the chain in his favor. To avoid this, we can establish a rule that limits the "weight" of each bet, for example:

*   If a validator makes a bet with odds 2:1 on a given state root, then all histories containing that state root get an additional 1 point in the scoring rule.
*   If a validator makes a bet with odds k:1 on a given state root, then let L:1 be the 67th percentile odds in favor of that state root from the last 40 blocks, ie. the highest odds such that at least 27 of the last 40 blocks bet in favor of that state root with at least those odds. All histories containing that state root get an additional `min(k^2, (2L)^2)` points in the scoring rule.

If validators always make the maximally confident bets that they are allowed to make under this rule, then we can see that the amount of stake backing each block will increase exponentially over time, quickly hitting the ceiling of `BET_MAXLOSS`.

### Finality as an overlay to proof of work

Note that it is possible to design this scheme as an overlay to proof of work. The technique would involve using block hashes as a source of randomness to select a stakeholder for each "window" of blocks (eg. a window can be 4 blocks wide), with each stakeholder getting a chance proportional to their deposit of being selected, and implement the same mechanism within that framework. The fork choice soft forking can happen within this scheme too, making the protocol a hybrid of proof of work and proof of stake.
