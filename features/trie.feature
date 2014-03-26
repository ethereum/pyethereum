@trie
Feature: trie tree manipulate

  # here (key, value) is called pair

  Scenario: clear trie tree
    When clear trie tree
    Then root will be blank

  Scenario: insert to a blank tree
    Given a pair with key "AB"
    When clear trie tree
    And insert pairs
    Then for each pair, get with key will return the correct value

  # ---- start: insert to a key value node---------
  Scenario: insert to a key value node, with the later key contains the former key
    Given a pair with key "AB"
    And a pair with key "ABCD"
    When clear trie tree
    And insert pairs
    Then for each pair, get with key will return the correct value

  Scenario: insert to a key value node, with the former key contains the later key
    Given a pair with key "ABCD"
    And a pair with key "AB"
    When clear trie tree
    And insert pairs
    Then for each pair, get with key will return the correct value

  Scenario: insert to a key value node, keys has common prefix and different postfix
    Given a pair with key "AB"
    And a pair with key "AC"
    When clear trie tree
    And insert pairs
    Then for each pair, get with key will return the correct value

  Scenario: insert to a key value node, keys has no common prefix
    Given a pair with key "A"
    """
    nibbles is [4, 1]
    """
    And a pair with key "Z"
    """
    nibbles is [5, 10]
    """
    When clear trie tree
    And insert pairs
    Then for each pair, get with key will return the correct value
  # ---- end: insert to a key value node---------

  # ---- start: insert to a diverge node---------
  Scenario: insert to a diverge node, with same slot
    Given a pair with key "A"
    """
    nibbles is [4, 1]
    """
    And a pair with key "Z"
    """
    nibbles is [5, 10]
    """
    Given a pair with key "B"
    """
    nibbles is [4, 2]
    """
    When clear trie tree
    And insert pairs
    Then for each pair, get with key will return the correct value

  Scenario: insert to a diverge node, with different slot
    Given a pair with key "A"
    """
    nibbles is [4, 1]
    """
    And a pair with key "Z"
    """
    nibbles is [5, 10]
    """
    Given a pair with key "0"
    """
    nibbles is [3, 0]
    """
    When clear trie tree
    And insert pairs
    Then for each pair, get with key will return the correct value
  # ---- end: insert to a diverge node---------

  @load_data
  Scenario: insert in a more sophisticated case
    Then for each pair, get with key will return the correct value
