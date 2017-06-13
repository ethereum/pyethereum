import click
import copy
import json

from ethereum import slogging
slogging.PRINT_FORMAT = '%(message)s'

from ethereum import vm
from ethereum.block import Block
from ethereum.transactions import Transaction
from ethereum.config import Env, default_config
from ethereum.db import EphemDB
from ethereum.genesis_helpers import initialize_genesis_keys, state_from_genesis_declaration, mk_genesis_data
from ethereum.messages import VMExt, _apply_msg
from ethereum.utils import bytearray_to_bytestr, normalize_address, encode_int256, encode_bin, scan_bin, zpad, encode_hex, decode_hex, big_endian_to_int, int_to_big_endian

slogging.configure(':info,eth.vm.op:trace')


def scan_int(v):
    if v[:2] in ('0x', b'0x'):
        v = v[2:]
    if len(v) % 2 != 0:
        v = '0' + v
    return big_endian_to_int(decode_hex(v))

def encode_int(v):
    s = encode_hex(int_to_big_endian(int(v)))
    if s[:1] == '0':  # remove leading zero
        s = s[1:]
    if not s:
        s = '0'
    return '0x' + s

vm.log_vm_op.memory = '0x'
vm.log_vm_op.storage = ''
def format_message(msg, kwargs, highlight, level):
    if 'memory' in kwargs:
        vm.log_vm_op.memory = '0x' + kwargs['memory']
    if 'storage' in kwargs:
        s = []
        storage = kwargs['storage']['storage']
        for k in sorted(storage.keys()):
            v = '0x' + encode_hex(zpad(int_to_big_endian(scan_int(storage[k])),32))
            k = '0x' + encode_hex(zpad(int_to_big_endian(scan_int(k)),32))
            s.append(k + ': ' + v)
        s = ','.join(s)
        vm.log_vm_op.storage = s

    return '{"pc":%s,"op":%s,"gas":"%s","gasCost":"%s","memory":"%s","stack":[%s],"storage":{%s},"depth":%s}' % (
        kwargs['pc'],
        kwargs['inst'],
        encode_int(int(kwargs['gas'])),
        encode_int(kwargs['gas_cost']),
        vm.log_vm_op.memory,
        ','.join(['"%s"' % encode_int(v) for v in kwargs['stack']]),
        vm.log_vm_op.storage,
        kwargs['depth']+1
    )
vm.log_vm_op.format_message = format_message


konfig = copy.copy(default_config)
konfig['HOMESTEAD_FORK_BLKNUM'] = 0
konfig['DAO_FORK_BLKNUM'] = 0
konfig['ANTI_DOS_FORK_BLKNUM'] = 0
konfig['SPURIOUS_DRAGON_FORK_BLKNUM'] = 0
konfig['METROPOLIS_FORK_BLKNUM'] = 999999999


class EVMRunner(object):
    def __init__(self, genesis):
        env = Env(EphemDB(), konfig)
        if not genesis:
            genesis = mk_genesis_data(env)

        if 'config' in genesis:
            if 'homesteadBlock' in genesis['config']:
                env.config['HOMESTEAD_FORK_BLKNUM'] = int(genesis['config']['homesteadBlock'])
                env.config['DAO_FORK_BLKNUM'] = int(genesis['config']['homesteadBlock'])
                env.config['ANTI_DOS_FORK_BLKNUM'] = int(genesis['config']['homesteadBlock'])
                env.config['SPURIOUS_DRAGON_FORK_BLKNUM'] = int(genesis['config']['homesteadBlock'])

        self.state = state_from_genesis_declaration(genesis, env)
        initialize_genesis_keys(self.state, Block(self.state.prev_headers[0], [], []))

    def run(self, sender=None, to=None, code=None, gas=None):
        sender = normalize_address(sender) if sender else normalize_address(zpad('sender', 20))
        to = normalize_address(to) if to else normalize_address(zpad('receiver', 20))
        code = scan_bin(code) if code else ''
        gas = scan_int(gas) if gas else 10000000000000

        msg = vm.Message(sender, to, gas=gas)
        ext = VMExt(self.state, Transaction(0, 0, 21000, b'', 0, b''))

        result, gas_remained, data = _apply_msg(ext, msg, code)
        return bytearray_to_bytestr(data) if result else None


@click.command()
@click.option('-g', '--genesis', type=click.File(), help='Genesis json file to use.')
@click.option('-c', '--code', type=str, help='Code to be run on evm.')
@click.option('-s', '--sender', type=str, help='Sender of the transaction.')
@click.option('-r', '--receiver', type=str, help='Receiver of the transaction.')
@click.option('--gas', type=str, help='Gas limit for the run.')
def main(genesis, code, sender, receiver, gas):
    if genesis:
        genesis = json.load(genesis)
    EVMRunner(genesis).run(
        sender=sender,
        to=receiver,
        code=code,
        gas=gas
    )


if __name__ == '__main__':
    main()
