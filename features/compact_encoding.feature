Feature: Compact encoding of hex sequence with optional terminator

  Scenario: Even length hex sequence, without terminator
    Given an Even length hex sequence
    When compactly encoded
    Then the first byte should be 0x00
    And the remain bits will be same of the original hex sequence
    And decode the compactly encoded hex sequence will get the original one

  Scenario: Odd length hex sequence, without terminator
    Given an odd length hex sequence
    When compactly encoded
    Then the first byte should start with 0x1
    And the remain bits will be same of the original hex sequence
    And decode the compactly encoded hex sequence will get the original one

  Scenario: Even length hex sequence, with terminator
    Given an odd length hex sequence
    When append a terminator
    And compactly encoded
    And remove terminator from source
    Then the first byte should start with 0x2
    And the remain bits will be same of the original hex sequence
    And decode the compactly encoded hex sequence will get the original one

  Scenario: Odd length hex sequence, with terminator
    Given an odd length hex sequence
    When append a terminator
    And compactly encoded
    And remove terminator from source
    Then the first byte should start with 0x3
    And the remain bits will be same of the original hex sequence
    And decode the compactly encoded hex sequence will get the original one
