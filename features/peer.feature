@config @peer @wip
Feature: peer

  Scenario: send packet to peer
    Given a packet
    When peer.send_packet is called
    And all data with the peer is processed
    Then the packet sent through connection should be the given packet

  Scenario: send Hello to peer
    When peer.send_Hello is called
    And all data with the peer is processed
    Then the packet sent through connection should be a Hello packet

  Scenario: receive a valid Hello packet
    Given a valid Hello packet
    When peer.send_Hello is instrumented
    And the packet is received from peer
    And all data with the peer is processed
    Then peer.send_Hello should be called once

  Scenario: receive two valid Hello packets
    Given a valid Hello packet
    When peer.send_Hello is instrumented
    And the packet is received from peer
    And the packet is received from peer
    And all data with the peer is processed
    Then peer.send_Hello should be called once

  Scenario Outline: receive an incompatible Hello packet
    Given a Hello packet with <incompatible reason> incompatible
    When peer.send_Disconnect is instrumented
    And the packet is received from peer
    And all data with the peer is processed
    Then peer.send_Disconnect should be called once with args: reason

    Examples:
      | incompatible reason |
      | protocol version    |
      | network id          |

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
    And peers data
    And a peers data provider
    '''which handle peers_data_requested signal
    and send peers_data_ready signal
    '''
    When peer.send_Peers is instrumented
    And the packet is received from peer
    And all data with the peer is processed
    Then peer.send_Peers should be called once with the peers data

  Scenario: send Peers to peer
    Given peers data
    When peer.send_Peers is called
    And all data with the peer is processed
    Then the packet sent through connection should be a Peers packet with the peers data

  Scenario: receive a Peers packet
    Given peers data
    And a Peers packet with the peers data
    When handler for a new_peer_received signal is registered
    And the packet is received from peer
    And all data with the peer is processed
    Then the new_peer_received handler should be called once for each peer
