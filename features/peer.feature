@config @peer @wip
Feature: peer

  Scenario: send packet to peer
    Given a packet
    When peer.send_packet is called
    And all data with the peer is processed
    Then the packet sent through connection is the given packet

  Scenario: send Hello to peer
    When peer.send_Hello is called
    And all data with the peer is processed
    Then the packet sent through connection is a Hello packet

  Scenario Outline: disconnect peer when received Hello packet is incompatible
    Given a Hello packet with <incompatible reason> incompatible
    When peer.send_Disconnect is observed
    And received the packet from peer
    And all data with the peer is processed
    Then peer.send_Disconnect should be called once with args: reason

    Examples:
      | incompatible reason |
      | protocol version    |
      | network id          |

  Scenario: send Ping to peer
    When peer.send_Ping is called
    And all data with the peer is processed
    Then the packet sent through connection is a Ping packet
