@config @peermanager @wip
Feature: peer manager

  Scenario: load_saved_peers where peers.json exists
    Given data_dir
    And a peers.json file exists
    And _known_peers is empty
    When load_saved_peers is called
    Then _known_peers should contain all peers in peers.json with blank node_ids

  Scenario: load_saved_peers where peers.json does not exist
    Given data_dir
    And a peers.json file does not exist
    And _known_peers is empty
    When load_saved_peers is called
    Then _known_peers should still be empty

  Scenario: save_peers
    Given peer data of (ip, port, node_id) in _known_peers
    When save_peers is called
    Then data_dir/peers.json should contain all peers in _known_peers

  Scenario: add_peer from _known_peers
    Given peer data of (connection, ip, port) from _known_peers
    When add_peer is called with the given peer data 
    Then connected_peers should contain the peer with the peer data

  Scenario: add_peer from peer_connection_accepted signal
    Given peer data of (connection, ip, port) from a newly accepted connection
    When add_peer is called with the given peer data
    Then connected_peers should contain the peer with the peer data
    But the peer's port should be the connection port, not the listen port
    And _known_peers should not contain peer (until Hello is received)

  Scenario: _create_peer_sock
    When _create_peer_sock
    Then return a socket

  Scenario: connect peer successfully
    Given peer address of (host, port)
    When socket is mocked
    And call of socket.connect will success
    And add_peer is mocked, and the return value is recorded as peer
    And connect_peer is called with the given peer address
    Then socket.connect should be called with (host, port)
    And add_peer should be called once
    And the peer should have send_Hello called once
    And connect_peer should return peer

  Scenario: connect peer failed
    Given peer address of (host, port)
    When socket is mocked
    And call of socket.connect will fail
    And add_peer is mocked, and the return value is recorded as peer
    And connect_peer is called with the given peer address
    Then socket.connect should be called with (host, port)
    And add_peer should not be called
    And connect_peer should return None

  Scenario: stop
    Given peer manager with connected peers
    When instrument each peer's `stop` method
    And the peer manager's `stop` method is called
    Then each peer's `stop` method should be called once

  Scenario: get connected peer addresses
    Given connected peer addresses, with each item is (ip, port, node_id)
    And add the connected peer addresses to `connected_peers`
    And a Hello has been received from the peer
    Then get_connected_peer_addresses should return the given peer addresses

  Scenario: add/get known peer address
    Given peer address of (ip, port, node_id)
    And connected peer addresses, with each item is (ip, port, node_id)
    And add the connected peer addresses to `connected_peers`
    When add_known_peer_address is called with the given peer address
    Then get_known_peer_addresses should contain the given peer address

  Scenario: remove peer
    Given peer data of (connection, ip, port)
    And the given peer is added
    When remove_peer is called with the peer
    Then the peer should be stopped
    And the peer should not present in connected_peers

  Scenario: get peer candidates
    When get_known_peer_addresses is mocked
    And  get_connected_peer_addresses is mocked
    And get_peer_candidates is called
    Then the result candidates should be right

  Scenario: check alive on stopped peer
    Given a mock stopped peer
    When remove_peer is mocked
    And _check_alive is called with the peer
    Then remove_peer should be called once with the peer

  Scenario: check alive on unalive peer
    Given a mock normal peer
    When time.time is patched
    And ping was sent and not responsed in time
    And remove_peer is mocked
    And _check_alive is called with the peer
    And time.time is unpatched
    Then remove_peer should be called once with the peer

  Scenario: check alive on alive peer
    Given a mock normal peer
    When time.time is patched
    And peer is slient for a long time
    And _check_alive is called with the peer
    And time.time is unpatched
    Then peer.send_Ping should be called once

  Scenario: connect peers
    Given connected peers
    And known peers
    When connect_peer is mocked
    And connected peers less then configured number of peers
    And have candidate peer
    And save known_peers count
    And _connect_peers is called
    Then connect_peer should be called
    And known_peers should be one less the saved count

  Scenario: connect peers
    Given connected peers
    When connect_peer is mocked
    And connected peers less then configured number of peers
    And have no candidate peer
    And for each connected peer, send_GetPeers is mocked
    And _connect_peers is called
    Then for each connected peer, send_GetPeers should be called

  Scenario: receive a valid Hello packet and confirm listen port
    Given a peer in connected_peers
    When Hello is received from the peer
    Then the peers port and node id should be reset to their correct values
    And peer_manager._known_peers should contain the peer

  Scenario: receive a list of peers from another peer
    Given a peer in connected_peers
    When _recv_Peers is called
    Then all received peers should be added to _known_peers and saved to peers.json

  Scenario: peer has incompatible protocol version
    Given a known connected peer with incompatible protocol version
    When send_Disconnect is called with reason "Incompatible"
    Then peer should be removed from _known_peers
