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


@given(u'peer manager with connected peers')  # noqa
def step_impl(context):
    context.peer_manager.add_peer(utils.mock_connection(), '127.0.0.1', 1234)
    context.peer_manager.add_peer(utils.mock_connection(), '1.1.1.1', 1234)


@when(u'instrument each peer\'s `stop` method')  # noqa
def step_impl(context):
    for peer in context.peer_manager.connected_peers:
        peer.stop = utils.instrument(peer.stop)


@when(u'the peer manager\'s `stop` method is called')  # noqa
def step_impl(context):
    context.peer_manager.stop()


@then(u'each peer\'s `stop` method should be called once')  # noqa
def step_impl(context):
    for peer in context.peer_manager.connected_peers:
        assert peer.stop.call_count == 1


@given(u'connected peer addresses, with each item is (ip, port, node_id)')  # noqa
def step_impl(context):
    context.peer_addresses = (
        ('192.168.1.2', 1234, 'it'),
        ('192.18.1.2', 1234, 'he'),
        ('192.68.1.2', 1234, 'she'),
    )


@given(u'add the connected peer addresses to `connected_peers`')  # noqa
def step_impl(context):
    context.peer_manager.connected_peers = []
    for ip, port, node_id in context.peer_addresses:
        peer = utils.mock_peer(utils.mock_connection(), ip, port)
        peer.node_id = node_id
        context.peer_manager.connected_peers.append(peer)


@then(u'get_connected_peer_addresses should'  # noqa
' return the given peer addresses')
def step_impl(context):
    res = context.peer_manager.get_connected_peer_addresses()
    for peer_address in context.peer_addresses:
        assert peer_address in res


@given(u'peer address of (ip, port, node_id)')  # noqa
def step_impl(context):
    context.peer_address = ('192.168.1.1', 1234, 'me')


@when(u'add_known_peer_address is called with the given peer address')  # noqa
def step_impl(context):
    context.peer_manager.add_known_peer_address(*context.peer_address)


@then(u'get_known_peer_addresses should contain the given peer address')  # noqa
def step_impl(context):
    res = context.peer_manager.get_known_peer_addresses()
    assert context.peer_address in res


@given(u'the given peer is added')  # noqa
def step_impl(context):
    context.peer = context.peer_manager.add_peer(*context.peer_data)


@when(u'remove_peer is called with the peer')  # noqa
def step_impl(context):
    context.peer_manager.remove_peer(context.peer)


@then(u'the peer should be stopped')  # noqa
def step_impl(context):
    assert context.peer.stopped()


@then(u'the peer should not present in connected_peers')  # noqa
def step_impl(context):
    assert context.peer not in context.peer_manager.connected_peers
