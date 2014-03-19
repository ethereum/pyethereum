Feature: Compact encoding of hex sequence with optional terminator

  Scenario: Even length hex sequence, without terminator
    Given an Even length hex sequence
    When compactly encoded
    Then the prefix hex sequence should be 0x0, 0x0
    And hex sequence after the prefix should equal to the original hex sequence
    And decode the compactly encoded hex sequence will get the original one

  Scenario: Odd length hex sequence, without terminator
    Given an odd length hex sequence
    When compactly encoded
    Then the prefix hex sequence should be 0x1
    And hex sequence after the prefix should equal to the original hex sequence
    And decode the compactly encoded hex sequence will get the original one

  Scenario: Even length hex sequence, with terminator
    Given an Even length hex sequence
    When append a terminator
    And compactly encoded
    And remove terminator from source
    Then the prefix hex sequence should be 0x2, 0x0
    And hex sequence after the prefix should equal to the original hex sequence
    And decode the compactly encoded hex sequence will get the original one

  Scenario: Odd length hex sequence, with terminator
    Given an odd length hex sequence
    When append a terminator
    And compactly encoded
    And remove terminator from source
    Then the prefix hex sequence should be 0x3
    And hex sequence after the prefix should equal to the original hex sequence
    And decode the compactly encoded hex sequence will get the original one
