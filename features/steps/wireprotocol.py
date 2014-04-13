@when(u'I receive a HELLO command from peer')  # noqa
def step_impl(context):
    context.packet = context.packeter.dump_Hello()
    context.wireprotocol.recv_packet(context.peer, context.packet)


@then(u'a HELLO will be sent to peer')  # noqa
def step_impl(context):
    context.peer.send_packet.assert_called_once_with(
        context.peer, context.packet)


@when(u'I receive a DISCONNECT command form peer')  # noqa
def step_impl(context):
    context.packet = context.packeter.dump_Disconnect()
    context.wireprotocol.recv_packet(context.peer, context.packet)


@then(u'I will disconnect peer immediately.')  # noqa
def step_impl(context):
    assert False
