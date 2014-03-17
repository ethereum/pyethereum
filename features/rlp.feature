Feature: RLP encoding and decoding

  Scenario: payload is a single byte in [0x00, 0x7f]
    Given the byte is in [0x00, 0x7f] range
    When encoded in RLP
    Then the byte is its own RLP encoding


  Scenario Outline: payload is a [0-55] long string
    Given <src>
    When encoded in RLP
    Then the first byte is 0x80 plus the length of the string
    And followed by the string

    Examples: 0-55 string
      | src                                        |
      | a single byte is not in [0x00, 0x7f] range |
      | a blank string                             |
      | a 2-55 bytes long string                   |


  Scenario: payload is a [56-] long string
    Given a string longer than 55
    When encoded in RLP
    Then the first byte is 0xb7 plus the length of the length of the string
    And following bytes are the payload string length
    And following bytes are the payload string itself


  Scenario: payload is a list with total length [0-55]
    Given a list with length of [0-55]
    When encoded in RLP
    Then the first byte is 0xc0 plus the length of the list
    And following bytes are concatenation of the RLP encodings of the items


  Scenario: payload is a list with total length [56-]
    Given a list with length of [56-]
    When encoded in RLP
    Then the first byte is 0xf7 plus the length of the length of the list
    And following bytes are the payload list length
    And following bytes are the payload list itself
