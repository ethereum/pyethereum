@config @packeter
Feature: packeter

  Scenario Outline: data can be packed correctly
    Given to be packeted payload data: <payload>
    When dump the data to packet
    Then bytes [0:4) is synchronisation token: (0x22400891)
    And bytes [4:8) is "payload(rlp serialized data) size" in form of big-endian integer
    And bytes [8:] data equal to RLP-serialised payload data

    Examples:
      | payload |
      | ''      |
      | 'a'*15  |
      | [1]*15  |
