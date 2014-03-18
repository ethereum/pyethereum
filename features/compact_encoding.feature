Feature: Compact encoding of hex string with optional terminator

  Scenario: Even length hex string, without terminator
    Given an Even length hex string
    When compactly encoded
    Then the first byte should be 0x00
    And the remain bits with be same of the original hex string
    And decode the compactly encoded hex string will get the original hex string

  Scenario: Odd length hex string, without terminator
    Given an odd length hex string
    When compactly encoded
    Then the first byte should start with 0x1
    And the remain bits with be same of the original hex string
    And decode the compactly encoded hex string will get the original hex string

  Scenario: Even length hex string, with terminator
    Given an odd length hex string
    When append a terminator
    And compactly encoded
    Then the first byte should start with 0x2
    And the remain bits with be same of the original hex string
    And decode the compactly encoded hex string will get the original hex string

  Scenario: Odd length hex string, with terminator
    Given an odd length hex string
    When append a terminator
    And compactly encoded
    Then the first byte should start with 0x3
    And the remain bits with be same of the original hex string
    And decode the compactly encoded hex string will get the original hex string
