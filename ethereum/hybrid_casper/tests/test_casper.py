from ethereum import utils
from ethereum.tools import tester2
from ethereum.hybrid_casper import casper_utils
from ethereum.hybrid_casper.casper_utils import mk_prepare, mk_commit, mk_status_flicker
# from ethereum.slogging import configure_logging
# config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace,eth.pb.msg:trace,eth.pb.tx:debug'
# configure_logging(config_string=config_string)

EPOCH_LENGTH = 23
SLASH_DELAY = 864
ALLOC = {a: {'balance': 5*10**19} for a in tester2.accounts[:10]}
k0, k1, k2, k3, k4, k5, k6, k7, k8, k9 = tester2.keys[:10]
a0, a1, a2, a3, a4, a5, a6, a7, a8, a9 = tester2.accounts[:10]

def init_chain_and_casper():
    genesis = casper_utils.make_casper_genesis(k0, ALLOC, EPOCH_LENGTH, SLASH_DELAY)
    casper_address = utils.mk_contract_address(a0, genesis.get_nonce(a0) - 1)
    t = tester2.Chain(genesis)
    casper = tester2.ABIContract(t, casper_utils.casper_abi, casper_address)
    casper.initiate()
    t.mine()
    return t, casper

# Helper function for gettting blockhashes by epoch, based on the current chain
def epoch_blockhash(epoch):
    if epoch == 0:
        return b'\x00' * 32
    return t.head_state.prev_headers[epoch*EPOCH_LENGTH * -1 - 1].hash

# Mines blocks required for number_of_epochs epoch changes, plus an offset of 2 blocks
def mine_epochs(number_of_epochs):
    distance_to_next_epoch = (EPOCH_LENGTH - t.head_state.block_number) % EPOCH_LENGTH
    number_of_blocks = distance_to_next_epoch + EPOCH_LENGTH*(number_of_epochs-1) + 2
    t.mine(number_of_blocks=number_of_blocks)

print("Starting tests")
t, casper = init_chain_and_casper()
start_hash = t.chain.head_hash
# Initialize the first epoch
mine_epochs(1)
assert casper.get_nextValidatorIndex() == 1
print("Epoch initialized")
print("Reward factor: %.8f" % (casper.get_reward_factor() * 2 / 3))
# Send a prepare message
# configure_logging(config_string=config_string)
casper.prepare(mk_prepare(0, 1, epoch_blockhash(1), epoch_blockhash(0), 0, epoch_blockhash(0), k0))
print('Gas consumed for a prepare: %d (including %d intrinsic gas)' %
      (t.head_state.receipts[-1].gas_used, t.last_tx.intrinsic_gas_used))
epoch_1_anchash = utils.sha3(epoch_blockhash(1) + epoch_blockhash(0))
assert casper.get_consensus_messages__hash_justified(1, epoch_blockhash(1))
assert casper.get_consensus_messages__ancestry_hash_justified(1, epoch_1_anchash)
print("Prepare message processed")
try:
    casper.prepare(mk_prepare(0, 1, epoch_blockhash(1), epoch_blockhash(0), 0, epoch_blockhash(0), k0))
    success = True
except:
    success = False
assert not success
t.mine()
print("Prepare message fails the second time")
# Send a commit message
print('commit!', casper.commit(mk_commit(0, 1, epoch_blockhash(1), 0, k0)))
print('Gas consumed for a commit: %d (including %d intrinsic gas)' %
      (t.head_state.receipts[-1].gas_used, t.last_tx.intrinsic_gas_used))
# Check that we committed
assert casper.get_consensus_messages__committed(1)
print("Commit message processed")
# Initialize the second epoch
mine_epochs(1)
# Check that the dynasty increased as expected
assert casper.get_dynasty() == 1
print("Second epoch initialized, dynasty increased as expected")
# Send a prepare message
casper.prepare(mk_prepare(0, 2, epoch_blockhash(2), epoch_1_anchash, 1, epoch_1_anchash, k0))
# Save the total deposits after the prepare for later
post_prepare_deposits = casper.get_total_deposits(1)
# Send a commit message
epoch_2_commit = mk_commit(0, 2, epoch_blockhash(2), 1, k0)
casper.commit(epoch_2_commit)
epoch_2_anchash = utils.sha3(epoch_blockhash(2) + epoch_1_anchash)
assert casper.get_consensus_messages__ancestry_hash_justified(2, epoch_2_anchash)
# Check that we committed
assert casper.get_consensus_messages__committed(2)
# Check that the reward was given for the prepare and commit
assert post_prepare_deposits - casper.get_total_deposits(0) > 0
assert casper.get_total_deposits(1) - post_prepare_deposits > 0
print('Initial deposits: %d, post-prepare: %d, post-commit: %d' % (casper.get_total_deposits(0), post_prepare_deposits, casper.get_total_deposits(1)))
# Initialize the third epoch
mine_epochs(1)
print("Second epoch prepared and committed, third epoch initialized")
# Test the NO_DBL_PREPARE slashing condition
p1 = mk_prepare(0, 3, epoch_blockhash(3), epoch_2_anchash, 2, epoch_2_anchash, k0)
p2 = mk_prepare(0, 3, '\x57' * 32, epoch_2_anchash, 2, epoch_2_anchash, k0)
snapshot = t.snapshot()
casper.double_prepare_slash(p1, p2)
t.revert(snapshot)
print("NO_DBL_PREPARE slashing condition works")
# Test the PREPARE_COMMIT_CONSISTENCY slashing condition
p3 = mk_prepare(0, 3, epoch_blockhash(3), epoch_2_anchash, 0, epoch_blockhash(0), k0)
snapshot = t.snapshot()
casper.prepare_commit_inconsistency_slash(p3, epoch_2_commit)
t.revert(snapshot)
print("PREPARE_COMMIT_CONSISTENCY slashing condition works")
# Finish the third epoch
casper.prepare(p1)
casper.commit(mk_commit(0, 3, epoch_blockhash(3), 2, k0))
epoch_3_anchash = utils.sha3(epoch_blockhash(3) + epoch_2_anchash)
assert casper.get_consensus_messages__ancestry_hash_justified(3, epoch_3_anchash)
assert casper.get_consensus_messages__committed(3)
# Initialize the fourth epoch. Not doing prepares or commits during this epoch.
mine_epochs(1)
assert casper.get_dynasty() == 3
epoch_4_anchash = utils.sha3(epoch_blockhash(4) + epoch_3_anchash)
# Not publishing this prepare for the time being
p4 = mk_prepare(0, 4, epoch_blockhash(4), '\x12' * 32, 3, '\x24' * 32, k0)
# Initialize the fifth epoch
mine_epochs(1)
print("Epochs up to 5 initialized")
# Dynasty not incremented because no commits were made
assert casper.get_dynasty() == 3
epoch_5_anchash = utils.sha3(epoch_blockhash(4) + epoch_4_anchash)
p5 = mk_prepare(0, 5, epoch_blockhash(4), epoch_4_anchash, 3, epoch_3_anchash, k0)
casper.prepare(p5)  # Prepare works, and no reward is given
# Test the COMMIT_REQ slashing condition
kommit = mk_commit(0, 5, b'\x80' * 32, 3, k0)
epoch_inc = 1 + int(SLASH_DELAY / 14 / EPOCH_LENGTH)
print("Speeding up time to test remaining two slashing conditions")
mine_epochs(epoch_inc)
print("Epochs up to %d initialized" % (6 + epoch_inc))
snapshot = t.snapshot()
casper.commit_non_justification_slash(kommit)
t.revert(snapshot)
try:
    casper.commit_non_justification_slash(epoch_2_commit)
    success = True
except:
    success = False
assert not success
t.mine()
print("COMMIT_REQ slashing condition works")
# Test the PREPARE_REQ slashing condition
casper.derive_parenthood(epoch_3_anchash, epoch_blockhash(4), epoch_4_anchash)
t.mine()
assert casper.get_ancestry(epoch_3_anchash, epoch_4_anchash) == 1
assert casper.get_ancestry(epoch_4_anchash, epoch_5_anchash) == 1
casper.derive_ancestry(epoch_3_anchash, epoch_4_anchash, epoch_5_anchash)
t.mine()
assert casper.get_ancestry(epoch_3_anchash, epoch_5_anchash) == 2
t.mine()
snapshot = t.snapshot()
casper.prepare_non_justification_slash(p4)
t.revert(snapshot)
try:
    casper.prepare_non_justification_slash(p5)
    success = True
except:
    success = False
assert not success
print("PREPARE_REQ slashing condition works")

print("Creating a new chain for test 2")
# Create a new chain
t.change_head(start_hash)
# Initialize the first epoch
mine_epochs(1)
assert casper.get_nextValidatorIndex() == 1
assert casper.get_dynasty() == 0
assert casper.get_current_epoch() == 1
assert casper.get_consensus_messages__ancestry_hash_justified(0, b'\x00' * 32)
print("Epoch 1 initialized")
for k in (k1, k2, k3, k4, k5, k6):
    valcode_addr = t.tx(k0, '', 0, casper_utils.mk_validation_code(utils.privtoaddr(k)))
    assert utils.big_endian_to_int(t.call(k0, casper_utils.purity_checker_address, 0, casper_utils.ct.encode('submit', [valcode_addr]))) == 1
    casper.deposit(valcode_addr, utils.privtoaddr(k), value=3 * 10**18)
    t.mine()
print("Processed 6 deposits")
casper.prepare(mk_prepare(0, 1, epoch_blockhash(1), epoch_blockhash(0), 0, epoch_blockhash(0), k0))
casper.commit(mk_commit(0, 1, epoch_blockhash(1), 0, k0))
epoch_1_anchash = utils.sha3(epoch_blockhash(1) + epoch_blockhash(0))
assert casper.get_consensus_messages__committed(1)
print("Prepared and committed")
mine_epochs(1)
print("Epoch 2 initialized")
assert casper.get_dynasty() == 1
casper.prepare(mk_prepare(0, 2, epoch_blockhash(2), epoch_1_anchash, 1, epoch_1_anchash, k0))
casper.commit(mk_commit(0, 2, epoch_blockhash(2), 1, k0))
epoch_2_anchash = utils.sha3(epoch_blockhash(2) + epoch_1_anchash)
casper.get_consensus_messages__committed(2)
print("Confirmed that one key is still sufficient to prepare and commit")
mine_epochs(1)
print("Epoch 3 initialized")
assert casper.get_dynasty() == 2
assert 3 * 10**18 <= casper.get_total_deposits(0) < 4 * 10**18
assert 3 * 10**18 <= casper.get_total_deposits(1) < 4 * 10**18
assert 21 * 10**18 <= casper.get_total_deposits(2) < 22 * 10**18
print("Confirmed new total_deposits")
try:
    casper.flick_status(mk_status_flicker(0, 3, 0, k1))
    success = True
except:
    success = False
assert not success
t.mine()
# Log out
casper.flick_status(mk_status_flicker(4, 3, 0, k4))
casper.flick_status(mk_status_flicker(5, 3, 0, k5))
casper.flick_status(mk_status_flicker(6, 3, 0, k6))
print("Logged out three validators")
# Validators leave the fwd validator set in dynasty 4
assert casper.get_validators__dynasty_end(4) == 4
epoch_3_anchash = utils.sha3(epoch_blockhash(3) + epoch_2_anchash)
# Prepare from one validator
casper.prepare(mk_prepare(0, 3, epoch_blockhash(3), epoch_2_anchash, 2, epoch_2_anchash, k0))
# Not prepared yet
assert not casper.get_consensus_messages__hash_justified(3, epoch_blockhash(3))
print("Prepare from one validator no longer sufficient")
# Prepare from 3 more validators
for i, k in ((1, k1), (2, k2), (3, k3)):
    casper.prepare(mk_prepare(i, 3, epoch_blockhash(3), epoch_2_anchash, 2, epoch_2_anchash, k))
    t.mine()
# Still not prepared
assert not casper.get_consensus_messages__hash_justified(3, epoch_blockhash(3))
print("Prepare from four of seven validators still not sufficient")
# Prepare from a fifth validator
casper.prepare(mk_prepare(4, 3, epoch_blockhash(3), epoch_2_anchash, 2, epoch_2_anchash, k4))
# NOW we're prepared!
assert casper.get_consensus_messages__hash_justified(3, epoch_blockhash(3))
print("Prepare from five of seven validators sufficient!")
# Five commits
for i, k in enumerate([k0, k1, k2, k3, k4]):
    casper.commit(mk_commit(i, 3, epoch_blockhash(3), 2 if i == 0 else 0, k))
    t.mine()
# And we committed!
assert casper.get_consensus_messages__committed(3)
print("Commit from five of seven validators sufficient")
# Start epoch 4
mine_epochs(1)
assert casper.get_dynasty() == 3
print("Epoch 4 initialized")
# Prepare and commit
epoch_4_anchash = utils.sha3(epoch_blockhash(4) + epoch_3_anchash)
for i, k in enumerate([k0, k1, k2, k3, k4]):
    casper.prepare(mk_prepare(i, 4, epoch_blockhash(4), epoch_3_anchash, 3, epoch_3_anchash, k))
    t.mine()
for i, k in enumerate([k0, k1, k2, k3, k4]):
    casper.commit(mk_commit(i, 4, epoch_blockhash(4), 3, k))
    t.mine()
assert casper.get_consensus_messages__committed(4)
print("Prepared and committed")
# Start epoch 5 / dynasty 4
mine_epochs(1)
print("Epoch 5 initialized")
assert casper.get_dynasty() == 4
assert 21 * 10**18 <= casper.get_total_deposits(3) <= 22 * 10**18
assert 12 * 10**18 <= casper.get_total_deposits(4) <= 13 * 10**18
epoch_5_anchash = utils.sha3(epoch_blockhash(5) + epoch_4_anchash)
# Do three prepares
for i, k in enumerate([k0, k1, k2]):
    casper.prepare(mk_prepare(i, 5, epoch_blockhash(5), epoch_4_anchash, 4, epoch_4_anchash, k))
    t.mine()
# Three prepares are insufficient because there are still five validators in the rear validator set
assert not casper.get_consensus_messages__hash_justified(5, epoch_blockhash(5))
print("Three prepares insufficient, as rear validator set still has seven")
# Do two more prepares
for i, k in [(3, k3), (4, k4)]:
    casper.prepare(mk_prepare(i, 5, epoch_blockhash(5), epoch_4_anchash, 4, epoch_4_anchash, k))
    t.mine()
# Now we're good!
assert casper.get_consensus_messages__hash_justified(5, epoch_blockhash(5))
print("Five prepares sufficient")
for i, k in enumerate([k0, k1, k2, k3, k4]):
    casper.commit(mk_commit(i, 5, epoch_blockhash(5), 4, k))
    t.mine()
# Committed!
assert casper.get_consensus_messages__committed(5)
# Start epoch 6 / dynasty 5
mine_epochs(1)
assert casper.get_dynasty() == 5
print("Epoch 6 initialized")
# Log back in
old_deposit_start = casper.get_dynasty_start_epoch(casper.get_validators__dynasty_start(4))
old_deposit_end = casper.get_dynasty_start_epoch(casper.get_validators__dynasty_end(4) + 1)
old_deposit = casper.get_validators__deposit(4)
# Explanation:
# * During dynasty 0, the validator deposited, so he joins the current set in dynasty 2
#   (epoch 3), and the previous set in dynasty 3 (epoch 4)
# * During dynasty 2, the validator logs off, so he leaves the current set in dynasty 4
#   (epoch 5) and the previous set in dynasty 5 (epoch 6)
assert [casper.check_eligible_in_epoch(4, i) for i in range(7)] == [0, 0, 0, 2, 3, 1, 0]
casper.flick_status(mk_status_flicker(4, 6, 1, k4))
t.mine()
# Explanation:
# * During dynasty 7, the validator will log on again. Hence, the dynasty mask
#   should include dynasties 4, 5, 6
assert [casper.check_eligible_in_epoch(4, i) for i in range(7)] == [0, 0, 0, 2, 3, 1, 0]
new_deposit = casper.get_validators__deposit(4)
print("One validator logging back in")
print("Penalty from %d epochs: %.4f" % (old_deposit_end - old_deposit_start, 1 - new_deposit / old_deposit))
assert casper.get_validators__dynasty_start(4) == 7
# Here three prepares and three commits should be sufficient!
epoch_6_anchash = utils.sha3(epoch_blockhash(6) + epoch_5_anchash)
for i, k in enumerate([k0, k1, k2]):
    casper.prepare(mk_prepare(i, 6, epoch_blockhash(6), epoch_5_anchash, 5, epoch_5_anchash, k))
    t.mine()
for i, k in enumerate([k0, k1, k2]):
    casper.commit(mk_commit(i, 6, epoch_blockhash(6), 5, k))
    t.mine()
assert casper.get_consensus_messages__committed(6)
print("Three of four prepares and commits sufficient")
# Start epoch 7 / dynasty 6
mine_epochs(1)
assert casper.get_dynasty() == 6
print("Epoch 7 initialized")
# Here three prepares and three commits should be sufficient!
epoch_7_anchash = utils.sha3(epoch_blockhash(7) + epoch_6_anchash)
for i, k in enumerate([k0, k1, k2]):
    # if i == 1:
    #     configure_logging(config_string=config_string)
    casper.prepare(mk_prepare(i, 7, epoch_blockhash(7), epoch_6_anchash, 6, epoch_6_anchash, k))
    print('Gas consumed for prepare', i, t.head_state.receipts[-1].gas_used)
    t.mine()
    # if i == 1:
    #     import sys
    #     sys.exit()
for i, k in enumerate([k0, k1, k2]):
    casper.commit(mk_commit(i, 7, epoch_blockhash(7), 6, k))
    print('Gas consumed for prepare', i, t.head_state.receipts[-1].gas_used)
    t.mine()
assert casper.get_consensus_messages__committed(7)
print("Three of four prepares and commits sufficient")
# Start epoch 8 / dynasty 7
mine_epochs(1)
assert casper.get_dynasty() == 7
print("Epoch 8 initialized")
assert 12 * 10**18 <= casper.get_total_deposits(6) <= 13 * 10**18
assert 15 * 10**18 <= casper.get_total_deposits(7) <= 16 * 10**18
epoch_8_anchash = utils.sha3(epoch_blockhash(8) + epoch_7_anchash)
# Do three prepares
for i, k in enumerate([k0, k1, k2]):
    casper.prepare(mk_prepare(i, 8, epoch_blockhash(8), epoch_7_anchash, 7, epoch_7_anchash, k))
    t.mine()
# Three prepares are insufficient because there are still five validators in the rear validator set
assert not casper.get_consensus_messages__hash_justified(8, epoch_blockhash(8))
print("Three prepares no longer sufficient, as the forward validator set has five validators")
# Do one more prepare
for i, k in [(3, k3)]:
    casper.prepare(mk_prepare(i, 8, epoch_blockhash(8), epoch_7_anchash, 7, epoch_7_anchash, k))
    t.mine()
# Now we're good!
assert casper.get_consensus_messages__hash_justified(8, epoch_blockhash(8))
print("Four of five prepares sufficient")
for i, k in enumerate([k0, k1, k2, k3, k4]):
    casper.commit(mk_commit(i, 8, epoch_blockhash(8), 7 if i < 3 else 5, k))
    t.mine()
assert casper.get_consensus_messages__committed(8)
print("Committed")
# Validator rejoins current validator set in epoch 8
assert [casper.check_eligible_in_epoch(4, i) for i in range(9)] == [0, 0, 0, 2, 3, 1, 0, 0, 2]

print("All tests passed")
