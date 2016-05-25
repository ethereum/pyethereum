# -*- coding: utf8 -*-
import re
import subprocess
import os

import yaml

BINARY = 'solc'


class CompileError(Exception):
    pass


def get_compiler_path():
    """ Return the path to the solc compiler.

    This funtion will search for the solc binary in the $PATH and return the
    path of the first executable occurence.
    """
    for path in os.getenv('PATH', '').split(os.pathsep):
        path = path.strip('"')
        executable_path = os.path.join(path, BINARY)

        if os.path.isfile(executable_path) and os.access(executable_path, os.X_OK):
            return executable_path

    return None


def get_solidity():
    """ Return the singleton used to interact with the solc compiler. """
    if get_compiler_path() is None:
        return None  # the compiler wasn't found in $PATH

    return solc_wrapper


def solc_arguments(libraries=None, combined='bin,abi', optimize=True):
    """ Build the arguments to call the solc binary. """
    args = [
        '--combined-json', combined,
        '--add-std',
    ]

    if optimize:
        args.append('--optmize')

    if libraries is not None:
        addresses = [
            '{name}:{address}'.format(name=name, address=address)
            for name, address in libraries.items()
        ]
        args.extend([
            '--libraries',
            ','.join(addresses),
        ])

    return args


def solc_parse_output(compiler_output):
    """ Parses the compiler output. """
    result = yaml.safe_load(compiler_output)['contracts']

    if 'bin' in result.values()[0]:
        for value in result.values():
            value['bin_hex'] = value['bin']
            value['bin'] = value['bin_hex'].decode('hex')

    for json_data in ('abi', 'devdoc', 'userdoc'):
        # the values in the output can be configured through the
        # --combined-json flag, check that it's present in the first value and
        # assume all values are consistent
        if json_data not in result.values()[0]:
            continue

        for value in result.values():
            value[json_data] = yaml.safe_load(value[json_data])

    return result


def compiler_version():
    """ Return the version of the installed solc. """
    version_info = subprocess.check_output(['solc', '--version'])
    match = re.search('^Version: ([0-9a-z.-]+)/', version_info, re.MULTILINE)

    if match:
        return match.group(1)


def solidity_names(code):
    """ Return the library and contract names in order of appearence. """
    # the special sequence \s is equivalent to the set [ \t\n\r\f\v]
    return re.findall(r'(contract|library)\s+([a-zA-Z][a-zA-Z0-9]*)', code, re.MULTILINE)


def compile_file(filepath, libraries=None, combined='bin,abi', optimize=True):
    """ Return the compile contract code.

    Args:
        filepath (str): The path to the contract source code.
        libraries (dict): A dictionary mapping library name to address.
        combined (str: The flags passed to the solidity compiler to defined
            what output should be used.
        optimize (bool): Flag to set up compiler optimization.

    Returns:
        dict: A mapping from the contract name to it's binary.
    """

    workdir, filename = os.path.split(filepath)

    args = solc_arguments(libraries=libraries, combined=combined, optimize=optimize)
    args.insert(0, get_compiler_path())
    args.append(filename)

    output = subprocess.check_output(args, cwd=workdir)

    return solc_parse_output(output)


def compile_contract(filepath, contract_name, libraries=None, combined='bin,abi', optimize=True):
    all_contracts = compile_file(
        filepath,
        libraries=libraries,
        combined=combined,
        optimize=optimize,
    )

    return all_contracts[contract_name]


def compile_last_contract(filepath, libraries=None, combined='bin,abi', optimize=True):
    with open(filepath) as handler:
        all_names = solidity_names(handler.read())

    all_contract_names = [
        name
        for kind, name in all_names
        # if kind == 'contract'
    ]

    last_contract = all_contract_names[-1]

    return compile_contract(
        filepath,
        last_contract,
        libraries=libraries,
        combined=combined,
        optimize=optimize,
    )


def compile_code(sourcecode, libraries=None, combined='bin,abi', optimize=True):
    args = solc_arguments(libraries=libraries, combined=combined, optimize=optimize)
    args.insert(0, get_compiler_path())

    process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    stdoutdata, _ = process.communicate(input=sourcecode)

    return solc_parse_output(stdoutdata)


class Solc(object):
    """ Wraps the solc binary. """

    compiler_available = staticmethod(get_compiler_path)
    contract_names = staticmethod(solidity_names)
    compiler_version = staticmethod(compiler_version)

    @staticmethod
    def _code_or_path(sourcecode, path, contract_name, libraries, combined):
        if sourcecode and path:
            raise ValueError('sourcecode and path are mutually exclusive.')

        if path and contract_name:
            return compile_contract(path, contract_name, libraries=libraries, combined=combined)

        if path:
            return compile_last_contract(path, libraries=libraries, combined=combined)

        all_names = solidity_names(sourcecode)
        all_contract_names = [
            name
            for kind, name in all_names
            if kind == 'contract'
        ]
        last_contract = all_contract_names[-1]

        result = compile_code(sourcecode, libraries=libraries, combined=combined)
        return result[last_contract]

    @classmethod
    def compile(cls, code, path=None, libraries=None, contract_name=''):
        """ Return the binary of last contract in code. """
        result = cls._code_or_path(code, path, contract_name, libraries, 'bin')
        return result['bin']

    @classmethod
    def mk_full_signature(cls, code, path=None, libraries=None, contract_name=''):
        "returns signature of last contract in code"

        result = cls._code_or_path(code, path, contract_name, libraries, 'abi')
        return result['abi']

    @classmethod
    def combined(cls, code, path=None):
        """ Compile combined-json with abi,bin,devdoc,userdoc.

        @param code: literal solidity code as a string.
        @param path: absolute path to solidity-file. Note: code & path are exclusive!
        """

        contracts = cls._code_or_path(
            sourcecode=code,
            path=path,
            contract_name=None,
            libraries=None,
            combined='abi,bin,devdoc,userdoc',
        )

        if path:
            with open(path) as handler:
                code = handler.read()

        sorted_contracts = []
        for name in solidity_names(code):
            sorted_contracts.append((name[1], contracts[name[1]]))
        return sorted_contracts

    @classmethod
    def compile_rich(cls, code, path=None):
        """full format as returned by jsonrpc"""

        return {
            contract_name: {
                'code': '0x' + contract.get('bin'),
                'info': {
                    'abiDefinition': contract.get('abi'),
                    'compilerVersion': cls.compiler_version(),
                    'developerDoc': contract.get('devdoc'),
                    'language': 'Solidity',
                    'languageVersion': '0',
                    'source': code,
                    'userDoc': contract.get('userdoc')
                },
            }
            for contract_name, contract
            in cls.combined(code, path=path)
        }


solc_wrapper = Solc  # pylint: disable=invalid-name
