from ethereum import utils
from ethereum.state import State
from ethereum import vm
from ethereum.state_transition import apply_transaction, apply_const_message
from ethereum.transactions import Transaction
from ethereum import abi
import serpent
from ethereum.config import default_config, Env
import copy

class RandaoSeed():

    def __init__(self, seed, rounds=10**4):
        self.medstate = []        
        for i in range(rounds):
            if not i % 500:
                self.medstate.append(seed)
            seed = utils.sha3(seed)

    def get(self, index):
        med = self.medstate[index // 500]
        for i in range(index % 500):
            med = utils.sha3(med)
        return med

print 'Initializing privkeys, addresses and randaos for validators'
privkeys = [utils.sha3(str(i)) for i in range(20)]
addrs = [utils.privtoaddr(k) for k in privkeys]
randaos = [RandaoSeed(utils.sha3(str(i))) for i in range(20)]
deposit_sizes = [128] * 15 + [256] * 5

casper_config = copy.deepcopy(default_config)
casper_config['HOMESTEAD_FORK_BLKNUM'] = 0
casper_config['METROPOLIS_FORK_BLKNUM'] = 0
casper_config['SERENITY_FORK_BLKNUM'] = 0
casper_config['CONSENSUS_ALGO'] = 'contract'

print 'Constructing genesis'

def get_contract_code(init_code):
    s = State(env=Env(config=casper_config))
    s.gas_limit = 10**9
    apply_transaction(s, Transaction(0, 0, 10**8, '', 0, init_code))
    addr = utils.mk_metropolis_contract_address(casper_config['METROPOLIS_ENTRY_POINT'], init_code)
    o = s.get_code(addr)
    assert o
    return o

print 'Creating casper contract'
import os
mydir = os.path.split(__file__)[0]
casper_path = os.path.join(mydir, 'casper_contract.py')
ct = abi.ContractTranslator(serpent.mk_full_signature(open(casper_path).read()))
s = State(env=Env(config=casper_config))
s.gas_limit = 10**9
casper_code = get_contract_code(serpent.compile(open(casper_path).read()))
casper_addr = utils.normalize_address(255)
s.set_code(casper_addr, casper_code)
assert len(casper_code)
print 'Casper contract created, code length %d' % len(casper_code)

def generate_validation_code(addr):
    code = """
# First 32 bytes of input = hash, remaining 96 = signature
a = ecrecover(~calldataload(0), ~calldataload(32), ~calldataload(64), ~calldataload(96))
assert a == %s
return(1)
    """ % ('0x'+utils.normalize_address(addr).encode('hex'))
    print code
    return get_contract_code(serpent.compile(code))

# Add all validators
for k, a, r, ds in zip(privkeys, addrs, randaos, deposit_sizes):
    # Leave 1 eth to pay txfees
    s.set_balance(a, (ds + 1) * 10**18)
    t = Transaction(0, 0, 10**8, casper_addr, ds * 10**18, ct.encode('deposit', [generate_validation_code(a), r.get(9999)])).sign(k)
    apply_transaction(s, t)


def call_casper(state, fun, args, gas=1000000, value=0):
    abidata = vm.CallData([utils.safe_ord(x) for x in ct.encode(fun, args)])
    msg = vm.Message(casper_config['METROPOLIS_ENTRY_POINT'], casper_addr,
                     value, gas, abidata, code_address=casper_addr)
    o = apply_const_message(state, msg)
    if o:
        return ct.decode(fun, ''.join(map(chr, o)))[0]
    else:
        return None
     
s.commit()
print 'Checking validator deposit total'
assert call_casper(s, 'getTotalDeposits', []) == sum(deposit_sizes) * 10**18
print 'Validator deposit total consistent'

print 'Next validator:', call_casper(s, 'getValidator', [1])
