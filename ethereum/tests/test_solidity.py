from ethereum import tester
import pytest
serpent_contract = """
extern solidity: [sub2:_:i]

def main(a):
    return(a.sub2() * 2)

def sub1():
    return(5)

"""

solidity_contract = """
contract serpent { function sub1() returns (int256 y) {} }

contract foo {
    function main(address a) returns (int256 y) {
        y = serpent(a).sub1() * 2;
    }
    function sub2() returns (int256 y) {
        y = 7;
    }
}

"""


@pytest.mark.xfail  # pysol is currently broken
def test_interop():
    s = tester.state()
    c1 = s.abi_contract(serpent_contract)
    c2 = s.abi_contract(solidity_contract, language='solidity')
    # assert c1.sub1() == 5
    # assert c2.sub2() == 7
    # assert c1.main(c2.address) == 14
    # assert c2.main(c1.address) == 10


if __name__ == '__main__':

    import subprocess

    one_solidity_contract = """

    contract foo {
        function main(address a) returns (address b) {
            b = a;
            return b;
        }
        function sub2() returns (int256 y) {
            y = 7;
        }
    }

    """

    class CompileError(Exception):
        pass

    class solc_wrapper(object):

        @classmethod
        def compile(cls, code):
            p = subprocess.Popen(['solc', '--binary', 'stdout'],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            stdoutdata, stderrdata = p.communicate(input=code)
            if p.returncode:
                raise CompileError('compilation failed')

            hex_code = stdoutdata.rsplit('Binary: \n')[-1].strip()
            return hex_code.decode('hex')

        @classmethod
        def mk_full_signature(cls, code):
            p = subprocess.Popen(['solc', '--json-abi', 'stdout'],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            stdoutdata, stderrdata = p.communicate(input=code)
            if p.returncode:
                raise CompileError('compilation failed')
            jsonabi = stdoutdata.rsplit('Contract JSON ABI\n')[-1].strip()
            return jsonabi

    tester.languages['solidity'] = solc_wrapper

    bytecode = solc_wrapper.compile(one_solidity_contract)
    jsonabi = solc_wrapper.mk_full_signature(one_solidity_contract)

    # test
    s = tester.state()
    c2 = s.abi_contract(one_solidity_contract, language='solidity')
    a = '\0' * 20
    assert c2.main(a).decode('hex') == a
    assert c2.sub2() == 7
