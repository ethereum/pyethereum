# -*- coding: utf8 -*-
import os
import re
import subprocess
import warnings
import shlex

import yaml

from rlp.utils import decode_hex
from . import utils

BINARY = 'solc'


class CompileError(Exception):
    pass


def get_compiler_path():
    """ Return the path to the solc compiler.

    This funtion will search for the solc binary in the $PATH and return the
    path of the first executable occurence.
    """
    # If the user provides a specific solc binary let's use that
    given_binary = os.environ.get('SOLC_BINARY')
    if given_binary:
        return given_binary

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


def solc_arguments(libraries=None, combined='bin,abi', optimize=True, extra_args=None):
    """ Build the arguments to call the solc binary. """
    args = [
        '--combined-json', combined,
        '--add-std'
    ]

    if optimize:
        args.append('--optimize')

    if extra_args:
        try:
            args.extend(shlex.split(extra_args))
        except:  # if not a parseable string then treat it as a list
            args.extend(extra_args)

    if libraries is not None and len(libraries):
        addresses = [
            '{name}:{address}'.format(name=name, address=address.decode('utf8'))
            for name, address in libraries.items()
        ]
        args.extend([
            '--libraries',
            ','.join(addresses),
        ])

    return args


def solc_parse_output(compiler_output):
    """ Parses the compiler output. """
    # At the moment some solc output like --hashes or -- gas will not output
    # json at all so if used with those arguments the logic here will break.
    # Perhaps solidity will slowly switch to a json only output and this comment
    # can eventually go away and we will not need to add more logic here at all.
    result = yaml.safe_load(compiler_output)['contracts']

    if 'bin' in tuple(result.values())[0]:
        for value in result.values():
            value['bin_hex'] = value['bin']

            # decoding can fail if the compiled contract has unresolved symbols
            try:
                value['bin'] = decode_hex(value['bin_hex'])
            except TypeError:
                pass

    for json_data in ('abi', 'devdoc', 'userdoc'):
        # the values in the output can be configured through the
        # --combined-json flag, check that it's present in the first value and
        # assume all values are consistent
        if json_data not in tuple(result.values())[0]:
            continue

        for value in result.values():
            value[json_data] = yaml.safe_load(value[json_data])

    return result


def compiler_version():
    """ Return the version of the installed solc. """
    version_info = subprocess.check_output(['solc', '--version'])
    match = re.search(b'^Version: ([0-9a-z.-]+)/', version_info, re.MULTILINE)

    if match:
        return match.group(1)


def solidity_names(code):  # pylint: disable=too-many-branches
    """ Return the library and contract names in order of appearence. """
    names = []
    in_string = None
    backslash = False
    comment = None

    # "parse" the code by hand to handle the corner cases:
    #  - the contract or library can be inside a comment or string
    #  - multiline comments
    #  - the contract and library keywords could not be at the start of the line
    for pos, char in enumerate(code):
        if in_string:
            if not backslash and in_string == char:
                in_string = None
                backslash = False

            if char == '\\':  # pylint: disable=simplifiable-if-statement
                backslash = True
            else:
                backslash = False

        elif comment == '//':
            if char in ('\n', '\r'):
                comment = None

        elif comment == '/*':
            if char == '*' and code[pos + 1] == '/':
                comment = None

        else:
            if char == '"' or char == "'":
                in_string = char

            if char == '/':
                if code[pos + 1] == '/':
                    comment = '//'
                if code[pos + 1] == '*':
                    comment = '/*'

            if char == 'c' and code[pos: pos + 8] == 'contract':
                result = re.match('^contract[^_$a-zA-Z]+([_$a-zA-Z][_$a-zA-Z0-9]*)', code[pos:])

                if result:
                    names.append(('contract', result.groups()[0]))

            if char == 'l' and code[pos: pos + 7] == 'library':
                result = re.match('^library[^_$a-zA-Z]+([_$a-zA-Z][_$a-zA-Z0-9]*)', code[pos:])

                if result:
                    names.append(('library', result.groups()[0]))

    return names


def solidity_library_symbol(library_name):
    """ Return the symbol used in the bytecode to represent the `library_name`. """
    # the symbol is always 40 characters in length with the minimum of two
    # leading and trailing underscores
    length = min(len(library_name), 36)

    library_piece = library_name[:length]
    hold_piece = '_' * (36 - length)

    return '__{library}{hold}__'.format(
        library=library_piece,
        hold=hold_piece,
    )


def solidity_resolve_address(hex_code, library_symbol, library_address):
    """ Change the bytecode to use the given library address.

    Args:
        hex_code (bin): The bytecode encoded in hexadecimal.
        library_name (str): The library that will be resolved.
        library_address (str): The address of the library.

    Returns:
        bin: The bytecode encoded in hexadecimal with the library references
            resolved.
    """
    if library_address.startswith('0x'):
        raise ValueError('Address should not contain the 0x prefix')

    try:
        decode_hex(library_address)
    except TypeError:
        raise ValueError('library_address contains invalid characters, it must be hex encoded.')

    if len(library_symbol) != 40 or len(library_address) != 40:
        raise ValueError('Address with wrong length')

    return hex_code.replace(library_symbol, library_address)


def solidity_resolve_symbols(hex_code, libraries):
    symbol_address = {
        solidity_library_symbol(library_name): address
        for library_name, address in libraries.items()
    }

    for unresolved in solidity_unresolved_symbols(hex_code):
        address = symbol_address[unresolved]
        hex_code = solidity_resolve_address(hex_code, unresolved, address)

    return hex_code


def solidity_unresolved_symbols(hex_code):
    """ Return the unresolved symbols contained in the `hex_code`.

    Note:
        The binary representation should not be provided since this function
        relies on the fact that the '_' is invalid in hex encoding.

    Args:
        hex_code (str): The bytecode encoded as hexadecimal.
    """
    return set(re.findall(r"_.{39}", hex_code))


def compile_file(filepath, libraries=None, combined='bin,abi', optimize=True, extra_args=None):
    """ Return the compile contract code.

    Args:
        filepath (str): The path to the contract source code.
        libraries (dict): A dictionary mapping library name to it's address.
        combined (str): The argument for solc's --combined-json.
        optimize (bool): Enable/disables compiler optimization.

    Returns:
        dict: A mapping from the contract name to it's binary.
    """

    workdir, filename = os.path.split(filepath)

    args = solc_arguments(libraries=libraries, combined=combined, optimize=optimize, extra_args=extra_args)
    args.insert(0, get_compiler_path())
    args.append(filename)

    output = subprocess.check_output(args, cwd=workdir)

    return solc_parse_output(output)


def compile_contract(filepath, contract_name, libraries=None, combined='bin,abi', optimize=True, extra_args=None):
    all_contracts = compile_file(
        filepath,
        libraries=libraries,
        combined=combined,
        optimize=optimize,
        extra_args=extra_args
    )

    return all_contracts[contract_name]


def compile_last_contract(filepath, libraries=None, combined='bin,abi', optimize=True, extra_args=None):
    with open(filepath) as handler:
        all_names = solidity_names(handler.read())

    all_contract_names = [
        name
        for _, name in all_names
    ]

    last_contract = all_contract_names[-1]

    return compile_contract(
        filepath,
        last_contract,
        libraries=libraries,
        combined=combined,
        optimize=optimize,
        extra_args=extra_args
    )


def compile_code(sourcecode, libraries=None, combined='bin,abi', optimize=True, extra_args=None):
    args = solc_arguments(libraries=libraries, combined=combined, optimize=optimize, extra_args=extra_args)
    args.insert(0, get_compiler_path())

    process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdoutdata, stderrdata = process.communicate(input=utils.to_string(sourcecode))

    if process.returncode != 0:
        raise CompileError(stderrdata)

    return solc_parse_output(stdoutdata)


class Solc(object):
    """ Wraps the solc binary. """

    compiler_available = staticmethod(get_compiler_path)
    contract_names = staticmethod(solidity_names)
    compiler_version = staticmethod(compiler_version)

    @staticmethod
    def _code_or_path(sourcecode, path, contract_name, libraries, combined, extra_args):
        warnings.warn('solc_wrapper is deprecated, please use the functions compile_file or compile_code')

        if sourcecode and path:
            raise ValueError('sourcecode and path are mutually exclusive.')

        if path and contract_name:
            return compile_contract(path, contract_name, libraries=libraries, combined=combined, extra_args=extra_args)

        if path:
            return compile_last_contract(path, libraries=libraries, combined=combined, extra_args=extra_args)

        all_names = solidity_names(sourcecode)
        all_contract_names = [
            name
            for _, name in all_names
        ]
        last_contract = all_contract_names[-1]

        result = compile_code(sourcecode, libraries=libraries, combined=combined, extra_args=extra_args)
        return result[last_contract]

    @classmethod
    def compile(cls, code, path=None, libraries=None, contract_name='', extra_args=None):
        """ Return the binary of last contract in code. """
        result = cls._code_or_path(code, path, contract_name, libraries, 'bin', extra_args)
        return result['bin']

    @classmethod
    def mk_full_signature(cls, code, path=None, libraries=None, contract_name='', extra_args=None):
        "returns signature of last contract in code"

        result = cls._code_or_path(code, path, contract_name, libraries, 'abi', extra_args)
        return result['abi']

    @classmethod
    def combined(cls, code, path=None, extra_args=None):
        """ Compile combined-json with abi,bin,devdoc,userdoc.

        @param code: literal solidity code as a string.
        @param path: absolute path to solidity-file. Note: code & path are
                     mutually exclusive!
        @param extra_args: Either a space separated string or a list of extra
                           arguments to be passed to the solidity compiler.
        """

        if code and path:
            raise ValueError('sourcecode and path are mutually exclusive.')

        if path:
            contracts = compile_file(path, extra_args=extra_args)

            with open(path) as handler:
                code = handler.read()

        elif code:
            contracts = compile_code(code, extra_args=extra_args)

        else:
            raise ValueError('either code or path needs to be supplied.')

        sorted_contracts = []
        for name in solidity_names(code):
            sorted_contracts.append((name[1], contracts[name[1]]))
        return sorted_contracts

    @classmethod
    def compile_rich(cls, code, path=None, extra_args=None):
        """full format as returned by jsonrpc"""

        return {
            contract_name: {
                'code': '0x' + contract.get('bin_hex'),
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
            in cls.combined(code, path=path, extra_args=extra_args)
        }


solc_wrapper = Solc  # pylint: disable=invalid-name
