Feature: Pack/unpack nibbles to/from binary, with optional nibbles terminator


  Scenario Outline: Even numbers of nibbles, without terminator
    Given nibbles: <nibbles>
    When packed to binary
    Then in the binary, the first nibbles should be 0x0
    And the second nibbles should be 0x0
    And nibbles after should equal to the original nibbles
    And unpack the binary will get the original nibbles

    Examples: even numbers of nibbles
      | nibbles              |
      | []                   |
      | [0x0, 0x1]           |
      | [0x1, 0x2, 0x3, 0x4] |


  Scenario Outline: Even numbers of nibbles, with terminator
    Given nibbles: <nibbles>
    When append a terminator
    And packed to binary
    Then in the binary, the first nibbles should be 0x2
    And the second nibbles should be 0x0
    And nibbles after should equal to the original nibbles
    And unpack the binary will get the original nibbles

    Examples: even numbers of nibbles
      | nibbles              |
      | []                   |
      | [0x0, 0x1]           |
      | [0x1, 0x2, 0x3, 0x4] |


  Scenario Outline: Odd numbers of nibbles, with terminator
    Given nibbles: <nibbles>
    When append a terminator
    And packed to binary
    Then in the binary, the first nibbles should be 0x3
    And nibbles after should equal to the original nibbles
    And unpack the binary will get the original nibbles

    Examples: even numbers of nibbles
      | nibbles         |
      | [0x0]           |
      | [0x1, 0x2, 0x3] |


  Scenario Outline: Odd numbers of nibbles, without terminator
    Given nibbles: <nibbles>
    When packed to binary
    Then in the binary, the first nibbles should be 0x1
    And nibbles after should equal to the original nibbles
    And unpack the binary will get the original nibbles

    Examples: even numbers of nibbles
      | nibbles         |
      | [0x0]           |
      | [0x1, 0x2, 0x3] |
