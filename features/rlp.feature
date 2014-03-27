Feature: RLP encoding and decoding


  Scenario Outline: payload is a single byte in [0x00, 0x7f]
    Given a payload string: <src>
    When encoded in RLP
    Then the byte is its own RLP encoding
    And decode the RLP encoded data will get the original data

    Examples:
      | src       |
      | chr(0x00) |
      | chr(0x71) |
      | chr(0x7f) |


  Scenario Outline: payload is a [0-55] long string
    Given a payload string: <src>
    When encoded in RLP
    Then the first byte is 0x80 plus the length of the string
    And followed by the string
    And decode the RLP encoded data will get the original data

    Examples: a blank string
      | src |
      | ""  |

    Examples: a single byte is not in [0x00, 0x7f] range
      | src       |
      | chr(0x80) |
      | chr(0x81) |
      | chr(0xFF) |

    Examples: 'a 2-55 bytes long string'
      | src      |
      | 'abcd'   |
      | 'a' * 55 |


  Scenario Outline: payload is a [56-] long string
    Given a payload string: <src>
    When encoded in RLP
    Then the first byte is 0xb7 plus the length of the length of the string
    And following bytes are the payload string length
    And following bytes are the payload string itself
    And decode the RLP encoded data will get the original data

    Examples:
      | src        |
      | 'a' * 56   |
      | 'a' * 1024 |


  Scenario Outline: payload is a list with total length [0-55]
    Given a payload string: <src>
    When encoded in RLP
    Then the first byte is 0xc0 plus the length of the list
    And following bytes are concatenation of the RLP encodings of the items
    And decode the RLP encoded data will get the original data

    Examples:
      | src             |
      | []              |
      | ['foo', 'bar']  |
      | ['a', 'b', 'c'] |
      | ['a'] * 55      |

  Scenario Outline: payload is a list with total length [56-]
    Given a payload string: <src>
    When encoded in RLP
    Then the first byte is 0xf7 plus the length of the length of the list
    And following bytes are the payload list length
    And following bytes are the payload list itself
    And decode the RLP encoded data will get the original data

    Examples:
      | src                          |
      | [str(x) for x in range(100)] |
      | ['a'] * 56                   |
      | ['a'] * 1024                 |


  Scenario Outline: payload containing elements of unsupported type
    Given a payload string: <src>
    Then raise TypeError

    Examples:
      | src          |
      | [0]          |
      | [1]          |
      | [None]       |
      | [1, 'ok']    |
      | [None, 'ok'] |
      | [[1], 'ok']  |
