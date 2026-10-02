"""Transaction lifecycle for the simulated payment flow.

    PROPOSED -> AUTHORIZED -> CHECKOUT -> PAYMENT_PENDING -> COMPLETED
    failure:   PROPOSED -> DENIED
    cancel:    PAYMENT_PENDING -> CANCELLED

Core invariant: only an APPROVE decision may authorize a transaction, and
COMPLETED is reachable only through AUTHORIZED. ASK and DENY can never reach
AUTHORIZED, so an unauthorized purchase can never complete.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models import FirewallDecision, PurchasePlan
from ..types import DecisionStatus, TransactionState

__all__ = [
    "Transaction",
    "TransactionError",
    "UnauthorizedTransactionError",
    "InvalidTransitionError",
    "ALLOWED_TRANSITIONS",
    "TERMINAL_STATES",
]

ALLOWED_TRANSITIONS: dict[TransactionState, frozenset[TransactionState]] = {
    TransactionState.PROPOSED: frozenset(
        {TransactionState.AUTHORIZED, TransactionState.DENIED}
    ),
    TransactionState.AUTHORIZED: frozenset({TransactionState.CHECKOUT}),
    TransactionState.CHECKOUT: frozenset({TransactionState.PAYMENT_PENDING}),
    TransactionState.PAYMENT_PENDING: frozenset(
        {TransactionState.COMPLETED, TransactionState.CANCELLED}
    ),
    TransactionState.COMPLETED: frozenset(),
    TransactionState.DENIED: frozenset(),
    TransactionState.CANCELLED: frozenset(),
}

TERMINAL_STATES = frozenset(
    {
        TransactionState.COMPLETED,
        TransactionState.DENIED,
        TransactionState.CANCELLED,
    }
)


class TransactionError(RuntimeError):
    """Base class for transaction lifecycle errors."""


class UnauthorizedTransactionError(TransactionError):
    """Raised when something other than an APPROVE decision tries to authorize."""


class InvalidTransitionError(TransactionError):
    """Raised on an illegal state transition."""


@dataclass
class Transaction:
    """A simulated purchase transaction with an explicit state machine."""

    transaction_id: str
    plan: PurchasePlan
    state: TransactionState = TransactionState.PROPOSED
    history: list[tuple[TransactionState, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.history.append((self.state, "Transaction proposed."))

    # -- inspection ------------------------------------------------------
    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def can_transition_to(self, target: TransactionState) -> bool:
        return target in ALLOWED_TRANSITIONS[self.state]

    # -- transitions -----------------------------------------------------
    def authorize(self, decision: FirewallDecision) -> None:
        """Move PROPOSED -> AUTHORIZED. Only an APPROVE decision is accepted."""

        if not isinstance(decision, FirewallDecision):
            raise UnauthorizedTransactionError(
                "A transaction can only be authorized by a firewall decision."
            )
        if decision.status is not DecisionStatus.APPROVE or decision.approved_plan is None:
            raise UnauthorizedTransactionError(
                f"Transaction {self.transaction_id} cannot be authorized: the firewall "
                f"returned {decision.status.value}. Only APPROVE may authorize a purchase."
            )
        self._transition(TransactionState.AUTHORIZED, "Firewall decision: APPROVE.")

    def deny(self, reason: str) -> None:
        """Move PROPOSED -> DENIED."""

        self._transition(TransactionState.DENIED, reason)

    def begin_checkout(self) -> None:
        """Move AUTHORIZED -> CHECKOUT (SIMULATED PAYMENT)."""

        self._transition(TransactionState.CHECKOUT, "Simulated checkout started.")

    def begin_payment(self) -> None:
        """Move CHECKOUT -> PAYMENT_PENDING (SIMULATED PAYMENT)."""

        self._transition(TransactionState.PAYMENT_PENDING, "Simulated payment pending.")

    def complete(self) -> None:
        """Move PAYMENT_PENDING -> COMPLETED."""

        self._transition(TransactionState.COMPLETED, "Simulated payment completed.")

    def cancel(self) -> None:
        """Move PAYMENT_PENDING -> CANCELLED."""

        self._transition(TransactionState.CANCELLED, "Simulated payment cancelled.")

    # -- internals -------------------------------------------------------
    def _transition(self, target: TransactionState, note: str) -> None:
        if not self.can_transition_to(target):
            raise InvalidTransitionError(
                f"Illegal transaction transition {self.state.value} -> {target.value} "
                f"for transaction {self.transaction_id}."
            )
        self.state = target
        self.history.append((target, note))
