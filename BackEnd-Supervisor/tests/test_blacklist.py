"""Blacklist behaviour: hard denial, exact matching, blacklisting during an ASK."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from firewall import (
    AuthorizationEngine,
    BlacklistError,
    BlacklistStore,
    DecisionStatus,
    RuleCode,
)
from firewall.authorization_engine import FirewallRequest, FinancialFirewall

from tests.factories import CONFIRM, CONFIRM_AND_BLACKLIST, context, plan, summary


def _firewall(store: BlacklistStore | None = None):
    engine = AuthorizationEngine(blacklist_store=store)
    return FinancialFirewall(engine), engine


class BlacklistRuleTest(unittest.TestCase):
    def test_not_blacklisted_continues(self) -> None:
        firewall, _ = _firewall(BlacklistStore(["merchant-999"]))
        decision = firewall.evaluate_purchase_plans(
            FirewallRequest(plans=(plan(1, total="100.00"),), context=context())
        )
        self.assertIs(decision.status, DecisionStatus.APPROVE)

    def test_blacklisted_merchant_is_denied(self) -> None:
        firewall, _ = _firewall(BlacklistStore(["merchant-001"]))
        decision = firewall.evaluate_purchase_plans(
            FirewallRequest(plans=(plan(1, total="100.00"),), context=context())
        )
        self.assertIs(decision.status, DecisionStatus.DENY)
        self.assertIn(RuleCode.MERCHANT_BLACKLISTED, decision.failed_rules)
        self.assertEqual(summary(decision).reason, "This merchant is on your blacklist.")

    def test_blacklist_from_context_also_denies(self) -> None:
        firewall, _ = _firewall()
        decision = firewall.evaluate_purchase_plans(
            FirewallRequest(
                plans=(plan(1, total="100.00"),),
                context=context(blacklist=["merchant-001"]),
            )
        )
        self.assertIs(decision.status, DecisionStatus.DENY)

    def test_matching_is_exact_not_fuzzy(self) -> None:
        for entry in ("MERCHANT-001", "merchant-001 ", "merchant-1", "merchant-0011"):
            with self.subTest(entry=entry):
                firewall, _ = _firewall(BlacklistStore([entry]))
                decision = firewall.evaluate_purchase_plans(
                    FirewallRequest(plans=(plan(1, total="100.00"),), context=context())
                )
                self.assertIs(decision.status, DecisionStatus.APPROVE)

    def test_blacklist_is_a_hard_denial_even_with_low_rating(self) -> None:
        firewall, _ = _firewall(BlacklistStore(["merchant-001"]))
        decision = firewall.evaluate_purchase_plans(
            FirewallRequest(
                plans=(plan(1, total="250.00", credit=40, feedback=30),),
                context=context(),
            )
        )
        self.assertIs(decision.status, DecisionStatus.DENY)

    def test_blacklist_beats_low_rating_and_threshold(self) -> None:
        firewall, _ = _firewall(BlacklistStore(["merchant-001"]))
        decision = firewall.evaluate_purchase_plans(
            FirewallRequest(
                plans=(plan(1, total="100.00", credit=40, feedback=30),),
                context=context(),
            )
        )
        self.assertIs(decision.status, DecisionStatus.DENY)
        self.assertEqual(decision.failed_rules, (RuleCode.MERCHANT_BLACKLISTED,))


class BlacklistDuringAskTest(unittest.TestCase):
    def test_continue_and_blacklist_approves_now_and_denies_later(self) -> None:
        store = BlacklistStore()
        firewall, engine = _firewall(store)
        risky_plan = plan(1, total="250.00", credit=55, feedback=50)
        decision = firewall.evaluate_purchase_plans(
            FirewallRequest(
                plans=(risky_plan,),
                context=context(),
                confirmation_provider=lambda evaluation: CONFIRM_AND_BLACKLIST,
            )
        )
        # The current purchase was explicitly approved by the user.
        self.assertIs(decision.status, DecisionStatus.APPROVE)
        self.assertEqual(decision.approved_plan.merchant_id, "merchant-001")
        # ... but the merchant is now blacklisted for future plans.
        self.assertEqual(store.merchants, ("merchant-001",))
        follow_up = firewall.evaluate_purchase_plans(
            FirewallRequest(plans=(risky_plan,), context=context())
        )
        self.assertIs(follow_up.status, DecisionStatus.DENY)
        self.assertIn(RuleCode.MERCHANT_BLACKLISTED, follow_up.failed_rules)

    def test_blacklist_action_is_audited(self) -> None:
        store = BlacklistStore()
        firewall, engine = _firewall(store)
        firewall.evaluate_purchase_plans(
            FirewallRequest(
                plans=(plan(1, total="250.00", credit=55, feedback=50),),
                context=context(),
                confirmation_provider=lambda evaluation: CONFIRM_AND_BLACKLIST,
            )
        )
        blacklist_events = [
            event
            for event in engine.audit_service.events
            if event.event_type == "BLACKLIST_ACTION"
        ]
        self.assertEqual(len(blacklist_events), 1)
        self.assertTrue(blacklist_events[0].merchant_blacklisted)
        self.assertEqual(blacklist_events[0].merchant_id, "merchant-001")

    def test_continue_without_blacklist_leaves_the_store_empty(self) -> None:
        store = BlacklistStore()
        firewall, _ = _firewall(store)
        decision = firewall.evaluate_purchase_plans(
            FirewallRequest(
                plans=(plan(1, total="250.00", credit=55, feedback=50),),
                context=context(),
                confirmation_provider=lambda evaluation: CONFIRM,
            )
        )
        self.assertIs(decision.status, DecisionStatus.APPROVE)
        self.assertEqual(store.merchants, ())


class BlacklistStoreTest(unittest.TestCase):
    def test_persistence_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "blacklist.json"
            store = BlacklistStore(path=path)
            self.assertTrue(store.add("merchant-123"))
            self.assertFalse(store.add("merchant-123"))
            reloaded = BlacklistStore(path=path)
            self.assertEqual(reloaded.merchants, ("merchant-123",))
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["blacklistedMerchants"], ["merchant-123"])

    def test_malformed_blacklist_fails_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "blacklist.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(BlacklistError):
                BlacklistStore(path=path)
            path.write_text('{"blacklistedMerchants": "merchant-001"}', encoding="utf-8")
            with self.assertRaises(BlacklistError):
                BlacklistStore(path=path)

    def test_empty_or_non_string_entries_are_rejected(self) -> None:
        with self.assertRaises(BlacklistError):
            BlacklistStore([""])
        with self.assertRaises(BlacklistError):
            BlacklistStore([None])  # type: ignore[list-item]

    def test_merchants_are_sorted(self) -> None:
        store = BlacklistStore(["merchant-b", "merchant-a"])
        self.assertEqual(store.merchants, ("merchant-a", "merchant-b"))
        self.assertTrue(store.contains("merchant-a"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
