import utils
import mock
import os
import json
from pyethereum.utils import big_endian_to_int as idec

@given(u'data_dir')
def step_impl(context):
    context.data_dir = context.peer_manager.config.get('misc', 'data_dir')
    assert(not context.data_dir == None)

@given(u'a peers.json file exists')
def step_impl(context):
    peers = set([('12.13.14.15', 2002), ('14.15.16.17', 3003)])
    context.path = os.path.join(context.data_dir, 'peers.json')
    json.dump(list(peers), open(context.path, 'w'))

@given(u'_known_peers is empty')
def step_impl(context):
    assert(len(context.peer_manager._known_peers) == 0)

@when(u'load_saved_peers is called')
def step_impl(context):
    context.peer_manager.load_saved_peers()

@then(u'_known_peers should contain all peers in peers.json with blank node_ids')
def step_impl(context):
    peers = json.load(open(context.path))
    os.remove(context.path)
    for i,p in peers:
        assert((i, p, "") in context.peer_manager._known_peers)

@given(u'a peers.json file does not exist')
def step_impl(context):
    context.path = os.path.join(context.peer_manager.config.get('misc', 'data_dir'), 'peers.json')
    assert (not os.path.exists(context.path))

@then(u'_known_peers should still be empty')
def step_impl(context):
    assert (len(context.peer_manager._known_peers) == 0)

@given(u'peer data of (ip, port, node_id) in _known_peers')
def step_impl(context):
    context.peer_manager._known_peers = set([('12.13.14.15', 2002, "him"), ('14.15.16.17', 3003, "her")])

@when(u'save_peers is called')
def step_impl(context):
    context.peer_manager.save_peers()

@then(u'data_dir/peers.json should contain all peers in _known_peers')
def step_impl(context):
    context.path = os.path.join(context.peer_manager.config.get('misc', 'data_dir'), 'peers.json')
    peers = [(i, p) for i, p in json.load(open(context.path))]
    os.remove(context.path)
    for ip, port, nodeid in context.peer_manager._known_peers:
        assert((ip, port) in peers)

@given(u'peer data of (connection, ip, port) from _known_peers')
def step_impl(context):
    context.peer_manager._known_peers = set([('12.13.14.15', 2002, "him"), ('14.15.16.17', 3003, "her")])
    ip, port, nid = context.peer_manager._known_peers.pop()
    context.peer_data = (utils.mock_connection(), ip, port)

@when(u'add_peer is called with the given peer data')
def step_impl(context):
    context.peer = context.peer_manager.add_peer(*context.peer_data)

@then(u'connected_peers should contain the peer with the peer data')  # noqa
def step_impl(context):
    manager = context.peer_manager
    data = context.peer_data
    assert len(list(p for p in manager.connected_peers
               if p.connection() == data[0])) == 1

@given(u'peer data of (connection, ip, port) from a newly accepted connection')
def step_impl(context):
    context.peer_data = (utils.mock_connection(), '100.100.100.100', 10001)

@then(u'the peer\'s port should be the connection port, not the listen port')
def step_impl(context):
    assert(context.peer_data[2] != 30303) # this is a hack

@then(u'_known_peers should not contain peer (until Hello is received)')
def step_impl(context):
    assert (context.peer_data not in context.peer_manager._known_peers)

@given(u'peer data of (connection, ip, port)')  # noqa
def step_impl(context):
    context.peer_data = (utils.mock_connection(), '127.0.0.1', 1234)


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

@given(u'a Hello has been received from the peer')
def step_impl(context):
    for p in context.peer_manager.connected_peers:
        p.hello_received = True

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
            ('1.1.1.1', 1234, context.conf.get('network', 'node_id')),
        ]))


@when(u'get_connected_peer_addresses is mocked')  # noqa
def step_impl(context):
    context.peer_manager.get_connected_peer_addresses = mock.MagicMock(
        return_value=set([
            ('192.168.1.1', 1234, 'it'),
            ('9.168.1.1', 1234, 'she'),
        ]))

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


@given(u'a peer in connected_peers')  # noqa
def step_impl(context):
    # a random peer with connection port and no id
    context.peer_data = (utils.mock_connection(), '4.5.6.7', 55555)
    context.peer = context.peer_manager._start_peer(*context.peer_data)
    context.peer.node_id = ""

    context.packeter.NODE_ID = 'this is a different node id'

@when(u'Hello is received from the peer')
def step_impl(context):
    from pyethereum.signals import peer_handshake_success
    from pyethereum.peermanager import new_peer_connected

    peer_handshake_success.disconnect(new_peer_connected)

    def peer_handshake_success_handler(sender, peer, **kwargs):
        ipn = peer.ip, peer.port, peer.node_id
        context.peer_manager.add_known_peer_address(*ipn)
    peer_handshake_success.connect(peer_handshake_success_handler)

    context.packet = context.packeter.dump_Hello()
    decoded_packet = context.packeter.load_packet(context.packet)[1][3]
    context.peer._recv_Hello(decoded_packet)

@then(u'the peers port and node id should be reset to their correct values')  # noqa
def step_impl(context):
    from pyethereum.utils import big_endian_to_int as idec
    decoded_packet = context.packeter.load_packet(context.packet)[1][3]
    port = idec(decoded_packet[4])
    node_id = decoded_packet[5]
    assert(context.peer.port == port)
    assert(context.peer.node_id == node_id)

@then(u'peer_manager._known_peers should contain the peer')  # noqa
def step_impl(context):
    i, p, n = context.peer.ip, context.peer.port, context.peer.node_id
    assert((i, p, n) in context.peer_manager._known_peers)

@when(u'_recv_Peers is called')
def step_impl(context):
    from pyethereum.signals import peer_addresses_received
    from pyethereum.peermanager import peer_addresses_received_handler

    peer_addresses_received.disconnect(peer_addresses_received_handler)

    def peer_addresses_received_handler(sender, addresses, **kwargs):
        for address in addresses:
            context.peer_manager.add_known_peer_address(*address)
        context.peer_manager.save_peers()
    peer_addresses_received.connect(peer_addresses_received_handler)

    context.peers_to_send = [('9.8.7.6', 3000, 'him'), ('10.9.8.7', 4000, 'her'), ('12.11.10.9', 5000, 'she')]
    context.packet = context.packeter.dump_Peers(context.peers_to_send)
    decoded_packet = context.packeter.load_packet(context.packet)[1][3]
    context.peer._recv_Peers(decoded_packet)

@then(u'all received peers should be added to _known_peers and saved to peers.json')
def step_impl(context):
    context.path = os.path.join(context.peer_manager.config.get('misc', 'data_dir'), 'peers.json')
    saved_peers = [(i, p) for i, p in json.load(open(context.path))]
    os.remove(context.path)
    for ip, port, nodeid in context.peers_to_send:
        assert((ip, port) in saved_peers)
        assert((ip, port, nodeid) in context.peer_manager._known_peers)

@given(u'a known connected peer with incompatible protocol version')
def step_impl(context):
    context.peer_data = (utils.mock_connection(), '4.5.6.7', 55555)
    context.peer = context.peer_manager.add_peer(*context.peer_data)
    context.ipn = (context.peer.ip, context.peer.port, context.peer.node_id)
    context.peer_manager._known_peers.add(context.ipn)
    context.peer_protocol_version = 0xff

@when(u'send_Disconnect is called with reason "Incompatible"')
def step_impl(context):
    from pyethereum.signals import peer_disconnect_requested
    from pyethereum.peermanager import disconnect_requested_handler

    peer_disconnect_requested.disconnect(disconnect_requested_handler)

    def disconnect_requested_handler(sender, peer, forget=False, **kwargs):
        context.peer_manager.remove_peer(peer)
        if forget:
            ipn = (peer.ip, peer.port, peer.node_id)
            if ipn in context.peer_manager._known_peers:
                context.peer_manager._known_peers.remove(ipn)
                context.peer_manager.save_peers()

    peer_disconnect_requested.connect(disconnect_requested_handler)
    context.peer.send_Disconnect(reason='Incompatible network protocols')

@then(u'peer should be removed from _known_peers')
def step_impl(context):
    ipn = (context.peer.ip, context.peer.port, context.peer.node_id)
    assert(ipn not in context.peer_manager._known_peers)


