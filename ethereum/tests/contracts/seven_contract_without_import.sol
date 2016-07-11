library SevenLibrary {
    function seven() returns (int256 y);
}

contract SevenContract {
    function test() returns (int256 seven) {
        seven = SevenLibrary.seven();
    }
}

