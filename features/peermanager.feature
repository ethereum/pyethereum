@config @peermanager @wip
Feature: peer manager

  Scenario: add_peer
    Given peer data of (connection, ip, port)
    When add_peer is called with the given peer data
    Then connected_peers should contain the peer with the peer data

  Scenario: stop
    Given peer manager with connected peers
    When instrument each peer's `stop` method
    And the peer manager's `stop` method is called
    Then each peer's `stop` method is called once

