Feature: Pack/unpack nibbles to/from binary, with optional nibbles terminator


  Scenario Outline: Even numbers of nibbles, without terminator
    Given nibbles: <nibbles>
    When packed to binary
    Then in the binary, the first nibbles should be 0x0
    And the second nibbles should be 0x0
    And nibbles after should equal to the original nibbles
    And unpack the binary will get the original nibbles

    Examples: even numbers of nibbles
      | nibbles              |
      | []                   |
      | [0x0, 0x1]           |
      | [0x1, 0x2, 0x3, 0x4] |


  Scenario Outline: Even numbers of nibbles, with terminator
    Given nibbles: <nibbles>
    When append a terminator
    And packed to binary
    Then in the binary, the first nibbles should be 0x2
    And the second nibbles should be 0x0
    And nibbles after should equal to the original nibbles
    And unpack the binary will get the original nibbles

    Examples: even numbers of nibbles
      | nibbles              |
      | []                   |
      | [0x0, 0x1]           |
      | [0x1, 0x2, 0x3, 0x4] |


  Scenario Outline: Odd numbers of nibbles, with terminator
    Given nibbles: <nibbles>
    When append a terminator
    And packed to binary
    Then in the binary, the first nibbles should be 0x3
    And nibbles after should equal to the original nibbles
    And unpack the binary will get the original nibbles

    Examples: even numbers of nibbles
      | nibbles         |
      | [0x0]           |
      | [0x1, 0x2, 0x3] |


  Scenario Outline: Odd numbers of nibbles, without terminator
    Given nibbles: <nibbles>
    When packed to binary
    Then in the binary, the first nibbles should be 0x1
    And nibbles after should equal to the original nibbles
    And unpack the binary will get the original nibbles

    Examples: even numbers of nibbles
      | nibbles         |
      | [0x0]           |
      | [0x1, 0x2, 0x3] |

  Scenario Outline: conform to fixture
    Given to be packed nibbles: <seq> and terminator: <term>
    When packed to binary
    Then the packed result will be <out>

    Examples: zz,odd,term
      | out        | seq                   | term   |
      | "30012345" | [0, 0, 1, 2, 3, 4, 5] | True   |

    Examples: nz,odd,open
      | out      | seq             | term   |
      | "112345" | [1, 2, 3, 4, 5] | False  |

    Examples: zz,even,open
      | out        | seq                | term   |
      | "00001234" | [0, 0, 1, 2, 3, 4] | False  |

    Examples: z,odd,term
      | out      | seq             | term   |
      | "301234" | [0, 1, 2, 3, 4] | True   |

    Examples: zz,odd,open
      | out        | seq                   | term   |
      | "10012345" | [0, 0, 1, 2, 3, 4, 5] | False  |

    Examples: nz,even,open
      | out      | seq          | term   |
      | "001234" | [1, 2, 3, 4] | False  |

    Examples: nz,odd,term
      | out      | seq             | term   |
      | "312345" | [1, 2, 3, 4, 5] | True   |

    Examples: nz,even,term
      | out      | seq          | term   |
      | "201234" | [1, 2, 3, 4] | True   |

    Examples: z,odd,open
      | out      | seq             | term   |
      | "101234" | [0, 1, 2, 3, 4] | False  |

    Examples: zz,even,term
      | out        | seq                | term   |
      | "20001234" | [0, 0, 1, 2, 3, 4] | True   |

    Examples: z,even,term
      | out        | seq                | term   |
      | "20012345" | [0, 1, 2, 3, 4, 5] | True   |

    Examples: z,even,open
      | out        | seq                | term   |
      | "00012345" | [0, 1, 2, 3, 4, 5] | False  |

