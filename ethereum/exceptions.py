class UnknownParentException(Exception):
    pass


class VerificationFailed(Exception):
    pass


class InvalidTransaction(Exception):
    pass


class UnsignedTransactionError(InvalidTransaction):
    pass


class InvalidNonce(InvalidTransaction):
    pass


class InsufficientBalance(InvalidTransaction):
    pass


class InsufficientStartGas(InvalidTransaction):
    pass


class BlockGasLimitReached(InvalidTransaction):
    pass


class GasPriceTooLow(InvalidTransaction):
    pass
