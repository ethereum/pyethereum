import click
import json

from ethereum import vm, slogging
from ethereum.block import Block
from ethereum.transactions import Transaction
from ethereum.config import Env
from ethereum.db import EphemDB
from ethereum.genesis_helpers import initialize_genesis_keys, state_from_genesis_declaration
from ethereum.messages import VMExt, _apply_msg
from ethereum.utils import bytearray_to_bytestr, normalize_address, scan_bin, scan_int, zpad


slogging.configure('eth.vm:trace,eth.pb:trace')


class EVMRunner(object):
    def __init__(self, genesis):
        env = Env(EphemDB())
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
    genesis = json.load(genesis)
    EVMRunner(genesis).run(
        sender=sender,
        to=receiver,
        code=code,
        gas=gas
    )


if __name__ == '__main__':
    main()
