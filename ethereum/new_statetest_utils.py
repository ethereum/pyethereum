from ethereum.state import State
from ethereum.block import FakeHeader, Block
from ethereum.utils import decode_hex, parse_int_or_hex, sha3, to_string, \
    remove_0x_head, encode_hex, big_endian_to_int
from ethereum.config import default_config, Env
from ethereum.exceptions import InvalidTransaction
import ethereum.transactions as transactions
import ethereum.state_transition as state_transition
import copy

#from ethereum.slogging import LogRecorder, configure_logging, set_level
#config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace,eth.pb.msg:trace,eth.pb.tx:debug'
#configure_logging(config_string=config_string)

fake_headers = {}

def mk_fake_header(blknum):
    if blknum not in fake_headers:
        fake_headers[blknum] = FakeHeader(sha3(to_string(blknum)))
    return fake_headers[blknum]

basic_env = {
    "currentCoinbase": "2adc25665018aa1fe0e6bc666dac8fc2697ff9ba",
    "currentDifficulty": "256",
    "currentGasLimit": "1000000000",
    "currentNumber": "257",
    "currentTimestamp": "1",
    "previousHash": "5e20a0453cecd065ea59c37ac63e079ee08998b6045136a8ce6635c7912ec0b6"
}

konfig = copy.copy(default_config)

konfig_spurious = copy.copy(konfig)
konfig_spurious["HOMESTEAD_FORK_BLKNUM"] = 0
konfig_spurious["ANTI_DOS_FORK_BLKNUM"] = 0
konfig_spurious["CLEARING_FORK_BLKNUM"] = 0
konfig_spurious["METROPOLIS_FORK_BLKNUM"] = 2**99

konfig_metropolis = copy.copy(konfig)
konfig_metropolis["HOMESTEAD_FORK_BLKNUM"] = 0
konfig_metropolis["ANTI_DOS_FORK_BLKNUM"] = 0
konfig_metropolis["CLEARING_FORK_BLKNUM"] = 0
konfig_metropolis["METROPOLIS_FORK_BLKNUM"] = 0

configs = {
    "EIP158": konfig_spurious,
    "Metropolis": konfig_metropolis
}

def compute_state_test_post(test, indices=None, _configs=None):
    env, pre, txdata = test["env"], test["pre"], test["transaction"]
    # Setup env
    state = State(
        env=Env(config=konfig),
        block_prevhash=decode_hex(env['previousHash']),
        prev_headers=[mk_fake_header(i) for i in range(parse_int_or_hex(env['currentNumber']) -1,
                                                       max(-1, parse_int_or_hex(env['currentNumber']) -257), -1)],
        block_number=parse_int_or_hex(env['currentNumber']),
        block_coinbase=decode_hex(env['currentCoinbase']),
        block_difficulty=parse_int_or_hex(env['currentDifficulty']),
        gas_limit=parse_int_or_hex(env['currentGasLimit']),
        timestamp=parse_int_or_hex(env['currentTimestamp']))

    # Fill up pre
    for address, h in list(pre.items()):
        assert len(address) == 40
        address = decode_hex(address)
        assert set(h.keys()) == set(['code', 'nonce', 'balance', 'storage'])
        state.set_nonce(address, parse_int_or_hex(h['nonce']))
        state.set_balance(address, parse_int_or_hex(h['balance']))
        state.set_code(address, decode_hex(h['code'][2:]))
        for k, v in h['storage'].items():
            state.set_storage_data(address,
                                   big_endian_to_int(decode_hex(k[2:])),
                                   decode_hex(v[2:]))

    
    # We have an optional argument which is a list of JSONs specifying indices.
    # If this argument is set, we compute only those scenarios. If not, we
    # compute all of them.   
    if indices is None:
        indices = []
        for data_index in range(len(txdata['data'])):
            for value_index in range(len(txdata['value'])):
                for gaslimit_index in range(len(txdata['gasLimit'])):
                    indices.append({"data": data_index, "gas": gaslimit_index, "value": value_index})
                
    o = {}
    for config_name in (configs.keys() if _configs is None else _configs):
        state.env.config = configs[config_name]
        output_decls = []
        for index_json in indices:
            print("Executing for indices %r" % index_json)
            data_index, value_index, gaslimit_index = index_json["data"], index_json["value"], index_json["gas"]
            try:
                # Create the transaction
                tx = transactions.Transaction(
                    nonce=parse_int_or_hex(txdata['nonce'] or b"0"),
                    gasprice=parse_int_or_hex(txdata['gasPrice'] or b"0"),
                    startgas=parse_int_or_hex(txdata['gasLimit'][gaslimit_index] or b"0"),
                    to=decode_hex(txdata['to']),
                    value=parse_int_or_hex(txdata['value'][value_index] or b"0"),
                    data=decode_hex(remove_0x_head(txdata['data'][data_index])))
                tx.sign(decode_hex(txdata['secretKey']))
                # Run it
                success, output = state_transition.apply_transaction(state, tx)
                print("Applied tx")
            except InvalidTransaction as e:
                print("Exception: %r" % e)
                success, output = False, b''
            state.commit()
            output_decl = {
                "hash": encode_hex(state.trie.root_hash),
                "indexes": index_json
            }
            output_decls.append(output_decl)
        o[config_name] = output_decls
    return o

def verify_state_test(test):
    print("Verifying state test")
    for config_name, result in test["post"].items():
        # Old protocol versions may not be supported
        if config_name not in configs:
            continue
        print("Testing for %s" % config_name)
        computed = compute_state_test_post(test, [x["indexes"] for x in result], [config_name])[config_name]
        supplied = test["post"][config_name]
        assert len(computed) == len(supplied)
        for c, s in zip(computed, supplied):
            assert c["hash"] == s["hash"]
