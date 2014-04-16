from utils import instrument


@given(u'a packet')  # noqa
def step_impl(context):
    context.packet = context.packeter.dump_packet('this is a test packet')


@when(u'peer.send_packet is called')  # noqa
def step_impl(context):
    context.peer.send_packet(context.packet)


@when(u'all data with the peer is processed')  # noqa
def step_impl(context):
    context.peer.run()


@then(u'the packet sent through connection is the given packet')  # noqa
def step_impl(context):
    assert context.sent_packets == [context.packet]


@when(u'peer.send_Hello is called')  # noqa
def step_impl(context):
    context.peer.send_Hello()


@then(u'the packet sent through connection is a Hello packet')  # noqa
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
            packeter.config.get('wallet', 'pub_key')
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
            packeter.config.get('wallet', 'pub_key')
            ]
    context.packet = packeter.dump_packet(data)


@when(u'peer.send_Hello is instrumented')  # noqa
def step_impl(context):
    context.peer.send_Hello = instrument(context.peer.send_Hello)


@then(u'peer.send_Hello should be called once')  # noqa
def step_impl(context):
    func = context.peer.send_Hello
    assert func.called
    assert func.call_count == 1


@when(u'peer.send_Disconnect is instrumented')  # noqa
def step_impl(context):
    context.peer.send_Disconnect = instrument(context.peer.send_Disconnect)


@when(u'received the packet from peer')  # noqa
def step_impl(context):
    context.add_recv_packet(context.packet)


@then(u'peer.send_Disconnect should be called once with args: reason')  # noqa
def step_impl(context):
    func = context.peer.send_Disconnect
    assert func.called
    assert func.call_count == 1
    assert len(func.call_args[0]) == 1 or 'reason' in func.call_args[1]


@when(u'peer.send_Ping is called')  # noqa
def step_impl(context):
    context.peer.send_Ping()


@then(u'the packet sent through connection is a Ping packet')  # noqa
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
    assert func.called
    assert func.call_count == 1
