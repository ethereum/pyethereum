@packeter
Feature: packeter

  @wip
  Scenario Outline: data can be packed correctly
    Given to be packeted payload data: <payload>
    When packeted
    Then bytes [0:4) is synchronisation token: (0x22400891)
    And bytes [4:8) is "payload size"(big-endian integer)
    And bytes [8:] data equal to RLP-serialised payload data

    Examples:
      | payload |
      | ''      |
      | 'a'*15  |
      | [1]*15  |
