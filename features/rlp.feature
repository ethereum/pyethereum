Feature: RLP encoding and decoding

  Scenario: a single byte
    Given the byte is in [0x00, 0x7f] range
    When encoded in RLP
    Then the byte is its own RLP encoding

  Scenario Outline: the string is [0-55] long
    Given <src>
    When encoded in RLP
    Then the first byte is 0x80 plus the length of the string
    And followed by the string

    Examples: 0-55 string
      | src                                        |
      | a single byte is not in [0x00, 0x7f] range |
      | a blank string                             |
      | a 2-55 bytes long string                   |
