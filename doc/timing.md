### Timing Rules in PoS

One important issue that must be solved in any proof of stake algorithm is timing. Some mechanism is required to determine which validators are allowed to produce blocks at what times. One may come up with the simple policy that validators are simply allowed to produce blocks as quickly as network latency allows, but then one is faced with an issue: what if the validator at some given height is missing? Then, a subsequent validator must eventually be able to produce a block, but if the time until "eventually" is zero then the algorithm is essentially a free-for-all that is likely to be won by the cluster with the best connectivity. Hence, some restrictions on when blocks can be sent by whom in any given situation are required.

### Timing in NXT

In NXT, timing works approximately as follows:

1.  Every block height corresponds to a "slot" of time one minute wide. Timeslots are assigned to validators using some algorithm (see the paper on randomness for more details)
2.  A validator can produce a block during a timeslot assigned to them, and that block must point to a previous block; the longest-chain rule is used to determine which blockchain is valid at any given time.
3.  If a validator publishes a block too early (ie. before the start of the next timeslot that is assigned to them), then other validators will ignore the block until the start of that timeslot, and pretend to only receive the block at that time. There are no in-protocol penalties for publishing a block too late.

In proof of work, timestamps are used for the limited function of regulating the rate of block production, and in both the bitcoin and ethereum case a variant of rule 3 is also used. With this mechanism, there is clearly no incentive to publish a block too early, as validators will simply pretend that you had published it at the earliest correct time, and a validator that does publish too early may well miss out on potentially lucrative fees. There is also a disincentive against publishing too late: you open yourself up to competition against the next validator.

However, there is a more interesting question that is much harder to answer: might there be an incentive to **accept** a block too early? That ius, suppose that according to the protocol specification validators are "supposed to" accept a given block X at time T. Suppose now that you receive a block at time T-1\. Might you have some advantage from accepting that block and building on top of it? There is, at least theoretically, a possibility of a "drift" scenario where, if everyone else accepts a block at time T, it is individually rational to accept at T-1, creating a race to the bottom with validators accepting blocks earlier and earlier than planned.

### Absolute and Relative Time

Before we move towards trying to come up with a solution to that puzzle, let us first discuss two ways of enforcing timing rules in a PoS blockchain, which we can call **absolute time** and **relative time**. Absolute time is simple: it involves the use of rules of the form "a block with parent X in situation S can only be accepted starting from time T". Relative time, on the other hand, uses rules of the form "a block with parent X in situation S can only be accepted at least T seconds after the parent was received".

Both styles have their advantages:

1.  Absolute time requires the nodes to have access to synchronized timestamps, which is a potential centralization vector. Relative time only requires access to reasonably accurate clocks, and even 1% (~14 minutes per day) clock drift is not fatal.
2.  If the blockchain requires knowledge of an absolute timestamp for reasons unrelated to consensus (this goes beyond use of the `TIMESTAMP` opcode; in Casper, an important use case is making sure that de-facto annual interest rates are constant), absolute time-based mechanisms come with such a timestamp built in, whereas if relative time is used it must be added explicitly.
3.  Relative time doubles the error from network latency, as the variance in delay in receiving the parent and the variance in delay in receiving the child both contribute to the variance in relative time.
4.  Relative time allows for blocks to be created "as fast as possible" with no limits to the creation of blocks except in the case of skips. A mean block time of under 1 second is quite possible as long as skips are spaced far apart enough for safety. However, in the absolute time case a limited version of this can still be achieved, simply by making the timeslot start time based on a formula such as `block_height * 2 + total_skips * 8`, providing a 2-second block time without skips and an 8-second block time during a skip.

A particularly important one, however, is that absolute time is less vulnerable to equilibrium drift. If there is a reason why drift is taking place, in an absolute-time scenario the drift will be on a per-second basis, so the average block time will still remain close to constant. In a relative-time scenario, the drift will be in the minimum time between blocks, so the average block time itself could shrink or grow greatly. For this reason, we focus on absolute time, with a fast normal block time and slower skip time, for the remainder of this discussion.

In order to mitigate the clock drift issue, we can use the blockchain itself as a kind of limited timestamp provider. The approach is simple: determine a timestamp such that the sum of the absolute offsets between the time each of the last 80 blocks should have appeared, and the time that it did appear, is minimized. This method will roughly provide the median timestamp of the nodes, with an offset that takes into account network latency (using least squares rather than least absolutes would provide the mean, but using the mean is dangerous as one extreme node could greatly manipulate the result). This "poor man's NTP" is substantially less precise than the real NTP, but is more decentralized, and is economically expensive for any party to manipulate.

### How to Enforce

The next question is, is the NXT approach to disincentivizing too-early blocks the correct one? From an outside view, it is not clear if the strategy is evolutionarily stable; in general, if an actor has a piece of information, then a strategy that asks the actor to ignore that information until some preset time, as the NXT approach does, is likely not to be optimal, as there may be ways to use the information ahead of time in order to optimize one's behavior. In this specific case, if a highly-weighted chain appears a few seconds too early and it is a given validator's turn to produce a block, then it may be in that validator's interest to produce a block on top of that chain, as the validator knows that in a few seconds other validators will see that chain and accept it as the winning chain. It may well be the case that recursive reasoning leads all validators to simply ignore the timestamp in the equilibrium.

We evaluate a possible alternative approach: make a weakly subjective scoring rule. Specifically, the idea is to modify the function that computes the "length" of a chain for purposes of picking the longest one such that any block that was received before the alloted time receives 0 points instead of 1\. Hence, if there is a head X and a child Y is created too early, X and Y will actually have equal scores, and nodes will try to create a block on X if they can and on Y if they can.

Suppose that there is zero network latency, so "time received" is an objective parameter on which there is perfect ex-ante consensus among online nodes. Then, we can reason as follows. If such a child is created, you can either (i) accept too early, which means trying to create a block on Y only, or (ii) follow the rules, which means trying to create a block on X if you can or on Y if you can. Suppose that the reward for adding a block to the chain is 1 and the penalty for creating a block that goes off the chain is 1 (ie. a block is a bet at 1:1 odds on its own inclusion). Then, a validator with ε stakepower following (i) will get an expected reward of ε, as they have an ε chance of being able to create the block on Y and if they do then it will be accepted as a head, and a validator following (ii) will get an expected reward of 2ε as they have that chance for both X and Y (note that due to their weight, if they build on X then just X will be part of the longest chain, otherwise Y will also be part of the longest chain, by creating the block they essentially pick the winner); hence (ii) is favored.

Now, suppose that there is some network latency and hence uncertainty. Suppose also that the distribution of network latencies is symmetrical. If a validator receives a block too early, they can then infer that there is a chance of `p > 0.5` that the next validator also saw the block as appearing too early. Their expected return from strategy (i) is ε as before, since no validator will see building on Y as objectionable, and from strategy (ii) as ε `+` ε `* p -` ε `* (1-p)` = ε `* (2p - 1)`, as there is a `p` chance that a block Z that they construct on X will be viewed as having the highest score, as Y has equal score to X and Z would have a score 1 higher, and a `1-p` chance that such a block will have equal score to Y, as both Z and Y would have a score 1 higher than X, and in this case Z would lose because it skips whereas the block on Y would proceed without skips and so can be created more quickly. Hence, creating a block on X or Y is optimal only if you think the rest of the network saw that Y appeared ahead of schedule, and otherwise you want to stick to creating a block on Y only - exactly the correct outcome. In reality, however, the distribution may be asymmetrical, and so receiving a block a little too early may in fact give you information that most of the network saw the block on schedule.

I have implemented simulations of this scheme, as well as NXT's scheme, using both the longest-chain rule and GHOST and have obtained results summarized in this table: [http://vitalik.ca/files/modeling_results.txt](http://vitalik.ca/files/modeling_results.txt). Strategy groups 0 and 8 represent normal compliance, groups 6 and 7 represent accepting too early and groups 9 and 10 represent accepting too late. In summary, we see in general that with the NXT scheme there is a very small and possibly statistically insignificant gain (~1%) to complying with the rules, whereas with the weakly subjective scheme there seems to be a consistent ~2% gain to accepting blocks too early.

A likely cause of this is that in an NXT-style scheme, small amounts of drift are arguably meaningless; the reason is that given some block with a minimum receiving time T, the scheme does not give the opportunity to create a block just before T in the first place. Rather, the only amount of drift that makes meaningful sense is a multiple of the skip time; in this case, the question is this: suppose that block X has been created, and the time has come for some other validator to possibly create a block Y (with 0 skips). You are slotted to create block Z with 1 skip. Do you try to create Z early? Hence, the de-facto strategy space is discretized, in a similar way to how PoW is discretized, defending against drift:

Initial tests show that there is in fact an incentive to take the default strategy and not either extreme (accepting early or accepting late):

![](http://vitalik.ca/files/returns_by_drift.png)

Hence, it seems reasonable to conclude, from these initial observations, that the "ignore until earliest allowed time" scheme used in NXT is likely the best approach available.

### Sequential proof of work

A third strategy for dealing with these timing issues is to use sequential proof of work. A sequential proof of work puzzle is one that, if solved, proves that the solver performed a certain amount of sequential computation, ie. it is impossible to achieve speed gains by parallelizing; additionally, it is a property of all of these schemes that there are limits to the gains that one can achieve by improving hardware.

A simple sequential PoW algorithm is iterated hashing, ie:

    def pow(x, rounds):
        for i in range(rounds):
            x = sha3(x)
        return x

The idea would be to continue running the algorithm until you find a number of rounds such that the result fits some mathematical condition, eg. the first 4 bytes are all zeroes. However, using sha3 has the weakness that it takes as long to verify as it does to compute. A perhaps better alternative is iterated modular square roots, using a different modulus during different rounds, ie. something like:

    primes = [... list of prime numbers between 2**31 and 2**32 such that p = 4k+1 for some integer k...]

    def pow(x, rounds):
        for i in range(rounds):
            x = modsqrt(x, primes[i % len(primes)])
        return x

Where `modsqrt` is a function which satisfies `(modsqrt(x, p) * modsqrt(x, p)) % p == x` for all values `1 < x < p` and primes `p`. Computing a modular square root where the prime modulus is of the form `4k + 1` involves the [Tonelli Shanks algorithm](https://en.wikipedia.org/wiki/Tonelli%E2%80%93Shanks_algorithm), which requires ~4b modular multiplications for a b-bit number, but running the PoW backwards to verify it equires a single modular squaring for each round; hence, for 32-bit numbers which can easily be computed in existing 64-bit processors, there is a 128-factor difference between computation and verification.

Such a puzzle can be used as an alternative skip timing mechanism: simply require a block that skips `n` validators to compute, say, `4 * n` seconds worth of sequential proof of work (we'll leave it an exercise to the reader to imagine an in-protocol difficulty adjustment scheme that would securely determine just how much sequential PoW _is_ 4 seconds' worth). This completely circumvents all issues about incentive compatibility of timing and early acceptance because the definition of a valid block will once again be unambiguously objective, so early acceptance or early production is impossible.

Sequential PoW does have the weakness that it is PoW, and so brings back some degree of wasteful energy expenditure as well as a possible ASIC arms race, but the effect of these issues is very limited because the way that the PoW is limited. The amount of energy that can be usefully spent on it is capped at a very low amount (assuming a perfectly smoothly running network, zero, and in the worst case perhaps 10-20 CPUs running at full capacity on one core) and even if ASICs are developed and one firm produces 99% of all ASICs there is little centralization concern as long as the underlying PoS system's stake is distributed well.

There is a superlinear reward concern if wealthier stakeholders can afford hardware-accelerated sequential PoW but others can't, but in a well-functioning network this should be very low as the sequential PoW is used only in the case of skips. Additionally, we can imagine a scheme where each stakeholder is assigned a "private difficulty" value, adjusting each stakeholder's difficulty so as to ensure that they produce a roughly equal number of skip blocks; this would increase fairness and reduce the incentive to develop ASICs even further.
