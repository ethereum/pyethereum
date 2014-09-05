@config @peer
Feature: peer

  Scenario: send packet to peer
    Given a packet
    When peer.send_packet is called
    And all data with the peer is processed
    Then the packet sent through connection should be the given packet

  Scenario: send Ping to peer
    When peer.send_Ping is called
    And all data with the peer is processed
    Then the packet sent through connection should be a Ping packet

  Scenario: receive a Ping packet
    Given a Ping packet
    When peer.send_Pong is instrumented
    And the packet is received from peer
    And all data with the peer is processed
    Then peer.send_Pong should be called once

  Scenario: send Pong to peer
    When peer.send_Pong is called
    And all data with the peer is processed
    Then the packet sent through connection should be a Pong packet

  Scenario: receive a Pong packet
    Given a Pong packet
    When the packet is received from peer
    And all data with the peer is processed

  Scenario: send Disconnect to peer
    When handler for a disconnect_requested signal is registered
    And peer.send_Disconnect is called
    And all data with the peer is processed
    Then the packet sent through connection should be a Disconnect packet
    And the disconnect_requested handler should be called once after sleeping for at least 2 seconds

  Scenario: receive a Disconnect packet
    Given a Disconnect packet
    When handler for a disconnect_requested signal is registered
    And the packet is received from peer
    And all data with the peer is processed
    Then the disconnect_requested handler should be called once

  Scenario: send GetPeers to peer
    When peer.send_GetPeers is called
    And all data with the peer is processed
    Then the packet sent through connection should be a GetPeers packet

  Scenario: receive a GetPeers packet
    Given a GetPeers packet
    When getpeers_received signal handler is connected
    And the packet is received from peer
    And all data with the peer is processed
    Then the getpeers_received signal handler should be called once

  Scenario: send Peers to peer
    Given peers data
    When peer.send_Peers is called
    And all data with the peer is processed
    Then the packet sent through connection should be a Peers packet with the peers data

  Scenario: receive a Peers packet
    Given peers data
    And a Peers packet with the peers data
    When handler for new_peers_received signal is registered
    And the packet is received from peer
    And all data with the peer is processed
    Then the new_peers_received handler should be called once with all peers

  Scenario: send GetTransactions to peer
    When peer.send_GetTransactions is called
    And all data with the peer is processed
    Then the packet sent through connection should be a GetTransactions packet

  Scenario: receive a GetTransactions packet
    Given a GetTransactions packet
    When gettransactions_received signal handler is connected
    And the packet is received from peer
    And all data with the peer is processed
    Then the gettransactions_received signal handler should be called once

  Scenario: send Transactions to peer
    Given transactions data
    When peer.send_Transactions is called
    And all data with the peer is processed
    Then the packet sent through connection should be a Transactions packet with the transactions data

  Scenario: receive a Transactions packet
    Given transactions data
    And a Transactions packet with the transactions data
    When handler for a new_transactions_received signal is registered
    And the packet is received from peer
    And all data with the peer is processed
    Then the new_transactions_received handler should be called once with the transactions data
