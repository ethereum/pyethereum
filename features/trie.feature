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

  @load_data
  Scenario: insert in a more sophisticated case
    Then for each pair, get with key will return the correct value


  @load_data
  Scenario Outline: update existing node
    # keys already in loaded data
    Given pairs with keys: <keys>
    When insert pairs
    Then for each pair, get with key will return the correct value

    Examples:
      | keys     |
      | ["AB"]   |
      | ["AC"]   |
      | ["ABCD"] |
      | ["ACD"]  |
      | ["A"]    |
      | ["B"]    |
      | ["CD"]   |
      | ["BCD"]  |
      | ["Z"]    |
      | ["0"]    |
      | ["Z0"]   |
      | ["0Z"]   |

  @load_data
  Scenario Outline: reading with a key not existing
    # a key not existing in loaded data
    Given a key: <key>
    Then get by the key will return None

    Examples:
      | key    |
      | "ABDCD" |
      | "X"     |

  @load_data
  Scenario Outline: delete existing node by key
    # keys already in loaded data
    Given a key: <key>
    When delete by the key
    Then get by the key will return None

    Examples:
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

  @load_data
  Scenario Outline: delete node by a key not existing
    # a key not existing in loaded data
    Given a key: <key>
    When delete by the key
    Then get by the key will return None

    Examples:
      | key     |
      | "ABDCD" |
      | "X"     |
