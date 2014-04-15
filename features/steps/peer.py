@when(u'peer send hello')  # noqa
def step_impl(context):
    context.peer.send_Hello()
    context.set_recv_packet('')
    context.peer.loop_body()


@then(u'the packet sent through connection is a Hello packet')  # noqa
def step_impl(context):
    packet = context.packeter.dump_Hello()
    assert context.get_sent_packet() == [packet]
