"""Transaction lifecycle for the simulated payment flow."""

from .state_machine import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATES,
    InvalidTransitionError,
    Transaction,
    TransactionError,
    UnauthorizedTransactionError,
)

__all__ = [
    "Transaction",
    "TransactionError",
    "UnauthorizedTransactionError",
    "InvalidTransitionError",
    "ALLOWED_TRANSITIONS",
    "TERMINAL_STATES",
]
