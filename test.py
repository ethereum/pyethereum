from binascii import hexlify
from ethereum.abi import ContractTranslator
from ethereum.config import config_metropolis, Env
from ethereum.tools import tester
from ethereum.tools.tester import ABIContract
from solc import compile_standard

config_metropolis['BLOCK_GAS_LIMIT'] = 2**60

solCode = """
contract Foo {
    function apple() public constant returns (address) {
        return this;
    }
}
"""

def uploadSolidityContract(chain, compileResult, name, contractName):
    print compileResult['contracts'][name][contractName]['evm']['bytecode']['object']
    bytecode = bytearray.fromhex(compileResult['contracts'][name][contractName]['evm']['bytecode']['object'])
    signature = compileResult['contracts'][name][contractName]['abi']
    address = '0x' + hexlify(chain.contract(bytecode, language='evm'))
    contract = ABIContract(chain, ContractTranslator(signature), address)
    return contract

def compileSolidity(chain, name, code):
    result = compile_standard({
        'language': 'Solidity',
        'sources': {
            name: { 'content': code },
        },
        'settings': {
            'outputSelection': { '*': [ 'metadata', 'evm.bytecode', 'evm.sourceMap' ] }
        }
    })
    return result

def compileAndUpload(chain, name, code, contracts):
    compileResult = compileSolidity(chain, name, code)
    return (uploadSolidityContract(chain, compileResult, name, contractName) for contractName in contracts)

chain = tester.Chain(env=Env(config=config_metropolis))
foo, = compileAndUpload(chain, 'Sol', solCode, ['Foo'])
print foo.apple()
print foo.address