@trie
Feature: trie tree manipulate

  # here (key, value) is called pair

  Scenario: clear trie tree
    When clear trie tree
    Then root will be blank

  Scenario Outline: insert (key, node) pairs to a trie tree
    Given pairs with keys: <keys>
    When clear trie tree
    And insert pairs
    Then for each pair, get with key will return the correct value

    Examples: insert to a blank tree
      | keys   |
      | ["AB"] |

    # ---- start: insert to a key value node---------
    Examples: insert to a key value node, with the later key contains the former key
      | keys           |
      | ["AB", "ABCD"] |

    Examples: insert to a key value node, with the former key contains the later key
      | keys           |
      | ["ABCD", "AB"] |

    Examples: insert to a key value node, keys has common prefix and different postfix
      | keys         |
      | ["AB", "CD"] |

    Examples: insert to a key value node, keys has no common prefix
      # nibbles of A: [4,1]
      # nibbles of Z: [5,10]
      | keys       |
      | ["A", "Z"] |
    # ---- end: insert to a key value node---------

    # ---- start: insert to a diverge node---------
    Examples: insert to a diverge node, with same slot
      # nibbles of A: [4,1]
      # nibbles of Z: [5,10]
      # nibbles of B: [4,2]
      | keys            |
      | ["A", "Z", "B"] |

    Examples: insert to a diverge node, with different slot
      # nibbles of A: [4,1]
      # nibbles of Z: [5,10]
      # nibbles of 0: [3,0]
      | keys            |
      | ["A", "Z", "0"] |
    # ---- end: insert to a diverge node---------


  Scenario: insert in a more sophisticated case
    Given pairs with keys: ["AB", "AC", "ABCD", "ACD", "A", "B", "CD", "BCD", "Z", "0", "Z0", "0Z"]
    When clear trie tree
    And insert pairs
    Then for each pair, get with key will return the correct value


  Scenario Outline: update existing node
    Given pairs with keys: ["AB", "AC", "ABCD", "ACD", "A", "B", "CD", "BCD", "Z", "0", "Z0", "0Z"]
    When clear trie tree
    And insert pairs
    And update by the key: <key>
    Then for each pair, get with key will return the correct value

    Examples:
      | key     |
      | "AB"   |
      | "AC"   |
      | "ABCD" |
      | "ACD"  |
      | "A"    |
      | "B"    |
      | "CD"   |
      | "BCD"  |
      | "Z"    |
      | "0"    |
      | "Z0"   |
      | "0Z"   |


  Scenario Outline: reading with a key not existing
    Given pairs with keys: ["AB", "AC", "ABCD", "ACD", "A", "B", "CD", "BCD", "Z", "0", "Z0", "0Z"]
    When clear trie tree
    And insert pairs
    Then for each pair, get with key will return the correct value
    And get by the key: <key> will return None

    Examples: key not existing
      | key    |
      | "ABDCD" |
      | "X"     |


  Scenario Outline: delete node
    Given pairs with keys: ["AB", "AC", "ABCD", "ACD", "A", "B", "CD", "BCD", "Z", "0", "Z0", "0Z"]
    When clear trie tree
    And insert pairs
    And delete by the key: <key>
    Then for each pair, get with key will return the correct value
    And get by the key: <key> will return None

    Examples: existing key
      | key    |
      | "AB"   |
      | "AC"   |
      | "ABCD" |
      | "ACD"  |
      | "A"    |
      | "B"    |
      | "CD"   |
      | "BCD"  |
      | "Z"    |
      | "0"    |
      | "Z0"   |
      | "0Z"   |

    Examples: key not existing
      | key     |
      | "ABDCD" |
      | "X"     |


  Scenario Outline: get node size
    Given pairs with keys: <keys>
    When clear trie tree
    And insert pairs
    Then get size will return the correct number

    Examples: a blank tree
      | keys |
      | []   |

    Examples: key value node
      | keys           |
      | ["AB", "ABCD"] |

    Examples: diverge node
      # nibbles of A: [4,1]
      # nibbles of Z: [5,10]
      # nibbles of B: [4,2]
      | keys            |
      | ["AB", "CD"]    |
      | ["A", "Z"]      |
      | ["A", "Z", "B"] |
      | ["A", "Z", "0"] |

    Examples: sophisticated case
      | keys                                                             |
      | ["AB", "AC", "ACD", "A", "B", "CD", "BCD", "Z", "0", "Z0", "0Z"] |

