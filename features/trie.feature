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

    # ---- start: insert to a branch node---------
    Examples: insert to a branch node, with same slot
      # nibbles of A: [4,1]
      # nibbles of Z: [5,10]
      # nibbles of B: [4,2]
      | keys            |
      | ["A", "Z", "B"] |

    Examples: insert to a branch node, with different slot
      # nibbles of A: [4,1]
      # nibbles of Z: [5,10]
      # nibbles of 0: [3,0]
      | keys            |
      | ["A", "Z", "0"] |
    # ---- end: insert to a branch node---------

    Examples: insert in a more sophisticated case
      | keys                                                                     |
      | ["AB", "AC", "ABCD", "ACD", "A", "B", "CD", "BCD", "Z", "0", "Z0", "0Z"] |


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
    And get by the key: <key> will return BLANK

    Examples: key not existing
      | key    |
      | "ABDCD" |
      | "X"     |

  Scenario Outline: delete node
    Given pairs with keys: <keys>
    When clear trie tree
    And insert pairs except key: <key>
    And record hash as old hash
    And insert pair with key: <key>
    And delete by the key: <key>
    And record hash as new hash
    Then for keys except <key>, get with key will return the correct value
    And old hash is the same with new hash
    And get by the key: <key> will return BLANK

    Examples: basic
      | key  | keys   |
      | "AB" | ["AB"] |

    Examples: branch node
      | key | keys       |
      | "A" | ["A", "Z"] |

    Examples: key value node
      | key  | keys        |
      | "A"  | ["A", "AB"] |
      | "AB" | ["A", "AB"] |

    Examples:
      | key  | keys             |
      | "AB" | ["A", "B", "AB"] |

    Examples: delete branch and kv node
      | key    | keys                                 |
      | 'dog'  | ['cat', 'ca', 'dog', 'doge', 'test'] |
      | 'test' | ['cat', 'ca',  'doge', 'test']       |

    Examples: sophisticated case
      | key    | keys                                                                    |
      | "AB"   | ["AB", "AC", "ABCD", "ACD", "A", "B", "CD", "BCD", "Z", "0", "Z0", "0Z"]|
      | "AC"   | ["AB", "AC", "ABCD", "ACD", "A", "B", "CD", "BCD", "Z", "0", "Z0", "0Z"]|
      | "ABCD" | ["AB", "AC", "ABCD", "ACD", "A", "B", "CD", "BCD", "Z", "0", "Z0", "0Z"]|
      | "ACD"  | ["AB", "AC", "ABCD", "ACD", "A", "B", "CD", "BCD", "Z", "0", "Z0", "0Z"]|
      | "A"    | ["AB", "AC", "ABCD", "ACD", "A", "B", "CD", "BCD", "Z", "0", "Z0", "0Z"]|
      | "B"    | ["AB", "AC", "ABCD", "ACD", "A", "B", "CD", "BCD", "Z", "0", "Z0", "0Z"]|
      | "CD"   | ["AB", "AC", "ABCD", "ACD", "A", "B", "CD", "BCD", "Z", "0", "Z0", "0Z"]|
      | "BCD"  | ["AB", "AC", "ABCD", "ACD", "A", "B", "CD", "BCD", "Z", "0", "Z0", "0Z"]|
      | "Z"    | ["AB", "AC", "ABCD", "ACD", "A", "B", "CD", "BCD", "Z", "0", "Z0", "0Z"]|
      | "0"    | ["AB", "AC", "ABCD", "ACD", "A", "B", "CD", "BCD", "Z", "0", "Z0", "0Z"]|
      | "Z0"   | ["AB", "AC", "ABCD", "ACD", "A", "B", "CD", "BCD", "Z", "0", "Z0", "0Z"]|
      | "0Z"   | ["AB", "AC", "ABCD", "ACD", "A", "B", "CD", "BCD", "Z", "0", "Z0", "0Z"]|

  Scenario Outline: delete none exist key
    Given pairs with keys: <keys>
    When clear trie tree
    And insert pairs
    And record hash as old hash
    And delete by the key: <key>
    And record hash as new hash
    Then for keys except <key>, get with key will return the correct value
    And old hash is the same with new hash
    And get by the key: <key> will return BLANK

    Examples: key not existing
      | key        | keys                     |
      | "ABDCD"    | []                       |
      | "X"        | []                       |
      | "\x01\xf4" | ["\x03\xe8", "\x03\xe9"] |


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

    Examples: branch node
      # nibbles of A: [4,1]
      # nibbles of Z: [5,10]
      # nibbles of B: [4,2]
      | keys            |
      | ["A", "Z"]      |
      | ["A", "Z", "B"] |
      | ["A", "Z", "0"] |
      | ["AB", "CD"]    |

    Examples: sophisticated case
      | keys                                                             |
      | ["AB", "AC", "ACD", "A", "B", "CD", "BCD", "Z", "0", "Z0", "0Z"] |


  Scenario Outline: convert trie tree to dict
    Given pairs with keys: <keys>
    When clear trie tree
    And insert pairs
    Then to_dict will return the correct dict

    Examples: a blank tree
      | keys |
      | []   |

    Examples: key value node
      | keys           |
      | ["AB", "ABCD"] |

    Examples: branch node
      # nibbles of A: [4,1]
      # nibbles of Z: [5,10]
      # nibbles of B: [4,2]
      | keys            |
      | ["A", "Z"]      |
      | ["A", "Z", "B"] |
      | ["A", "Z", "0"] |
      | ["AB", "CD"]    |

    Examples: sophisticated case
      | keys                                                             |
      | ["AB", "AC", "ACD", "A", "B", "CD", "BCD", "Z", "0", "Z0", "0Z"] |

    Examples: rewriting
      | keys                                 |
      | ["\x03\xe8", "\x03\xe9", "\x03\xe8"] |

  Scenario: conform to fixture
    Given trie fixtures file path
    When load the trie fixtures
    Then for each example, then the hash of the tree root is the expectation
