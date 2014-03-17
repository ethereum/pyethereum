Feature: RLP encoding and decoding

  Scenario: a single byte
    Given the byte is in [0x00, 0x7f] range
    Then the byte is its own RLP encoding

