@config @peer
Feature: peer

  Scenario: peer can send Hello
    When peer send hello
    Then the packet sent through connection is a Hello packet
