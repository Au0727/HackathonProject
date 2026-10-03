"""Determinism: identical input always produces an identical policy decision."""

from __future__ import annotations

import unittest
from decimal import Decimal

from firewall import AuthorizationEngine, calculate_merchant_rating
from firewall.authorization_engine import FirewallRequest, FinancialFirewall

from tests.factories import DECLINE, auth, context, plan, responses


def _fingerprint(decision) -> tuple:
    """The policy-relevant content of a decision (timestamps excluded)."""

    payload = decision.to_dict()
    payload.pop("askId", None)
    return (
        payload.get("status"),
        tuple(payload.get("failedRules", ())),
        tuple(payload.get("askReasons", ())),
        payload.get("reason"),
        payload.get("evaluatedPlanRank"),
        None if payload.get("merchantRisk") is None else payload["merchantRisk"]["merchantRating"],
    )


def _scenario(provider=None):
    plans = (
        plan(1, total="400.00"),
        plan(2, total="250.00", merchant_id="merchant-002", credit=55, feedback=50),
        plan(3, total="150.00", merchant_id="merchant-003"),
    )
    firewall = FinancialFirewall(AuthorizationEngine())
    return firewall.evaluate_purchase_plans(
        FirewallRequest(
            plans=plans,
            context=context(daily_spent="100.00", provider=None),
            confirmation_provider=provider,
        )
    )


class DeterminismTest(unittest.TestCase):
    def test_same_input_produces_the_same_decision_100_times(self) -> None:
        first = _fingerprint(_scenario())
        for run in range(100):
            with self.subTest(run=run):
                self.assertEqual(_fingerprint(_scenario()), first)

    def test_ask_resolution_is_deterministic(self) -> None:
        provider = responses({1: DECLINE}, default=DECLINE)
        fingerprints = {
            _fingerprint(
                FinancialFirewall(AuthorizationEngine()).evaluate_purchase_plans(
                    FirewallRequest(
                        plans=(plan(1, total="250.00"),),
                        context=context(),
                        confirmation_provider=provider,
                    )
                )
            )
            for _ in range(50)
        }
        self.assertEqual(len(fingerprints), 1)

    def test_merchant_rating_is_deterministic(self) -> None:
        ratings = {calculate_merchant_rating(82, 71) for _ in range(50)}
        self.assertEqual(ratings, {Decimal("77.60")})

    def test_audit_sequence_is_deterministic_apart_from_timestamps(self) -> None:
        engine = AuthorizationEngine()
        firewall = FinancialFirewall(engine)
        request = FirewallRequest(
            plans=(plan(1, total="400.00"), plan(2, total="150.00")),
            context=context(),
        )
        firewall.evaluate_purchase_plans(request)
        first = [(event.id, event.decision.value, event.failed_rules) for event in engine.audit_service.events]

        engine2 = AuthorizationEngine()
        FinancialFirewall(engine2).evaluate_purchase_plans(request)
        second = [(event.id, event.decision.value, event.failed_rules) for event in engine2.audit_service.events]
        self.assertEqual(first, second)

    def test_suspended_ask_ids_are_deterministic(self) -> None:
        ids = set()
        for _ in range(10):
            firewall = FinancialFirewall(AuthorizationEngine())
            decision = firewall.evaluate_purchase_plans(
                FirewallRequest(plans=(plan(1, total="250.00"),), context=context())
            )
            ids.add(decision.ask_id)
        self.assertEqual(ids, {"ask-0001"})

    def test_authorization_logic_does_not_use_randomness(self) -> None:
        import random

        state = random.getstate()
        try:
            random.seed(1)
            first = _fingerprint(_scenario())
            random.seed(2)
            second = _fingerprint(_scenario())
        finally:
            random.setstate(state)
        self.assertEqual(first, second)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
