import copy
import rlp
import serpent
import os
import sys

from ethereum import utils, messages, transactions, abi, genesis_helpers, config
from ethereum.transactions import Transaction
from ethereum.hybrid_casper import consensus
from ethereum.abi import ContractTranslator
from viper import compiler

gasprice = 25 * 10**9

# Install RLP decoder library
viper_rlp_decoder_tx = rlp.hex_decode("0xf90237808506fc23ac00830330888080b902246102128061000e60003961022056600060007f010000000000000000000000000000000000000000000000000000000000000060003504600060c082121515585760f882121561004d5760bf820336141558576001905061006e565b600181013560f783036020035260005160f6830301361415585760f6820390505b5b368112156101c2577f010000000000000000000000000000000000000000000000000000000000000081350483602086026040015260018501945060808112156100d55760018461044001526001828561046001376001820191506021840193506101bc565b60b881121561014357608081038461044001526080810360018301856104600137608181141561012e5760807f010000000000000000000000000000000000000000000000000000000000000060018401350412151558575b607f81038201915060608103840193506101bb565b60c08112156101b857600182013560b782036020035260005160388112157f010000000000000000000000000000000000000000000000000000000000000060018501350402155857808561044001528060b6838501038661046001378060b6830301830192506020810185019450506101ba565bfe5b5b5b5061006f565b601f841315155857602060208502016020810391505b6000821215156101fc578082604001510182826104400301526020820391506101d8565b808401610420528381018161044003f350505050505b6000f31b2d4f", Transaction)

# Install sig hasher
sig_hasher_tx = rlp.hex_decode("0xf9016d808506fc23ac0083026a508080b9015a6101488061000e6000396101565660007f01000000000000000000000000000000000000000000000000000000000000006000350460f8811215610038576001915061003f565b60f6810391505b508060005b368312156100c8577f01000000000000000000000000000000000000000000000000000000000000008335048391506080811215610087576001840193506100c2565b60b881121561009d57607f8103840193506100c1565b60c08112156100c05760b68103600185013560b783036020035260005101840193505b5b5b50610044565b81810360388112156100f4578060c00160005380836001378060010160002060e052602060e0f3610143565b61010081121561010557600161011b565b6201000081121561011757600261011a565b60035b5b8160005280601f038160f701815382856020378282600101018120610140526020610140f350505b505050505b6000f31b2d4f", Transaction)

# Install purity checker
purity_checker_tx = rlp.hex_decode("0xf90467808506fc23ac00830583c88080b904546104428061000e60003961045056600061033f537c0100000000000000000000000000000000000000000000000000000000600035047f80010000000000000000000000000000000000000030ffff1c0e00000000000060205263a1903eab8114156103f7573659905901600090523660048237600435608052506080513b806020015990590160009052818152602081019050905060a0526080513b600060a0516080513c6080513b8060200260200159905901600090528181526020810190509050610100526080513b806020026020015990590160009052818152602081019050905061016052600060005b602060a05103518212156103c957610100601f8360a051010351066020518160020a161561010a57fe5b80606013151561011e57607f811315610121565b60005b1561014f5780607f036101000a60018460a0510101510482602002610160510152605e8103830192506103b2565b60f18114801561015f5780610164565b60f282145b905080156101725780610177565b60f482145b9050156103aa5760028212151561019e5760606001830360200261010051015112156101a1565b60005b156101bc57607f6001830360200261010051015113156101bf565b60005b156101d157600282036102605261031e565b6004821215156101f057600360018303602002610100510151146101f3565b60005b1561020d57605a6002830360200261010051015114610210565b60005b1561022b57606060038303602002610100510151121561022e565b60005b1561024957607f60038303602002610100510151131561024c565b60005b1561025e57600482036102605261031d565b60028212151561027d57605a6001830360200261010051015114610280565b60005b1561029257600282036102605261031c565b6002821215156102b157609060018303602002610100510151146102b4565b60005b156102c657600282036102605261031b565b6002821215156102e65760806001830360200261010051015112156102e9565b60005b156103035760906001830360200261010051015112610306565b60005b1561031857600282036102605261031a565bfe5b5b5b5b5b604060405990590160009052600081526102605160200261016051015181602001528090502054156103555760016102a052610393565b60306102605160200261010051015114156103755760016102a052610392565b60606102605160200261010051015114156103915760016102a0525b5b5b6102a051151561039f57fe5b6001830192506103b1565b6001830192505b5b8082602002610100510152600182019150506100e0565b50506001604060405990590160009052600081526080518160200152809050205560016102e05260206102e0f35b63c23697a8811415610440573659905901600090523660048237600435608052506040604059905901600090526000815260805181602001528090502054610300526020610300f35b505b6000f31b2d4f", Transaction)

purity_checker_address = purity_checker_tx.creates
purity_checker_abi = [{'name': 'check(address)', 'type': 'function', 'constant': True, 'inputs': [{'name': 'addr', 'type': 'address'}], 'outputs': [{'name': 'out', 'type': 'bool'}]}, {'name': 'submit(address)', 'type': 'function', 'constant': False, 'inputs': [{'name': 'addr', 'type': 'address'}], 'outputs': [{'name': 'out', 'type': 'bool'}]}]
viper_rlp_decoder_address = viper_rlp_decoder_tx.creates
sig_hasher_address = sig_hasher_tx.creates

# casper contract related
ethereum_path = os.path.dirname(sys.modules['ethereum'].__file__)
casper_contract_path = '/'.join((ethereum_path, '..', 'casper', 'casper', 'contracts', 'simple_casper.v.py'))
casper_code = open(casper_contract_path).read()
casper_bytecode = compiler.compile(casper_code)
casper_abi = compiler.mk_full_signature(casper_code)
casper_ct = ContractTranslator(casper_abi)

code_template = """
~calldatacopy(0, 0, 128)
~call(3000, 1, 0, 0, 128, 0, 32)
return(~mload(0) == %s)
"""

def mk_validation_code(address):
    return serpent.compile(code_template % (utils.checksum_encode(address)))

# Helper functions for making a prepare, commit, login and logout message
def mk_prepare(validator_index, epoch, ancestry_hash, source_epoch, source_ancestry_hash, key):
    sighash = utils.sha3(rlp.encode([validator_index, epoch, ancestry_hash, source_epoch, source_ancestry_hash]))
    v, r, s = utils.ecdsa_raw_sign(sighash, key)
    sig = utils.encode_int32(v) + utils.encode_int32(r) + utils.encode_int32(s)
    return rlp.encode([validator_index, epoch, ancestry_hash, source_epoch, source_ancestry_hash, sig])

def mk_commit(validator_index, epoch, hash, prev_commit_epoch, key):
    sighash = utils.sha3(rlp.encode([validator_index, epoch, hash, prev_commit_epoch]))
    v, r, s = utils.ecdsa_raw_sign(sighash, key)
    sig = utils.encode_int32(v) + utils.encode_int32(r) + utils.encode_int32(s)
    return rlp.encode([validator_index, epoch, hash, prev_commit_epoch, sig])

def mk_logout(validator_index, epoch, key):
    sighash = utils.sha3(rlp.encode([validator_index, epoch]))
    v, r, s = utils.ecdsa_raw_sign(sighash, key)
    sig = utils.encode_int32(v) + utils.encode_int32(r) + utils.encode_int32(s)
    return rlp.encode([validator_index, epoch, sig])

def induct_validator(casper, key, value):
    valcode_addr = s.tx(key, "", 0, mk_validation_code(utils.privtoaddr(key)))
    assert utils.big_endian_to_int(s.tx(key, purity_checker_address, 0, ct.encode('submit', [valcode_addr]))) == 1
    casper.deposit(valcode_addr, utils.privtoaddr(key), value=value)

def mk_status_flicker(validator_index, epoch, login, key):
    sighash = utils.sha3(rlp.encode([validator_index, epoch, login]))
    v, r, s = utils.ecdsa_raw_sign(sighash, key)
    sig = utils.encode_int32(v) + utils.encode_int32(r) + utils.encode_int32(s)
    return rlp.encode([validator_index, epoch, login, sig])

# Get a genesis state which is primed for Casper
def make_casper_genesis(initial_validator, alloc, epoch_length, slash_delay):
    # The Casper-specific config declaration
    casper_config = copy.deepcopy(config.default_config)
    casper_config['HOMESTEAD_FORK_BLKNUM'] = 0
    casper_config['ANTI_DOS_FORK_BLKNUM'] = 0
    casper_config['CLEARING_FORK_BLKNUM'] = 0
    casper_config['CONSENSUS_STRATEGY'] = 'hybrid_casper'
    casper_config['EPOCH_LENGTH'] = epoch_length
    casper_config['SLASH_DELAY'] = slash_delay
    casper_config['CASPER_ADDRESS'] = utils.mk_contract_address(utils.privtoaddr(initial_validator), 4)
    # Create state and apply required state_transitions for initializing Casper
    state = genesis_helpers.mk_basic_state(alloc, None, env=config.Env(config=casper_config))
    state.gas_limit = 10**8
    consensus.initialize(state)
    # inject_casper_contracts(state, initial_validator, epoch_length, slash_delay)
    state.commit()
    return state

def mk_initializers(config, sender_privkey, starting_nonce=0):
    o = []
    nonce = starting_nonce
    # Create transactions for instantiating RLP decoder, sig hasher and purity checker, plus transactions for feeding the
    # one-time accounts that generate those transactions
    for tx in (viper_rlp_decoder_tx, sig_hasher_tx, purity_checker_tx):
        o.append(Transaction(nonce, gasprice, 90000, tx.sender, tx.startgas * tx.gasprice + tx.value, '').sign(sender_privkey))
        o.append(tx)
        nonce += 1
    # Casper initialization transaction
    casper_tx = Transaction(nonce, gasprice, 4500000, b'', 0, casper_bytecode).sign(sender_privkey)
    # Casper initiate call (separate from initialization to save gas)
    initiate_args = casper_ct.encode('initiate', [
        config["epoch_length"], config["withdrawal_delay"], config["owner"], sig_hasher_address,
        purity_checker_address, config["base_interest_factor"], config["base_penalty_factor"]
    ])
    casper_initiate_tx = Transaction(nonce + 1, gasprice, 1000000, casper_tx.creates, 0, initiate_args).sign(sender_privkey)
    # Return list of transactions and Casper address
    return o + [casper_tx, casper_initiate_tx], casper_tx.creates


def inject_casper_contracts(t, initial_validator, owner):
    casper_config = {
        "epoch_length": 25,             # 5 blocks
        "withdrawal_delay": 100,        # 100 epochs
        "base_interest_factor": 0.02,
        "base_penalty_factor": 0.002,
        "owner": owner
    }
    init_txs, casper_address = mk_initializers(casper_config, initial_validator)
    for tx in init_txs:
        if t.head_state.gas_used + tx.startgas > t.head_state.gas_limit:
            t.mine(1)
        t.direct_tx(tx)
    return casper_address
