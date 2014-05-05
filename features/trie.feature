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
    And get by the key: <key> will return None

    Examples: key not existing
      | key    |
      | "ABDCD" |
      | "X"     |


  Scenario Outline: delete node
    Given pairs with keys: <keys>
    When clear trie tree
    And insert pairs
    And delete by the key: <key>
    Then for each pair, get with key will return the correct value
    And get by the key: <key> will return None
    And tree has no change if key does not exist

    Examples: basic
      | key  | keys   |
      | "AB" | ["AB"] |

    Examples: diverge node
      | key | keys       |
      | "A" | ["A", "B"] |

    Examples: key value node
      | key  | keys        |
      | "A"  | ["A", "AB"] |
      | "AB" | ["A", "AB"] |

    Examples:
      | key  | keys             |
      | "AB" | ["A", "B", "AB"] |

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

    Examples: diverge node
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

    Examples: diverge node
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


  Scenario Outline: conform to fixture
    Given input dictionary: <in>
    When clear trie tree
    And build trie tree from the input
    Then the hash of the tree root is <root>

    Examples: basic
      | in                       | root                                                               |
      | {u'a': u'A', u'b': u'B'} | "300eab197a9d9e437aaeb9b0d7bd77d57e8d4e3eeca0b1e6a3fe28a84e2cd70c" |

    Examples: basic1
      | in                 | root                                                               |
      | {u'test': u'test'} | "85d106d4edff3b7a4889e91251d0a87d7c17a1dda648ebdba8c6060825be23b8" |

    Examples: basic2
      | in                                  | root                                                               |
      | {u'test': u'test', u'te': u'testy'} | "8452568af70d8d140f58d941338542f645fcca50094b20f3c3d8c3df49337928" |

    Examples: doprefix
      | in                                                               | root                                                               |
      | {u'dogglesworth': u'cat', u'dog': u'puppy', u'doe': u'reindeer'} | "8aad789dff2f538bca5d8ea56e8abe10f4c7ba3a5dea95fea4cd6e7c3a1168d3" |

    Examples: beprefix
      | in                                            | root                                                               |
      | {u'be': u'e', u'dog': u'puppy', u'bed': u'd'} | "3f67c7a47520f79faa29255d2d3c084a7a6df0453116ed7232ff10277a8be68b" |

    Examples: multiprefix
      | in                                                                          | root                                                               |
      | {u'do': u'verb', u'horse': u'stallion', u'doge': u'coin', u'dog': u'puppy'} | "5991bb8c6514148a29db676a14ac506cd2cd5775ace63c30a4fe457715e9ac84" |

    Examples: replacement
      | in                                                                          | root                                                               |
      | [['foo', 'bar'], ['food', 'bat'], ['food', 'bass']]                         | "17beaa1648bafa633cda809c90c04af50fc8aed3cb40d16efbddee6fdf63c4c3" |

