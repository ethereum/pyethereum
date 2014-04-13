@when(u'I receive a HELLO command from peer')  # noqa
def step_impl(context):
    context.packet = context.packeter.dump_Hello()
    context.wireprotocol.rcv_packet(context.peer, context.packet)


@then(u'a HELLO will be sent to peer')  # noqa
def step_impl(context):
    context.peer.send_packet.assert_called_once_with(context.peer, context.packet)
