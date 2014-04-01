Feature: RLP encoding and decoding


  Scenario Outline: payload is a single byte in [0x00, 0x7f]
    Given a to be rlp encoded payload: <src>
    When encoded in RLP
    Then the byte is its own RLP encoding
    And decode the RLP encoded data will get the original data

    Examples:
      | src       |
      | chr(0x00) |
      | chr(0x71) |
      | chr(0x7f) |


  Scenario Outline: payload is a [0-55] long string
    Given a to be rlp encoded payload: <src>
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
    Given a to be rlp encoded payload: <src>
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
    Given a to be rlp encoded payload: <src>
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
    Given a to be rlp encoded payload: <src>
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
    Given a to be rlp encoded payload: <src>
    Then raise TypeError

    Examples:
      | src          |
      | [{}]         |
      | [None]       |
      | [{}, 'ok']   |
      | [None, 'ok'] |
      | [[{}], 'ok'] |

  Scenario Outline: conform to fixture
    Given a to be rlp encoded payload: <in>
    When encoded in RLP
    Then the rlp encoded result will be equal to <out>
    And decode the RLP encoded data will get the original data

    Examples: smallint
      | in   | out   |
      | 1    | "01"  |

    Examples: multilist
      | in              | out              |
      | [u'zw', [4], 1] | "c6827a77c10401" |

    Examples: listsoflists
      | in             | out          |
      | [[[], []], []] | "c4c2c0c0c0" |

    Examples: emptylist
      | in   | out   |
      | []   | "c0"  |

    Examples: mediumint
      | in   | out      |
      | 1000 | "8203e8" |

    Examples: zero
      | in   | out   |
      | 0    | "80"  |

    Examples: longstring
      | in                                                         | out                                                                                                                    |
      | "Lorem ipsum dolor sit amet, consectetur adipisicing elit" | "b8384c6f72656d20697073756d20646f6c6f722073697420616d65742c20636f6e7365637465747572206164697069736963696e6720656c6974" |

    Examples: shortstring
      | in    | out        |
      | "dog" | "83646f67" |

    Examples: bigint
      | in                                                                             | out                                                                    |
      | 115792089237316195423570985008687907853269984665640564039457584007913129639936 | "a1010000000000000000000000000000000000000000000000000000000000000000" |

    Examples: emptystring
      | in   | out   |
      | ""   | "80"  |

    Examples: stringlist
      | in                       | out                          |
      | [u'dog', u'god', u'cat'] | "cc83646f6783676f6483636174" |

