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
"""
  Scenario: insert result a new child (key, value) node
    Given a pair with key "AB"
    And a pair with key "ABCD"
    When clear trie tree
    And insert pairs
    Then for each pair, get with key will return the correct value

  Scenario: insert result a 17 elements node
    Given a pair with key "AB"
    And a pair with key "AC"
    When clear trie tree
    And insert pairs
    Then for each pair, get with key will return the correct value

  @load_data
  Scenario: insert in a more sophisticated case
    Then for each pair, get with key will return the correct value
"""

