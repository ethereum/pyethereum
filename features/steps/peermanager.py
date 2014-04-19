import utils


@given(u'peer data of (connection, ip, port)')  # noqa
def step_impl(context):
    context.peer_data = (utils.mock_connection(), '127.0.0.1', 1234)


@when(u'add_peer is called with the given peer data')  # noqa
def step_impl(context):
    context.peer_manager.add_peer(*context.peer_data)


@then(u'connected_peers should contain the peer with the peer data')  # noqa
def step_impl(context):
    manager = context.peer_manager
    data = context.peer_data
    assert len(list(p for p in manager.connected_peers
               if p.connection() == data[0])) == 1
