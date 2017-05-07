import copy
import rlp
from viper import compiler
import serpent
from ethereum import utils, messages, transactions, abi, config
from ethereum.tools import tester2
from ethereum.hybrid_casper import casper_utils
from ethereum.hybrid_casper.casper_utils import mk_prepare, mk_commit, mk_status_flicker
from ethereum.slogging import configure_logging
config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace,eth.pb.msg:trace,eth.pb.tx:debug'
# configure_logging(config_string=config_string)


# The Casper-specific config declaration
casper_config = copy.deepcopy(config.default_config)
casper_config['HOMESTEAD_FORK_BLKNUM'] = 0
casper_config['ANTI_DOS_FORK_BLKNUM'] = 0
casper_config['CLEARING_FORK_BLKNUM'] = 0

k0, k1, k2, k3, k4, k5, k6, k7, k8, k9 = tester2.keys[:10]
a0, a1, a2, a3, a4, a5, a6, a7, a8, a9 = tester2.accounts[:10]

EPOCH_LENGTH = 100
SLASH_DELAY = 8640

code_template = """
~calldatacopy(0, 0, 128)
~call(3000, 1, 0, 0, 128, 0, 32)
return(~mload(0) == %s)
"""

def mk_validation_code(address):
    return serpent.compile(code_template % (utils.checksum_encode(address)))

def make_casper_chain():
    t = tester2.Chain(alloc={a: {'balance': 5*10**19} for a in tester2.accounts[:10]}, env=config.Env(config=casper_config))

    def inject_tx(txhex):
        tx = rlp.decode(utils.decode_hex(txhex[2:]), transactions.Transaction)
        t.head_state.set_balance(tx.sender, tx.startgas * tx.gasprice)
        t.chain.state.set_balance(tx.sender, tx.startgas * tx.gasprice)
        success, output = messages.apply_transaction(t.head_state, tx)
        t.block.transactions.append(tx)
        t.mine()
        contract_address = utils.mk_contract_address(tx.sender, 0)
        assert success
        assert t.chain.state.get_code(contract_address)
        return contract_address


    # Install RLP decoder library
    rlp_decoder_address = inject_tx('0xf90237808506fc23ac00830330888080b902246102128061000e60003961022056600060007f010000000000000000000000000000000000000000000000000000000000000060003504600060c082121515585760f882121561004d5760bf820336141558576001905061006e565b600181013560f783036020035260005160f6830301361415585760f6820390505b5b368112156101c2577f010000000000000000000000000000000000000000000000000000000000000081350483602086026040015260018501945060808112156100d55760018461044001526001828561046001376001820191506021840193506101bc565b60b881121561014357608081038461044001526080810360018301856104600137608181141561012e5760807f010000000000000000000000000000000000000000000000000000000000000060018401350412151558575b607f81038201915060608103840193506101bb565b60c08112156101b857600182013560b782036020035260005160388112157f010000000000000000000000000000000000000000000000000000000000000060018501350402155857808561044001528060b6838501038661046001378060b6830301830192506020810185019450506101ba565bfe5b5b5b5061006f565b601f841315155857602060208502016020810391505b6000821215156101fc578082604001510182826104400301526020820391506101d8565b808401610420528381018161044003f350505050505b6000f31b2d4f')

    # Install sig hasher

    t.chain.state.set_balance('0x6e7406512b244843c1171840dfcd3d7532d979fe', 7291200000000000)
    t.head_state.set_balance('0x6e7406512b244843c1171840dfcd3d7532d979fe', 7291200000000000)

    sighasher_address = inject_tx('0xf9016d808506fc23ac0083026a508080b9015a6101488061000e6000396101565660007f01000000000000000000000000000000000000000000000000000000000000006000350460f8811215610038576001915061003f565b60f6810391505b508060005b368312156100c8577f01000000000000000000000000000000000000000000000000000000000000008335048391506080811215610087576001840193506100c2565b60b881121561009d57607f8103840193506100c1565b60c08112156100c05760b68103600185013560b783036020035260005101840193505b5b5b50610044565b81810360388112156100f4578060c00160005380836001378060010160002060e052602060e0f3610143565b61010081121561010557600161011b565b6201000081121561011757600261011a565b60035b5b8160005280601f038160f701815382856020378282600101018120610140526020610140f350505b505050505b6000f31b2d4f')

    # Install purity checker

    purity_checker_address = inject_tx('0xf90467808506fc23ac00830583c88080b904546104428061000e60003961045056600061033f537c0100000000000000000000000000000000000000000000000000000000600035047f80010000000000000000000000000000000000000030ffff1c0e00000000000060205263a1903eab8114156103f7573659905901600090523660048237600435608052506080513b806020015990590160009052818152602081019050905060a0526080513b600060a0516080513c6080513b8060200260200159905901600090528181526020810190509050610100526080513b806020026020015990590160009052818152602081019050905061016052600060005b602060a05103518212156103c957610100601f8360a051010351066020518160020a161561010a57fe5b80606013151561011e57607f811315610121565b60005b1561014f5780607f036101000a60018460a0510101510482602002610160510152605e8103830192506103b2565b60f18114801561015f5780610164565b60f282145b905080156101725780610177565b60f482145b9050156103aa5760028212151561019e5760606001830360200261010051015112156101a1565b60005b156101bc57607f6001830360200261010051015113156101bf565b60005b156101d157600282036102605261031e565b6004821215156101f057600360018303602002610100510151146101f3565b60005b1561020d57605a6002830360200261010051015114610210565b60005b1561022b57606060038303602002610100510151121561022e565b60005b1561024957607f60038303602002610100510151131561024c565b60005b1561025e57600482036102605261031d565b60028212151561027d57605a6001830360200261010051015114610280565b60005b1561029257600282036102605261031c565b6002821215156102b157609060018303602002610100510151146102b4565b60005b156102c657600282036102605261031b565b6002821215156102e65760806001830360200261010051015112156102e9565b60005b156103035760906001830360200261010051015112610306565b60005b1561031857600282036102605261031a565bfe5b5b5b5b5b604060405990590160009052600081526102605160200261016051015181602001528090502054156103555760016102a052610393565b60306102605160200261010051015114156103755760016102a052610392565b60606102605160200261010051015114156103915760016102a0525b5b5b6102a051151561039f57fe5b6001830192506103b1565b6001830192505b5b8082602002610100510152600182019150506100e0565b50506001604060405990590160009052600081526080518160200152809050205560016102e05260206102e0f35b63c23697a8811415610440573659905901600090523660048237600435608052506040604059905901600090526000815260805181602001528090502054610300526020610300f35b505b6000f31b2d4f')

    ct = abi.ContractTranslator([{'name': 'check(address)', 'type': 'function', 'constant': True, 'inputs': [{'name': 'addr', 'type': 'address'}], 'outputs': [{'name': 'out', 'type': 'bool'}]}, {'name': 'submit(address)', 'type': 'function', 'constant': False, 'inputs': [{'name': 'addr', 'type': 'address'}], 'outputs': [{'name': 'out', 'type': 'bool'}]}])
    # Check that the RLP decoding library and the sig hashing library are "pure"
    assert utils.big_endian_to_int(t.tx(k0, purity_checker_address, 0, ct.encode('submit', [rlp_decoder_address]))) == 1
    assert utils.big_endian_to_int(t.tx(k0, purity_checker_address, 0, ct.encode('submit', [sighasher_address]))) == 1

    k1_valcode_addr = t.tx(k0, "", 0, mk_validation_code(a0))
    assert utils.big_endian_to_int(t.tx(k0, purity_checker_address, 0, ct.encode('submit', [k1_valcode_addr]))) == 1

    # Install Casper

    casper_code = casper_utils.casper_contract.decode('utf8').replace('epoch_length = 100', 'epoch_length = ' + str(EPOCH_LENGTH)) \
                                              .replace('insufficiency_slash_delay = 86400', 'insufficiency_slash_delay = ' + str(SLASH_DELAY)) \
                                              .replace('0x1Db3439a222C519ab44bb1144fC28167b4Fa6EE6', utils.checksum_encode(k1_valcode_addr)) \
                                              .replace('0x476c2cA9a7f3B16FeCa86512276271FAf63B6a24', utils.checksum_encode(sighasher_address)) \
                                              .replace('0xD7a3BD6C9eA32efF147d067f907AE6b22d436F91', utils.checksum_encode(purity_checker_address))

    print('Casper code length', len(compiler.compile(casper_code)))
    casper = t.contract(casper_code, language='viper', startgas=4096181)
    print('Gas consumed to launch Casper', t.chain.state.receipts[-1].gas_used - t.chain.state.receipts[-2].gas_used)
    t.mine()
    return t, casper, purity_checker_address, ct

# Helper function for gettting blockhashes by epoch, based on the current chain
def epoch_blockhash(epoch):
    if epoch == 0:
        return b'\x00' * 32
    return t.chain.get_blockhash_by_number(epoch*EPOCH_LENGTH)

def mine_and_init_epochs(number_of_epochs):
    distance_to_next_epoch = (EPOCH_LENGTH - t.chain.state.block_number) % EPOCH_LENGTH
    t.mine(number_of_blocks=distance_to_next_epoch)
    casper.initialize_epoch(t.chain.state.block_number // EPOCH_LENGTH)
    for i in range(number_of_epochs-1):
        print("Initializing epoch", t.chain.state.block_number // EPOCH_LENGTH)
        t.mine(number_of_blocks=EPOCH_LENGTH)
        casper.initialize_epoch(t.chain.state.block_number // EPOCH_LENGTH)
    print("Initializing epoch", t.chain.state.block_number // EPOCH_LENGTH)
    t.mine(number_of_blocks=2)

# Begin the test

print("Starting tests")
t, casper, purity_checker_address, ct = make_casper_chain()
casper.initiate()
# Initialize the first epoch
mine_and_init_epochs(1)
assert casper.get_nextValidatorIndex() == 1
print("Epoch initialized")
print("Reward factor: %.8f" % (casper.get_reward_factor() * 2 / 3))
# Send a prepare message
# configure_logging(config_string=config_string)
casper.prepare(mk_prepare(0, 1, epoch_blockhash(1), epoch_blockhash(0), 0, epoch_blockhash(0), k0))
print('Gas consumed for a prepare: %d (including %d intrinsic gas)' %
      (t.chain.state.receipts[-1].gas_used, t.last_tx.intrinsic_gas_used))
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
      (t.chain.state.receipts[-1].gas_used, t.last_tx.intrinsic_gas_used))
# Check that we committed
assert casper.get_consensus_messages__committed(1)
print("Commit message processed")
# Initialize the second epoch
mine_and_init_epochs(1)
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
mine_and_init_epochs(1)
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
mine_and_init_epochs(1)
assert casper.get_dynasty() == 3
epoch_4_anchash = utils.sha3(epoch_blockhash(4) + epoch_3_anchash)
# Not publishing this prepare for the time being
p4 = mk_prepare(0, 4, epoch_blockhash(4), '\x12' * 32, 3, '\x24' * 32, k0)
# Initialize the fifth epoch
mine_and_init_epochs(1)
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
mine_and_init_epochs(epoch_inc)
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
t, casper, purity_checker_address, ct = make_casper_chain()
casper.initiate()

# Initialize the first epoch
mine_and_init_epochs(1)
assert casper.get_nextValidatorIndex() == 1
assert casper.get_dynasty() == 0
assert casper.get_current_epoch() == 1
assert casper.get_consensus_messages__ancestry_hash_justified(0, b'\x00' * 32)
print("Epoch 1 initialized")
for k in (k1, k2, k3, k4, k5, k6):
    valcode_addr = t.tx(k0, '', 0, mk_validation_code(utils.privtoaddr(k)))
    assert utils.big_endian_to_int(t.call(k0, purity_checker_address, 0, ct.encode('submit', [valcode_addr]))) == 1
    casper.deposit(valcode_addr, utils.privtoaddr(k), value=3 * 10**18)
    t.mine()
print("Processed 6 deposits")
casper.prepare(mk_prepare(0, 1, epoch_blockhash(1), epoch_blockhash(0), 0, epoch_blockhash(0), k0))
casper.commit(mk_commit(0, 1, epoch_blockhash(1), 0, k0))
epoch_1_anchash = utils.sha3(epoch_blockhash(1) + epoch_blockhash(0))
assert casper.get_consensus_messages__committed(1)
print("Prepared and committed")
mine_and_init_epochs(1)
print("Epoch 2 initialized")
assert casper.get_dynasty() == 1
casper.prepare(mk_prepare(0, 2, epoch_blockhash(2), epoch_1_anchash, 1, epoch_1_anchash, k0))
casper.commit(mk_commit(0, 2, epoch_blockhash(2), 1, k0))
epoch_2_anchash = utils.sha3(epoch_blockhash(2) + epoch_1_anchash)
casper.get_consensus_messages__committed(2)
print("Confirmed that one key is still sufficient to prepare and commit")
mine_and_init_epochs(1)
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
mine_and_init_epochs(1)
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
mine_and_init_epochs(1)
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
mine_and_init_epochs(1)
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
mine_and_init_epochs(1)
assert casper.get_dynasty() == 6
print("Epoch 7 initialized")
# Here three prepares and three commits should be sufficient!
epoch_7_anchash = utils.sha3(epoch_blockhash(7) + epoch_6_anchash)
for i, k in enumerate([k0, k1, k2]):
    #if i == 1:
    #    configure_logging(config_string=config_string)
    casper.prepare(mk_prepare(i, 7, epoch_blockhash(7), epoch_6_anchash, 6, epoch_6_anchash, k))
    print('Gas consumed for prepare', i, t.chain.state.receipts[-1].gas_used)
    t.mine()
    #if i == 1:
    #    import sys
    #    sys.exit()
for i, k in enumerate([k0, k1, k2]):
    casper.commit(mk_commit(i, 7, epoch_blockhash(7), 6, k))
    print('Gas consumed for prepare', i, t.chain.state.receipts[-1].gas_used)
    t.mine()
assert casper.get_consensus_messages__committed(7)
print("Three of four prepares and commits sufficient")
# Start epoch 8 / dynasty 7
mine_and_init_epochs(1)
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
