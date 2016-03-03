from config import BLKTIME
from utils import DEBUG
import random

BRAVERY = 0.9375

# Takes as an argument a list of values and their associated weights
# and a fraction returns, returns the value such that the desired
# fraction of other values in the list, weighted by the given weights,
# is less than that value
def weighted_percentile(values, weights, frac):
    zipvals = sorted(zip(values, weights))
    target = sum(weights) * frac
    while target > zipvals[0][1]:
        target -= zipvals[0][1]
        zipvals.pop(0)
    return zipvals[0][0]


# Make a default bet on a block based on just personal info
def mk_initial_bet(blk_number, blk_hash, tr, genesis_time, now):
    scheduled_time = BLKTIME * blk_number + genesis_time
    received_time = tr.get(blk_hash, None)
    # If we already received a block...
    if received_time:
        time_delta = abs(received_time * 0.96 + now * 0.04 - scheduled_time)
        prob = 1 if time_delta < BLKTIME * 2 else 3.0 / (3.0 + time_delta / BLKTIME)
        DEBUG('Betting, block received', time_delta=time_delta, prob=prob)
        return 0.7 if random.random() < prob else 0.3
    # If we have not yet received a block...
    else:
        time_delta = now - scheduled_time
        prob = 1 if time_delta < BLKTIME * 2 else 3.0 / (3.0 + time_delta / BLKTIME)
        DEBUG('Betting, block not received', time_delta=time_delta, prob=prob)
        return 0.5 if random.random() < prob else 0.3


# Make a bet on a specific block
def bet_on_block(opinions, blk_number, blk_hash, tr, genesis_time, now):
    # Do we have the block?
    have_block = blk_hash and blk_hash in tr
    # The list of bet probabilities to use when producing one's own bet
    probs = []
    # Weights for each validator
    weights = []
    # My default opinion based on (i) whether or not I have the block,
    # (ii) when I saw it first if I do, and (iii) the current time
    default_bet = mk_initial_bet(blk_number, blk_hash, tr, genesis_time, now)
    # Go through others' opinions, check if they (i) are eligible to
    # bet, and (ii) have bet; if they have, add their bet to the
    # list of bets; otherwise, add the default bet in their place
    opinion_count = 0
    for i in opinions.keys():
        if opinions[i].induction_height <= blk_number < opinions[i].withdrawal_height and not opinions[i].withdrawn:
            p = opinions[i].get_prob(blk_number)
            # If this validator has not yet bet, then add our default bet
            if p is None:
                probs.append(default_bet)
            # If they bet toward a different block as the block hash currently being processed, then:
            # * if their probability is low, that means they are betting for the null case, so take their bet as is
            # * if their probability is high, that means that they are betting for a different block, so for this
            # block hash flip the bet as it's a bet against this particular block hash
            elif opinions[i].blockhashes[blk_number] != blk_hash and blk_hash is not None:
                probs.append(min(p, max(1 - p, 0.25)))
            # If they bet for the same block as is currently being processed, then take their bet as is
            else:
                probs.append(p)
            weights.append(opinions[i].deposit_size)
            opinion_count += (1 if p is not None else 0)
    # The algorithm for producing your own bet based on others' bets;
    # the intention is to converge toward 0 or 1
    p33 = weighted_percentile(probs, weights, 1/3.)
    p50 = weighted_percentile(probs, weights, 1/2.)
    p67 = weighted_percentile(probs, weights, 2/3.)
    if p33 > 0.8:
        o = BRAVERY + p33 * (1 - BRAVERY)
    elif p67 < 0.2:
        o = p67 * (1 - BRAVERY)
    else:
        o = min(0.85, max(0.15, p50 * 3 - (0.8 if have_block else 1.2)))
    return o

# Takes as input: (i) a list of other validators' opinions,
# (ii) a block height, (iii) a list of known blocks at that
# height, (iv) a hash -> time received map, (v) the genesis
# time, (vi) the current time
# Outputs a (block hash, probability, ask) combination where
# `ask` represents whether or not to send a network message
# asking for the block

def bet_at_height(opinions, h, known, time_received, genesis_time, now):
    # Determine candidate blocks
    candidates = [o.blockhashes[h] for o in opinions.values()
                  if len(o.blockhashes) > h and o.blockhashes[h] not in (None, '\x00' * 32)]
    for block in known:
        candidates.append(block.hash)
    if not len(candidates):
        candidates.append('\x00' * 32)
    candidates = list(set(candidates))
    # Locate highest probability
    probs = [(bet_on_block(opinions, h, c, time_received, genesis_time, now), c) for c in candidates]
    prob, new_block_hash = sorted(probs)[-1]
    if len(probs) >= 2:
        DEBUG('Voting on multiple candidates',
              height=h,
              options=[(a, b[:8].encode('hex')) for a, b in probs],
              winner=(prob, new_block_hash[:8].encode('hex')))
    # If we don't have a block, then confidently ask 
    if prob > 0.7 and new_block_hash not in time_received:
        return 0.7, new_block_hash, True
    else:
        return prob, new_block_hash, False
