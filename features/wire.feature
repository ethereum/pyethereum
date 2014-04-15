# Feature: wire protocol

#   Scenario: hello
#     When I receive a HELLO command from peer
#     Then a HELLO will be sent to peer

#   Scenario: receive disconnect
#     When I receive a DISCONNECT command form peer
#     Then I will disconnect peer immediately.

#   Scenario: send disconnect
#     When I send a DISCONNECT to peer
#     Then I will wait for 2 senconds to before disconnecting peer

#   Scenario: ping pong
#     When I receive a PING command from peer
#     Then I will send a PONG command to peer

#   Scenario: get peers
#     When I receive a GET_PEERS command from peer
#     Then I will send a PEERS command to peer
#     And with all known peers
#     And including me as peer too

#   Scenario: get transactions
#     When I receive a GET_TRANSACTIONS command from peer
#     Then I will send a TRANSACTIONS command to peer
#     And with all transactions currently in the queue

#   Scenario: transactions
#     When I receive a TRANSACTIONS command from peer
#     Then I will make sure the transactions are included in my transaction queue

#   Scenario: blocks
#     When I receive a BLOCKS command from peer
#     Then I will know about the blocks

#   Scenario: get chain with first parent presented in the block chain
#     Given a `count`
#     When I receive a GET_CHAIN command from peer, request `count` blocks
#     And the first parent presented in the block chain
#     Then I will send a BLOCKS command to peer
#     And with up to `count` blocks
#     And the blocks are in the current canonical block chain that are children of the first parent

#   Scenario: get chain with parent is the current block chain head
#     Given a `count`
#     When I receive a GET_CHAIN command from peer, request `count` blocks
#     And the first parent presented in the block chain
#     And the first parent is the current block chain head
#     Then I will send a BLOCKS command to peer
#     And with zero blocks

#   Scenario: get chain with first parent not presented in the block chain, but the second parent is presented
#     Given a `count`
#     When I receive a GET_CHAIN command from peer, request `count` blocks
#     And the first parent is not presented in the block chain
#     And the second parent is presented in the block chain
#     Then I will send a BLOCKS command to peer
#     And with up to `count` blocks
#     And the blocks are in the current canonical block chain that are children of the second parent

#   Scenario: get chain without any parents presented in the block chain
#     Given a `count`
#     When I receive a GET_CHAIN command from peer, request `count` blocks
#     And none of the parents is presented in the block chain
#     Then I will send a NOT_IN_CHAIN command to peer

#   Scenario: get chain without no parents
#     Given a `count`
#     When I receive a GET_CHAIN command from peer, request `count` blocks
#     And no parents are given
#     Then I will send no response to peer
