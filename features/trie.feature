Feature: trie tree manipulate

  # here (key, value) is called pair
  # pair1 with key "AB"
  # pair2 with key "AC"
  # pair3 with key "ABCD"
  # pair4 with key "ACD"

  Scenario: clear trie tree
    When clear trie tree
    Then root will be blank

  Scenario: insert single node
    Given pair1 with key "AB"
    When clear trie tree
    Then get with key of pair1 will return the correct value

  Scenario: insert result a new child (key, value) node
    Given pair1 with key "AB"
    And pair3 with key "ABCD"
    When clear trie tree
    And insert pair1
    And insert pair3
    Then get with key of pair3 will return the correct value

  Scenario: insert result a 17 elements node
    Given pair1 with key "AB"
    And pair2 with key "AC"
    When clear trie tree
    And insert pair1
    And Insert pair2
    Then get with key of pair2 will return the correct value

  Scenario: insert in a more sophisticated case
    Given pair1 with key "AB"
    And pair2 with key "AC"
    And pair3 with key "ABCD"
    And pair4 with key "ACD"
    And pair5 with key "A"
    And pair6 with key "B"
    And pair7 with key "BCD"
    When clear trie tree
    And insert pair1
    And Insert pair2
    And insert pair3
    And insert pair4
    And insert pair5
    And insert pair6
    And insert pair7
    Then get with key of pair7 will return the correct value
