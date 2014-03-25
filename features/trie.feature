@trie
Feature: trie tree manipulate

  # here (key, value) is called pair

  Scenario: clear trie tree
    When clear trie tree
    Then root will be blank

  Scenario: insert single node
    Given a pair with key "AB"
    When clear trie tree
    And insert pairs
    Then for each pair, get with key will return the correct value

  Scenario: insert to a key value node, result a key value node and a new diverge node with value in the latest index
    Given a pair with key "AB"
    And a pair with key "ABCD"
    When clear trie tree
    And insert pairs
    Then for each pair, get with key will return the correct value

  Scenario: insert to a key value node, result a key value node and a new diverge node without value in the latest index
    Given a pair with key "AB"
    And a pair with key "AC"
    When clear trie tree
    And insert pairs
    Then for each pair, get with key will return the correct value

  Scenario: insert to a key value node, result a new diverge node without value in the latest index
    Given a pair with key "A"
    And a pair with key "Z"
    When clear trie tree
    And insert pairs
    Then for each pair, get with key will return the correct value

  Scenario: insert to same slot in a diverge node
    Given a pair with key "A"
    And a pair with key "Z"
    Given a pair with key "B"
    When clear trie tree
    And insert pairs
    Then for each pair, get with key will return the correct value

  Scenario: insert to same slot in a diverge node
    Given a pair with key "AB"
    And a pair with key "AC"
    And a pair with key "ABCD"
    When clear trie tree
    And insert pairs
    Then for each pair, get with key will return the correct value

  @load_data
  Scenario: insert in a more sophisticated case
    Then for each pair, get with key will return the correct value

