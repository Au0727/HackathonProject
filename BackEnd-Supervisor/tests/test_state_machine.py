"""Transaction state machine and the core security invariant.

    No unauthorized transaction can become COMPLETED.
"""

from __future__ import annotations

import unittest

from firewall import (
    AuthorizationEngine,
    DecisionStatus,
    InvalidTransitionError,
    Transaction,
    TransactionState,
    UnauthorizedTransactionError,
)
from firewall.authorization_engine import FirewallRequest, FinancialFirewall

from tests.factories import context, plan


def _decision(plans=None, **kwargs):
    firewall = FinancialFirewall(AuthorizationEngine())
    return firewall.evaluate_purchase_plans(
        FirewallRequest(
            plans=plans if plans is not None else (plan(1, total="100.00"),),
            context=context(**kwargs),
        )
    )


class HappyPathTest(unittest.TestCase):
    def test_full_lifecycle(self) -> None:
        decision = _decision()
        self.assertIs(decision.status, DecisionStatus.APPROVE)
        transaction = Transaction("TXN-1", decision.approved_plan)
        transaction.authorize(decision)
        transaction.begin_checkout()
        transaction.begin_payment()
        transaction.complete()
        self.assertIs(transaction.state, TransactionState.COMPLETED)
        self.assertTrue(transaction.is_terminal)
        self.assertEqual(
            [state for state, _ in transaction.history],
            [
                TransactionState.PROPOSED,
                TransactionState.AUTHORIZED,
                TransactionState.CHECKOUT,
                TransactionState.PAYMENT_PENDING,
                TransactionState.COMPLETED,
            ],
        )

    def test_cancelled_payment(self) -> None:
        decision = _decision()
        transaction = Transaction("TXN-2", decision.approved_plan)
        transaction.authorize(decision)
        transaction.begin_checkout()
        transaction.begin_payment()
        transaction.cancel()
        self.assertIs(transaction.state, TransactionState.CANCELLED)

    def test_proposed_can_be_denied(self) -> None:
        decision = _decision(plans=(plan(1, total="500.00"),))
        transaction = Transaction("TXN-3", decision.plan_results and plan(1, total="500.00"))
        transaction.deny(decision.reason)
        self.assertIs(transaction.state, TransactionState.DENIED)


class InvariantTest(unittest.TestCase):
    def test_denied_purchase_cannot_be_authorized(self) -> None:
        decision = _decision(plans=(plan(1, total="500.00"),))
        self.assertIs(decision.status, DecisionStatus.DENY)
        transaction = Transaction("TXN-4", plan(1, total="500.00"))
        with self.assertRaises(UnauthorizedTransactionError):
            transaction.authorize(decision)
        self.assertIs(transaction.state, TransactionState.PROPOSED)

    def test_ask_purchase_cannot_be_authorized(self) -> None:
        decision = _decision(plans=(plan(1, total="250.00"),))
        self.assertIs(decision.status, DecisionStatus.ASK)
        transaction = Transaction("TXN-5", plan(1, total="250.00"))
        with self.assertRaises(UnauthorizedTransactionError):
            transaction.authorize(decision)
        self.assertIs(transaction.state, TransactionState.PROPOSED)

    def test_completed_is_unreachable_without_authorization(self) -> None:
        transaction = Transaction("TXN-6", plan(1, total="100.00"))
        with self.assertRaises(InvalidTransitionError):
            transaction.complete()
        with self.assertRaises(InvalidTransitionError):
            transaction.begin_checkout()
        with self.assertRaises(InvalidTransitionError):
            transaction.begin_payment()
        self.assertIs(transaction.state, TransactionState.PROPOSED)

    def test_checkout_cannot_be_reached_from_authorized_only_partially(self) -> None:
        decision = _decision()
        transaction = Transaction("TXN-7", decision.approved_plan)
        transaction.authorize(decision)
        with self.assertRaises(InvalidTransitionError):
            transaction.complete()
        self.assertIs(transaction.state, TransactionState.AUTHORIZED)

    def test_terminal_states_accept_no_further_transitions(self) -> None:
        decision = _decision()
        transaction = Transaction("TXN-8", decision.approved_plan)
        transaction.authorize(decision)
        transaction.begin_checkout()
        transaction.begin_payment()
        transaction.complete()
        for action in (
            transaction.begin_checkout,
            transaction.begin_payment,
            transaction.complete,
            transaction.cancel,
        ):
            with self.subTest(action=action.__name__):
                with self.assertRaises(InvalidTransitionError):
                    action()

    def test_authorize_requires_a_firewall_decision(self) -> None:
        transaction = Transaction("TXN-9", plan(1, total="100.00"))
        with self.assertRaises(UnauthorizedTransactionError):
            transaction.authorize("approve")  # type: ignore[arg-type]


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
