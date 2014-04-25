import utils
import mock


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


@when(u'_create_peer_sock')  # noqa
def step_impl(context):
    context.res = context.peer_manager._create_peer_sock()


@then(u'return a socket')  # noqa
def step_impl(context):
    assert context.res


@given(u'peer address of (host, port)')  # noqa
def step_impl(context):
    context.peer_address = ('myhost', 1234)


@when(u'socket is mocked')  # noqa
def step_impl(context):
    context.peer_manager._create_peer_sock = mock.MagicMock()
    context.sock = context.peer_manager._create_peer_sock.return_value
    context.sock.getpeername.return_value = ('192.168.1.1', 1234)


@then(u'socket.connect should be called with (host, port)')  # noqa
def step_impl(context):
    assert context.sock.connect.call_args[0][0] == context.peer_address


@when(u'call of socket.connect will success')  # noqa
def step_impl(context):
    pass


@when(u'add_peer is mocked, and the return value is recorded as peer')  # noqa
def step_impl(context):
    context.peer_manager.add_peer = mock.MagicMock()
    context.peer = context.peer_manager.add_peer.return_value


@when(u'send_Hello is mocked')  # noqa
def step_impl(context):
    context.peer_manager.send_Hello = mock.MagicMock()


@when(u'connect_peer is called with the given peer address')  # noqa
def step_impl(context):
    context.res = context.peer_manager.connect_peer(*context.peer_address)


@then(u'add_peer should be called once')  # noqa
def step_impl(context):
    assert context.peer_manager.add_peer.call_count == 1


@then(u'the peer should have send_Hello called once')  # noqa
def step_impl(context):
    assert context.peer.send_Hello.call_count == 1


@then(u'connect_peer should return peer')  # noqa
def step_impl(context):
    assert context.res == context.peer


@when(u'call of socket.connect will fail')  # noqa
def step_impl(context):
    def side_effect():
        raise Exception()
    context.sock.connect.side_effect = side_effect


@then(u'add_peer should not be called')  # noqa
def step_impl(context):
    assert context.peer_manager.add_peer.call_count == 0


@then(u'connect_peer should return None')  # noqa
def step_impl(context):
    assert context.res is None


@when(u'get_known_peer_addresses is mocked')  # noqa
def step_impl(context):
    context.peer_manager.get_known_peer_addresses = mock.MagicMock(
        return_value=set([
            ('192.168.1.1', 1234, 'it'),
            ('1.168.1.1', 1234, 'he'),
            ('1.1.1.1', 1234, 'me'),
        ]))


@when(u'get_connected_peer_addresses is mocked')  # noqa
def step_impl(context):
    context.peer_manager.get_connected_peer_addresses = mock.MagicMock(
        return_value=set([
            ('192.168.1.1', 1234, 'it'),
            ('9.168.1.1', 1234, 'she'),
        ]))


@when(u'local_address is local_address')  # noqa
def step_impl(context):
    context.peer_manager.local_addresses = [('1.1.1.1', 1234)]


@when(u'get_peer_candidates is called')  # noqa
def step_impl(context):
    context.res = context.peer_manager.get_peer_candidates()


@then(u'the result candidates should be right')  # noqa
def step_impl(context):
    right = set([
        ('1.168.1.1', 1234, 'he'),
    ])

    assert right == set(context.res)


@given(u'a mock stopped peer')  # noqa
def step_impl(context):
    from pyethereum.peer import Peer
    context.peer = mock.MagicMock(spec=Peer)
    context.peer.stopped = mock.MagicMock(return_value=True)


@when(u'remove_peer is mocked')  # noqa
def step_impl(context):
    context.peer_manager.remove_peer = mock.MagicMock()


@when(u'_check_alive is called with the peer')  # noqa
def step_impl(context):
    context.peer_manager._check_alive(context.peer)


@then(u'remove_peer should be called once with the peer')  # noqa
def step_impl(context):
    assert context.peer_manager.remove_peer.call_count == 1


@given(u'a mock normal peer')  # noqa
def step_impl(context):
    from pyethereum.peer import Peer
    context.peer = Peer(utils.mock_connection(), '1.1.1.1', 1234)
    context.peer.send_Ping = mock.MagicMock()


@when(u'time.time is patched')  # noqa
def step_impl(context):
    context.time_time_pactcher = mock.patch('pyethereum.peermanager.time.time')
    context.time_time = context.time_time_pactcher.start()
    context.time_time.return_value = 10


@when(u'ping was sent and not responsed in time')  # noqa
def step_impl(context):
    context.peer.last_pinged = 4
    context.peer.last_valid_packet_received = 1
    context.peer_manager.max_ping_wait = 5
    context.peer_manager.max_silence = 2

    now = context.time_time()
    dt_ping = now - context.peer.last_pinged
    dt_seen = now - context.peer.last_valid_packet_received

    assert dt_ping < dt_seen and dt_ping > context.peer_manager.max_ping_wait


@when(u'time.time is unpatched')  # noqa
def step_impl(context):
    context.time_time_pactcher.stop()


@when(u'peer is slient for a long time')  # noqa
def step_impl(context):
    context.peer.last_pinged = 4
    context.peer.last_valid_packet_received = 7
    context.peer_manager.max_ping_wait = 5
    context.peer_manager.max_silence = 2

    now = context.time_time()
    dt_ping = now - context.peer.last_pinged
    dt_seen = now - context.peer.last_valid_packet_received

    assert min(dt_seen, dt_ping) > context.peer_manager.max_silence


@then(u'peer.send_Ping should be called once')  # noqa
def step_impl(context):
    assert context.peer.send_Ping.call_count == 1


@given(u'connected peers')  # noqa
def step_impl(context):
    from pyethereum.peer import Peer
    context.peer_manager.connected_peers = [
        Peer(utils.mock_connection(), '1.1.1.1', 1234),
        Peer(utils.mock_connection(), '2.1.1.1', 1234),
    ]


@when(u'connect_peer is mocked')  # noqa
def step_impl(context):
    context.peer_manager.connect_peer = mock.MagicMock()


@given(u'known peers')  # noqa
def step_impl(context):
    context.peer_manager._known_peers = [
        ('192.168.1.2', 1234, 'it'),
        ('192.18.1.2', 1234, 'he'),
        ('192.68.1.2', 1234, 'she')]


@when(u'connected peers less then configured number of peers')  # noqa
def step_impl(context):
    configured_number = context.conf.getint('network', 'num_peers')
    assert len(context.peer_manager.connected_peers) < configured_number


@when(u'have candidate peer')  # noqa
def step_impl(context):
    candidates = context.peer_manager.get_peer_candidates()
    assert len(candidates)


@when(u'save known_peers count')  # noqa
def step_impl(context):
    context.known_peers_count_saved = len(context.peer_manager._known_peers)


@when(u'_connect_peers is called')  # noqa
def step_impl(context):
    context.peer_manager._connect_peers()


@then(u'connect_peer should be called')  # noqa
def step_impl(context):
    assert context.peer_manager.connect_peer.call_count == 1


@then(u'known_peers should be one less the saved count')  # noqa
def step_impl(context):
    assert context.known_peers_count_saved - 1 == \
        len(context.peer_manager._known_peers)


@when(u'have no candidate peer')  # noqa
def step_impl(context):
    context.peer_manager.get_peer_candidates = mock.MagicMock(
        return_value=[])


@when(u'for each connected peer, send_GetPeers is mocked')  # noqa
def step_impl(context):
    for peer in context.peer_manager.connected_peers:
        peer.send_GetPeers = mock.MagicMock()


@then(u'for each connected peer, send_GetPeers should be called')  # noqa
def step_impl(context):
    for peer in context.peer_manager.connected_peers:
        assert peer.send_GetPeers.call_count == 1
