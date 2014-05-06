from utils import instrument
from pyethereum.utils import recursive_int_to_big_endian
import mock


@given(u'a packet')  # noqa
def step_impl(context):
    context.packet = context.packeter.dump_packet('this is a test packet')


@when(u'peer.send_packet is called')  # noqa
def step_impl(context):
    context.peer.send_packet(context.packet)


@when(u'all data with the peer is processed')  # noqa
def step_impl(context):
    context.peer.run()


@then(u'the packet sent through connection should be the given packet')  # noqa
def step_impl(context):
    assert context.sent_packets == [context.packet]


@when(u'peer.send_Hello is called')  # noqa
def step_impl(context):
    context.peer.send_Hello()


@then(u'the packet sent through connection should be a Hello packet')  # noqa
def step_impl(context):
    packet = context.packeter.dump_Hello()
    assert context.sent_packets == [packet]

@given(u'a valid Hello packet')  # noqa
def step_impl(context):
    context.packet = context.packeter.dump_Hello()

@given(u'a Hello packet with protocol version incompatible')  # noqa
def step_impl(context):
    packeter = context.packeter
    data = [packeter.cmd_map_by_name['Hello'],
            'incompatible_protocal_version',
            packeter.NETWORK_ID,
            packeter.CLIENT_ID,
            packeter.config.getint('network', 'listen_port'),
            packeter.CAPABILITIES,
            packeter.config.get('wallet', 'coinbase')
            ]
    context.packet = packeter.dump_packet(data)


@given(u'a Hello packet with network id incompatible')  # noqa
def step_impl(context):
    packeter = context.packeter
    data = [packeter.cmd_map_by_name['Hello'],
            packeter.PROTOCOL_VERSION,
            'incompatible_network_id',
            packeter.CLIENT_ID,
            packeter.config.getint('network', 'listen_port'),
            packeter.CAPABILITIES,
            packeter.config.get('wallet', 'coinbase')
            ]
    context.packet = packeter.dump_packet(data)


@when(u'peer.send_Hello is instrumented')  # noqa
def step_impl(context):
    context.peer.send_Hello = instrument(context.peer.send_Hello)


@then(u'peer.send_Hello should be called once')  # noqa
def step_impl(context):
    func = context.peer.send_Hello
    assert func.call_count == 1


@when(u'peer.send_Disconnect is instrumented')  # noqa
def step_impl(context):
    context.peer.send_Disconnect = instrument(context.peer.send_Disconnect)


@when(u'the packet is received from peer')  # noqa
def step_impl(context):
    context.add_recv_packet(context.packet)


@then(u'peer.send_Disconnect should be called once with args: reason')  # noqa
def step_impl(context):
    func = context.peer.send_Disconnect
    assert func.call_count == 1
    assert len(func.call_args[0]) == 1 or 'reason' in func.call_args[1]


@when(u'peer.send_Ping is called')  # noqa
def step_impl(context):
    context.peer.send_Ping()


@then(u'the packet sent through connection should be a Ping packet')  # noqa
def step_impl(context):
    packet = context.packeter.dump_Ping()
    assert context.sent_packets == [packet]


@given(u'a Ping packet')  # noqa
def step_impl(context):
    context.packet = context.packeter.dump_Ping()


@when(u'peer.send_Pong is instrumented')  # noqa
def step_impl(context):
    context.peer.send_Pong = instrument(context.peer.send_Pong)


@then(u'peer.send_Pong should be called once')  # noqa
def step_impl(context):
    func = context.peer.send_Pong
    assert func.call_count == 1


@when(u'peer.send_Pong is called')  # noqa
def step_impl(context):
    context.peer.send_Pong()


@then(u'the packet sent through connection should be a Pong packet')  # noqa
def step_impl(context):
    packet = context.packeter.dump_Pong()
    assert context.sent_packets == [packet]


@given(u'a Pong packet')  # noqa
def step_impl(context):
    context.packet = context.packeter.dump_Pong()


@when(u'handler for a disconnect_requested signal is registered')  # noqa
def step_impl(context):
    from pyethereum.signals import peer_disconnect_requested
    context.disconnect_requested_handler = mock.MagicMock()
    peer_disconnect_requested.connect(context.disconnect_requested_handler)


@when(u'peer.send_Disconnect is called')  # noqa
def step_impl(context):
    context.peer.send_Disconnect()


@then(u'the packet sent through connection should be'  # noqa
' a Disconnect packet')
def step_impl(context):
    packet = context.packeter.dump_Disconnect()
    assert context.sent_packets == [packet]


@then(u'the disconnect_requested handler should be called once'  # noqa
' after sleeping for at least 2 seconds')
def step_impl(context):
    import time  # time is already pathced for mocks
    assert context.disconnect_requested_handler.call_count == 1
    sleeping = sum(x[0][0] for x in time.sleep.call_args_list)
    assert sleeping >= 2


@given(u'a Disconnect packet')  # noqa
def step_impl(context):
    context.packet = context.packeter.dump_Disconnect()


@then(u'the disconnect_requested handler should be called once')  # noqa
def step_impl(context):
    assert context.disconnect_requested_handler.call_count == 1


@when(u'peer.send_GetPeers is called')  # noqa
def step_impl(context):
    context.peer.send_GetPeers()


@then(u'the packet sent through connection should be'  # noqa
' a GetPeers packet')
def step_impl(context):
    packet = context.packeter.dump_GetPeers()
    assert context.sent_packets == [packet]


@given(u'a GetPeers packet')  # noqa
def step_impl(context):
    context.packet = context.packeter.dump_GetPeers()


@given(u'peers data')  # noqa
def step_impl(context):
    context.peers_data = [
        ['127.0.0.1', 1234, 'local'],
        ['1.0.0.1', 1234, 'remote'],
    ]


@when(u'getpeers_received signal handler is connected')  # noqa
def step_impl(context):
    from pyethereum.signals import getpeers_received
    handler = mock.MagicMock()
    context.getpeers_received_handler = handler
    getpeers_received.connect(handler)


@then(u'the getpeers_received signal handler should be called once')  # noqa
def step_impl(context):
    assert context.getpeers_received_handler.call_count == 1


@when(u'peer.send_Peers is called')  # noqa
def step_impl(context):
    context.peer.send_Peers(context.peers_data)


@then(u'the packet sent through connection should be a Peers packet'  # noqa
' with the peers data')
def step_impl(context):
    assert context.sent_packets == [
        context.packeter.dump_Peers(context.peers_data)]


@given(u'a Peers packet with the peers data')  # noqa
def step_impl(context):
    context.packet = context.packeter.dump_Peers(context.peers_data)


@when(u'handler for new_peers_received signal is registered')  # noqa
def step_impl(context):
    context.new_peer_received_handler = mock.MagicMock()
    from pyethereum.signals import peer_addresses_received
    peer_addresses_received.connect(context.new_peer_received_handler)


@then(u'the new_peers_received handler should be called once'  # noqa
' with all peers')
def step_impl(context):
    call_args = context.new_peer_received_handler.call_args_list[0]
    call_peers = call_args[1]['addresses']
    assert len(call_peers) == len(context.peers_data)
    pairs = zip(call_peers, context.peers_data)
    for call, peer in pairs:
        assert call == peer
        #assert call[1]['address'] == peer

@when(u'peer.send_GetTransactions is called')  # noqa
def step_impl(context):
    context.peer.send_GetTransactions()


@then(u'the packet sent through connection should be'  # noqa
' a GetTransactions packet')
def step_impl(context):
    packet = context.packeter.dump_GetTransactions()
    assert context.sent_packets == [packet]


@given(u'a GetTransactions packet')  # noqa
def step_impl(context):
    context.packet = context.packeter.dump_GetTransactions()


@given(u'transactions data')  # noqa
def step_impl(context):
    context.transactions_data = [
        ['nonce-1', 'receiving_address-1', 1],
        ['nonce-2', 'receiving_address-2', 2],
        ['nonce-3', 'receiving_address-3', 3],
    ]


@when(u'gettransactions_received signal handler is connected')  # noqa
def step_impl(context):
    from pyethereum.signals import gettransactions_received
    handler = mock.MagicMock()
    context.gettransactions_received_handler = handler
    gettransactions_received.connect(handler)


@then(u'the gettransactions_received signal handler'  # noqa
      ' should be called once')
def step_impl(context):
    assert context.gettransactions_received_handler.call_count == 1


@when(u'peer.send_Transactions is called')  # noqa
def step_impl(context):
    context.peer.send_Transactions(context.transactions_data)


@then(u'the packet sent through connection should be'  # noqa
' a Transactions packet with the transactions data')
def step_impl(context):
    packet = context.packeter.dump_Transactions(context.transactions_data)
    assert context.sent_packets == [packet]


@given(u'a Transactions packet with the transactions data')  # noqa
def step_impl(context):
    packet = context.packeter.dump_Transactions(context.transactions_data)
    context.packet = packet


@when(u'handler for a new_transactions_received signal is registered')  # noqa
def step_impl(context):
    context.new_transactions_received_handler = mock.MagicMock()
    from pyethereum.signals import remote_transactions_received
    remote_transactions_received.connect(
        context.new_transactions_received_handler)


@then(u'the new_transactions_received handler'  # noqa
' should be called once with the transactions data')
def step_impl(context):
    mock = context.new_transactions_received_handler
    assert mock.call_count == 1
    assert mock.call_args[1]['transactions'] == recursive_int_to_big_endian(
        context.transactions_data)


@given(u'blocks data')  # noqa
def step_impl(context):
    context.blocks_data = [
        ['block_headerA', ['txA1', 'txA2'], ['uncleA1', 'uncleA2']],
        ['block_headerB', ['txB', 'txB'], ['uncleB', 'uncleB2']],
    ]


@when(u'peer.send_Blocks is called')  # noqa
def step_impl(context):
    context.peer.send_Blocks(context.blocks_data)


@then(u'the packet sent through connection should be'  # noqa
' a Blocks packet with the blocks data')
def step_impl(context):
    packet = context.packeter.dump_Blocks(context.blocks_data)
    assert context.sent_packets == [packet]


@given(u'a Blocks packet with the blocks data')  # noqa
def step_impl(context):
    context.packet = context.packeter.dump_Blocks(context.blocks_data)


@when(u'handler for a new_blocks_received signal is registered')  # noqa
def step_impl(context):
    context.new_blocks_received_handler = mock.MagicMock()
    from pyethereum.signals import remote_blocks_received
    remote_blocks_received.connect(context.new_blocks_received_handler)


@then(u'the new_blocks_received handler should be'  # noqa
' called once with the blocks data')
def step_impl(context):
    context.new_blocks_received_handler = mock.MagicMock()
    from pyethereum.signals import remote_blocks_received
    remote_blocks_received.connect(
        context.new_blocks_received_handler)


@given(u'a GetChain request data')  # noqa
def step_impl(context):
    context.request_data = ['Parent1', 'Parent2', 3]


@when(u'peer.send_GetChain is called withe the request data')  # noqa
def step_impl(context):
    context.peer.send_GetChain(context.request_data)


@then(u'the packet sent through connection'  # noqa
' should be a GetChain packet')
def step_impl(context):
    packet = context.packeter.dump_GetChain(context.request_data)
    assert context.sent_packets == [packet]


@given(u'a GetChain packet with the request data')  # noqa
def step_impl(context):
    context.packet = context.packeter.dump_GetChain(context.request_data)


@given(u'a chain data provider')  # noqa
def step_impl(context):
    from pyethereum.signals import (local_chain_requested)

    def handler(sender, **kwargs):
        pass

    context.blocks_requested_handler = handler
    local_chain_requested.connect(handler)


@when(u'peer.send_Blocks is instrumented')  # noqa
def step_impl(context):
    context.peer.send_Blocks = instrument(context.peer.send_Blocks)


@when(u'peer.send_NotInChain is called')  # noqa
def step_impl(context):
    context.peer.send_NotInChain('some hash')


@then(u'the packet sent through connection should'  # noqa
' be a NotInChain packet')
def step_impl(context):
    packet = context.packeter.dump_NotInChain('some hash')
    assert context.sent_packets == [packet]


@given(u'a NotInChain packet')  # noqa
def step_impl(context):
    context.packet = context.packeter.dump_NotInChain('some hash')
