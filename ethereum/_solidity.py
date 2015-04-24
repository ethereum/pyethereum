import subprocess
import os


class CompileError(Exception):
    pass


class solc_wrapper(object):

    "wraps solc binary"

    @classmethod
    def compiler_available(cls):
        program = 'solc'

        def is_exe(fpath):
            return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

        fpath, fname = os.path.split(program)
        if fpath:
            if is_exe(program):
                return program
        else:
            for path in os.environ["PATH"].split(os.pathsep):
                path = path.strip('"')
                exe_file = os.path.join(path, program)
                if is_exe(exe_file):
                    return exe_file

        return None

    @classmethod
    def split_contracts(cls, code):
        contracts = []
        contract = None
        for line in code.split('\n'):
            if line.lstrip().startswith('contract '):  # FIXME
                if contract:
                    contracts.append('\n'.join(contract))
                contract = [line]
            elif contract:
                contract.append(line)
        if contract:
            contracts.append('\n'.join(contract))
        return contracts

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


def get_solidity():
    try:
        import solidity
        tester.languages['solidity'] = solidity
    except ImportError:
        if not solc_wrapper.compiler_available():
            return None
        return solc_wrapper


if __name__ == '__main__':
    import tester
    assert 'solidity' in tester.languages

    one_contract = """

    contract foo {
        function seven() returns (int256 y) {
            y = 7;
        }
        function mul2(int256 x) returns (int256 y) {
            y = x * 2;
        }
    }
    """

    two_contracts = one_contract + """
    contract baz {
        function echo(address a) returns (address b) {
            b = a;
            return b;
        }
        function eight() returns (int256 y) {
            y = 8;
        }
    }
    """

    # test
    assert 'solidity' in tester.languages

    s = tester.state()

    c1 = s.abi_contract(one_contract, language='solidity')
    assert c1.seven() == 7
    assert c1.mul2(2) == 4
    assert c1.mul2(-2) == -4

    two_codes = solc_wrapper.split_contracts(two_contracts)
    assert len(two_codes) == 2

    for code in two_codes:
        bytecode = solc_wrapper.compile(code)
        jsonabi = solc_wrapper.mk_full_signature(code)
        c = s.abi_contract(code, language='solidity')

    c1 = s.abi_contract(two_codes[0], language='solidity')
    assert c1.seven() == 7
    assert c1.mul2(2) == 4
    assert c1.mul2(-2) == -4

    c2 = s.abi_contract(two_codes[1], language='solidity')
    a = '\0' * 20
    assert c2.echo(a).decode('hex') == a
    assert c2.eight() == 8
