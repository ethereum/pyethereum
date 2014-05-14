@config @processblock
Feature: processblock

  Scenario Outline: process block containing sha3 opcode
    Given a block
    And a contract which returns the result of the SHA3 opcode
    When a msg is sent to the contract with msg.data[0] = <msg data>
    Then the contract should return the result of sha3(msg.data[0])

    Examples:
      | msg data     |
      | 'hello'      |
      | 342156       |
      | 'a5b2cc1f54' |

