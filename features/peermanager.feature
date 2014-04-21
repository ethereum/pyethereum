@config @peermanager @wip
Feature: peer manager

  Scenario: add_peer
    Given peer data of (connection, ip, port)
    When add_peer is called with the given peer data
    Then connected_peers should contain the peer with the peer data


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

