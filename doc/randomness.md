### Validator Ordering and Randomness in PoS

Proof of stake consensus algorithms promise to provide consensus for public blockchains at much lower cost than proof of work, as nodes do not need to consume electricity beyond the very small cost of downloading and processing the blockchain, with the protocol itself taking on the role of assigning validators ("virtual miners") the right to produce blocks on a random schedule. However, these algorithms carry several unique challenges, as there are hidden functions that proof of work provides that are not immediately obvious to the casual observer, but which are nevertheless crucial and must in some way be replicated in a proof of stake protocol.

A major one of these functions is validator ordering. Blockchain-style consensus protocols of all categories, including simple proof of work, GHOST proof of work, NXT-style proof of stake, and the current version of Casper all rely on a similar notion of convergence which can be very abstractly described as follows. The scheme requires validators to frequently converge on "decisions", which can be represented as a choice between A and B, with a number line representing the current state of the convergence process going from negative to positive infinity, starting at zero, with each block either making one step toward A (ie. -1) or one step toward B (ie. +1). Validators are incentivized to vote A when the process is "leaning" toward A, and vote B when the process is leaning toward B, thereby creating a positive feedback loop which quickly puts every decision on a path to convergence.

In simple proof of work, the decisions are between chains. In GHOST, the decisions are at the level of each block that has multiple children, deciding which child to choose; determining the "head" of the chain proceeds by applying the decision rule starting from the genesis and going down the chain one block at a time. However, in order for all of these schemes to work, some mechanism for ordering validators must exist. Proof of work does this implicitly, as the mining process in a random and unpredictable way "assigns" miners the right to create a block whenever they are lucky and discover a hash solution; proof of stake lacks this built-in mechanism and so must do this explicitly.

### The Model

Suppose that we have a proof of stake scheme with a static validator pool (to simplify the problem) of N validators. Each validator `V[i]` for `1 <= i <= N` has an account (which we will identify with `V[i]`) and the protocol may require the validator to hold on-chain state `S[i]` and private data `P[i]` (in addition to their private key; the fact that blocks are cryptographically signed and the public keys of validators are stored in on-chain state is assumed). Our goal is to determine (i) an initialization procedure for `S[i]` and `P[i]`, and (ii) a function `F(i, S[i], P[i], b)`, where `b` is a block, and outputs either `NULL` (the validator cannot produce a block) or a witness `W` which can either simply be the value 1, representing the right to produce a block, or a value which proves that the validator can create the block. What "heights" are is left unspecified, and requirements around _when_ a block at a given height may be published are also left unspecified, so as to maximize the generality of this document. Proving that proof of stake as a whole satisfies any specific economic or byzantine fault tolerance assumptions is also beyond the scope of this document, however such a proof for byzantine fault tolerance is available in [this document](https://arxiv.org/abs/1710.09437), with a discussion on the same paper (here)[https://ethresear.ch/t/latest-casper-basics-tear-it-apart/151/35].

### Round robin consensus

One simple algorithm is round robin consensus:

`F(i, b) = 1 if b.height % N == i else 0`

Essentially, validators are assigned the right to produce blocks in sequence. This algorithm benefits from a very high degree of simplicity, but has a number of important weaknesses:

*   **No denial of service resistance**: because validators can be predicted ahead of time, attackers may be able to target denial-of-service attacks against each validator during the timeslot during which they are supposed to create a block.
*   **Extreme ease of planning "selfish mining" strategies**: an attacker can clearly see any contiguous ranges during which they, by random chance, have more validators than all honest actors, and can use this information to consistently force other validator's blocks to get kicked off the main chain as they can create a longer chain.
*   **Ease of planning medium-length forks**: an attacker can capture a large contiguous sequence of `K < N` validator slots, and thereby force the previous K-1 blocks to be reverted. This means that no practical notion of "de-facto finality" can be achieved in less than `N / 2` blocks, and in a public chain `N` can be quite large; no "six confirmations" for you.

### NXT RNG

A slightly more complicated approach, used in the NXT blockchain, is as follows (see the relevant source code extract [here](https://bitbucket.org/JeanLucPicard/nxt/src/4d3e828e818d13065b636bfcccfb3806f16a24e7/src/java/nxt/BlockchainProcessorImpl.java?at=master&fileviewer=file-view-default#BlockchainProcessorImpl.java-1830)). Define:

    E(0) = 0
    E(b) = hash(E(b.parent), b.validator)

Where `b.validator` is the pubkey of the validator that produced the given block.

We then select `F(i, b) = 1` iff `E(b) % N == i` (note: this is different from NXT's approach, but is simpler and thus preferred for expository purposes; the essential properties of the NXT algorithm come from the definition of `E` itself and not the specifics of how it's used).

The key behind this approach is that it derives randomness from the fact that the chain of validators that create the blocks in the chain is not certain: if every validator behaves perfectly, then it can certainly be computed ahead of time without limit, but any validator that fails to produce a block, or whose block does not make it into the main chain (eg. for timing reasons), serves as an unpredictable source of entropy. Particularly, note that this entropy is costly to manipulate: the only way to influence it is for a validator to deliberately not produce a block when they are entitled to, and this costs them a block reward and transaction fees; hence, validators will only do this in the case that it increases their expected number of future block production slots by more than 1.

We can compute the probability of this happening for any given validator with portion `h` of stake power (ie. `N*h` validator slots), and a probability `m` that an honest validator will miss a block (and thus make the entropy unreliable) as follows. First, we define a distribution `D` over _expected-value revenues_, and treat both validating honestly and block skipping as separate results of sampling from that distribution. We can define `D` naively as follows, where `h` is the attacker's stake power, `m` is the natural probability of a validator missing a block, and `R(h)` is a distribution that outputs 1 with probability `h` and otherwise zero:

    D(h, m) = R(h) + m * D(h, m) + (1-m) * D(h, m)

Essentially, the next block will be the attacker's with probability `h` and otherwise it won't be, and then for subsequent blocks we note that we are back in the same situation, except that a separate sample is required for the `1-m` case, representing the next validator successfully creating a block, and the `m` case, representing the next validator failing to create a block. Note that this equation always tends to infinity, which is expected since rewards go on forever. However, what we can do is analyze the distribution as a mathematical object and determine its variance:

    V(D(h, m)) = V(R(h)) + V(m * D(h, m)) + V((1-m) * D(h, m))

    V(D(h, m)) = h * (1-h) + m^2 * V(D(h, m)) + (1-m)^2 * V(D(h,m))

    V(D(h, m)) = h * (1-h) + (2*m + m^2) * V(D(h, m))

    V(D(h, m)) = h * (1-h) / (2*m + m^2)

The standard deviation, as usual, can be computed by taking the square root of the variance. Now, we want to know: given two samples (the first corresponding to mining honestly and the second corresponding to skipping), what is the probability that the second sample will be more than one unit higher than the first sample? If it is, then it is worth the cost of losing a block reward to manipulate the randomness by not publishing. We can estimate this probability from the standard deviation by assuming that the distribution is normal, and then multiplying the standard deviation by sqrt(2) ~= 1.41 to get the standard deviation of two of these distributions subtracted from each other (if the difference is at least +1 then exploitation is profitable).

Hence the final formula for the relevant statistic is this:

    SDD(D(h, m)) = sqrt(2 * h * (1-h) / (2*m + m^2))

The following table provides some examples:

<table>

<tbody>

<tr>

<td>Standard deviation of difference</td>

<td>Probability exploitation is profitable</td>

</tr>

<tr>

<td>0.5</td>

<td>0.023</td>

</tr>

<tr>

<td>1</td>

<td>0.159</td>

</tr>

<tr>

<td>1.5</td>

<td>0.253</td>

</tr>

<tr>

<td>2</td>

<td>0.309</td>

</tr>

<tr>

<td>3</td>

<td>0.370</td>

</tr>

<tr>

<td>∞</td>

<td>0.5</td>

</tr>

</tbody>

</table>

Note that results for low standard deviations are slightly unreliable because in those cases there are too few samples for the central limit theorem to properly apply; fortunately, in our case, if we assume `m` is low (as validators don't make mistakes _that_ often), then we can see that there is enough data for the approximation to work (eg. even at `m = 0.2`, we get ~10 large samples of `R(h)`).

To provide some results, consider that at `h = 0.2` and `m = 0.05`, we get `SDD = 1.76`, and at `h = 0.2` and `m = 0.01` we get `SDD = 3.99`. Hence, the incentives to skip are frequent and substantial.

One mitigating factor to keep in mind is that block skipping may in practice be kept low because it is in some ways self-defeating: skipping by both the validator themselves and by other validators employing the same strategy contribute to `m`, and higher values of `m` reduce the standard deviation and hence make skipping less attractive. However, even still, this means that equilibrium operation will be highly suboptimal.

There are several approaches to mitigating this problem at other layers of the protocol. One is to explicitly penalize not creating blocks over and above the opportunity cost of not getting the reward; a penalty of 2x the reward (ie. a validator must create blocks at least 67% of the time to be profitable) would increase the requirement to the point that the second sample must be three units higher than the first sample to make exploitation profitable. This changes the table above to the following:

<table>

<tbody>

<tr>

<td>Standard deviation of difference</td>

<td>Probability exploitation is profitable</td>

</tr>

<tr>

<td>0.5</td>

<td>0.0000</td>

</tr>

<tr>

<td>1</td>

<td>0.0013</td>

</tr>

<tr>

<td>1.5</td>

<td>0.023</td>

</tr>

<tr>

<td>2</td>

<td>0.067</td>

</tr>

<tr>

<td>3</td>

<td>0.159</td>

</tr>

<tr>

<td>∞</td>

<td>0.5</td>

</tr>

</tbody>

</table>

This is not a perfect solution, but it does make the equilibrium behavior much more palatable. The second is to introduce a counter into the state that keeps track of how many blocks a validator produces, and constantly adjust that the probability that that validator will be able to create the next block so as to target a constant value; this way, any manipulation of the RNG would simply be self-correcting long-term (except for the very brief period before the validator withdraws), although not participating would still be penalized.

In exchange for these exploitation concerns, however, the NXT RNG approach does introduce an important property: attackers cannot reliably make sure that they control large ranges of heights in advance. From a sufficiently long view (ie. more than `~3/m` blocks), the RNG _is_ random. However, the RNG is still predictable in the short term and so attack vulnerabilities still do exist.

Also, note that this RNG can be simplified substantially from the NXT approach by taking the one factor that influences entropy (namely, validator skipping), and simply using it explicitly.

    E(0) = 0
    E(b) = hash(HX(E(b.parent), # of blocks skipped since parent), 1)

Where:

    HX(d, 0) = d
    HX(d, i) = hash(H(d, i-1), 0)

This looks slightly more involved but is actually simpler, as what it means in practice is that at each height a state transition takes place, which simply takes the previous value and hashes it together with 1 if a block was present and with 0 if a block was not present.

### RANDAO

One can also rely on sources of randomness other than validators skipping. The leading approach in this regard is Youcai Qian's [RANDAO](https://github.com/randao/randao), which in its most abstract and general form works as follows:

1.  N participants each pick a value `v[i]` and submit `hash(v[i])` along with a security deposit
2.  Participants submit `v[i]`; the system makes sure that the values match the previously submitted hashes
3.  The XOR of the `v[i]` values submitted is taken as the result, and everyone who did not submit their `v[i]` value loses their deposit

There are a number of possible extensions, particularly (1) not returning a value unless _all_ `v[i]` values are submitted and instead re-running the algorithm until they are (this makes manipulation somewhat harder at the expense of making the algorithm potentially take multiple rounds), and (ii) incorporating an [anti-pre-revelation game](https://blog.ethereum.org/2015/08/28/on-anti-pre-revelation-games/) to discourage early revelation of `v[i]` values through side channels. However, these mechanisms are not strictly necessary.

We can incorporate this into a blockchain context by initializing the state information `S[i]` as containing `hash(v_0[i])` where `v_0[i]` is part of the private information `P[i]`, and requiring the nth block of validator `i` to contain (i) `v_(n-1)[i]`, and (ii) `hash(v_n[i])` for some new value `v_n[i]`. We now keep a running XOR (or sum or hash or whatever) of all `v_j[i]` values submitted by all validators, and use this as a source of randomness in exactly the same way that the NXT RNG does, ie:

`F(i, b) = 1` iff `RANDAO(b) % N == i`.

We can have a small penalty for non-participation, so it is still manipulable but at medium cost, and because of the high degree of unpredictability of the randomness (roughly equivalent to the results of the above calculations for the NXT RNG but setting `m = 1`) manipulation is almost never reliably worth it. The fact that the public can only ever see one block ahead also means that, while DOS attacks against block-producing validators can still happen, they are hard, particularly if the block time is fast; additionally, pre-planned attacks are even harder than the NXT RNG case.

### Pure private randomness

A different approach to validator determination is one based on "private randomness". The approach here is as follows. Each validator initially generates a random value `v_1000000[i]`, and calculates `v_j[i] = hash^(100000-j)(v_1000000[i])` for `1 <= j <= 1000000` (ie. a chain of a million values where each value is the hash of the previous) and saves these values. `v_0[j]` is put into `S[i]`, all other values are private information.

In simplest form, the function determining validator eligibility is as follows:

`F(i, b) = v_(b.height)[i] if xor(v_(b.height)[i], hash(i)) < 2**256 / D else 0`

Where `D` is the difficulty parameter. Note that this does require the block to include `v_(b.height)[i]` as a "witness" in order to show the network that the validator actually does have the right to create the given block.

The benefit of this approach is that outside actors cannot see in advance when a validator will be able to create the next block, so we have a very high degree of resistance to denial-of-service attacks. In a future scalable blockchain context, another benefit is that it is extremely easy to parallelize, as all values are arrived at independently. However, the main risk is that the validator themselves will be able to engage in a "grinding attack", where they determine ahead of time how many blocks a given seed will create and try to continually re-create seeds until they find one which is sufficiently favorable to them. This can have two consequences: (i) unfairly increased profits for validators that do this (and hence resulting economic inefficiency), and (ii) grinding in order to gain a majority of votes within a particular range of block heights so as to revert a medium-length fork (or in a scalable blockchain context to attack a shard).

Contrary to some popular wisdom, the existence of nonzero gains to be made from a grinding attack does not immediately imply that the algorithm will on net consume as much electricity as a simple proof-of-work scheme. Rather, we can determine the equilibrium energy consumption by analyzing what expected returns a given amount of grinding will provide, determine the point where marginal grinding is no longer worth the cost and use economic reasoning to determine the total losses from grinding as well as the degree of centralization risk.

In this case, we know that `n` attempts will lead to an expected maximum of `sqrt(2) * ln(n) * SD + M`, where `M` is the mean and `SD = sqrt(M / 2)` is the standard deviation. Hence, the expected maximum is `M + sqrt(M) * ln(n)` and so the marginal value of the nth attempt is `sqrt(M) / n`. Suppose that the block reward is `R`, and that one round of grinding has a cost `c`. Then, the equilibrium is where `c = sqrt(M) / n * R`, and so the total cost of grinding will be `c * n = sqrt(M) / n * R * n = sqrt(M) * R`. Hence, assuming that a validator would honestly get `M` blocks, they will expend effort equal to `sqrt(M)` times the block reward - a fairly small amount of grinding for all but the smallest validators. This in fact shows that the grinding, though inefficient, carries a very small centralization risk, and it is in fact a _minimum_ deposit size that may be appropriate to counter it. Additionally, dynamic retargeting can be used to further reduce the vulnerability.

Grinding to revert (or to attack a shard) is a more serious problem. The goal for mitigating the problem is to make it very difficult (ie. computationally/economically infeasible) for attackers to coordinate in advance a situation where they will dominate (ie. have more than 50% stake in) some particular significant range of heights. Here, the primary concern is that private randomness provides very many "dimensions" for the attacker to optimize their seeds. For example, if an attacker spreads their validators among slots that, in the desired range, would ordinarily only make one block, then the attacker can, by retrying each seed 148 times (that's ~e**5), get six blocks within that range - enabling a 51% attack with only 14.28% of the stake. Note that the xor in the original formula prevents the attack from being vastly worse (where the attacker could find a single optimal seed and reuse it for all validators) by xoring it with a unique value for each index, but even still the vulnerability exists. So far, I have not found a solution to this problem in a "pure" private randomness context.

Another concern with this approach is the selfish validating vulnerability. Even though a validator does not see results of other validators' future randomness, they see their own future randomness, and so a validator with medium stake (~10-30%) can see when they are very likely to have more than 50% of the stake power in the very short term (~2-8 blocks), and exert selfish-mining-style attacks against those other validators. This can be mitigated by other means in a proof of stake context (eg. making the validation returns not quite zero-sum) but even still the ability to do this is undesirable. This problem is weaker here than in a context where entropy is predictable to a medium length (eg. in the NXT RNG) but even still it is a concern.

A final concern is that in some cases, there will inevitably be multiple validators selected at a given height, and so the protocol will either need to support a facility for finalizing multiple blocks at a given height or accept that the protocol will be highly "competitive" in nature, in the event of a face-off between two blocks at one height likely favoring the validator that has faster connectivity to the network (a trait that sounds like it encourages high performance, but has the highly undesirable consequence that it encourages colocation, pooling and other forms of network centralization).

### Hybrid RANDAO / Private Randomness

One solution to get the "holy grail" of simultaneously having the unpredictability benefits of private randomness and RANDAO is to, quite literally, use both:

`F(i, b) = v_(b.height)[i] if xor(v_(b.height)[i], hash(i), RANDAO(b.parent)) < 2**256 / D else 0`

Where `RANDAO(b.parent)` is the state of the RANDAO, as defined in the RANDAO section above. This ensures that (i) the validator who will make the next block can see one block ahead but no further, and (ii) other validators cannot see ahead at all, essentially fully replicating the properties of proof of work. This is arguably optimal (and also removes all classes of grinding and manipulation vulnerabilities described above), but it comes at the cost of substantially more complexity: the protocol must (i) maintain both the private-randomness state and the RANDAO state, and (ii) have a mechanism for either managing the competitive nature of a protocol with potentially multiple validators selected per round or allowing multi-block finalization. Hence, for designs that aim for be simple, pure RANDAO with no private randomness may be optimal.
    
