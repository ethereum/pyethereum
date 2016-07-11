import "seven_library.sol";

contract SevenContract {
    function test() returns (int256 seven) {
        seven = SevenLibrary.seven();
    }
}
