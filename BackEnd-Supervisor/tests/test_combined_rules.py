"""Combined rules: multiple ASK reasons, and hard denial overriding ASK."""

from __future__ import annotations

import unittest

from firewall import AuthorizationEngine, DecisionStatus, RuleCode
from firewall.authorization_engine import FirewallRequest, FinancialFirewall

from tests.factories import context, plan, summary


class CombinedAskTest(unittest.TestCase):
    def setUp(self) -> None:
        self.firewall = FinancialFirewall(AuthorizationEngine())

    def test_low_rating_and_threshold_produce_one_combined_ask(self) -> None:
        decision = self.firewall.evaluate_purchase_plans(
            FirewallRequest(
                plans=(plan(1, total="250.00", credit=55, feedback=50),),
                context=context(),
            )
        )
        self.assertIs(decision.status, DecisionStatus.ASK)
        self.assertEqual(
            [reason.value for reason in decision.ask_reasons],
            ["MERCHANT_RATING_LOW", "CONFIRMATION_THRESHOLD_EXCEEDED"],
        )
        self.assertTrue(decision.allow_blacklist_option)
        self.assertIn("Merchant Safety Rating", decision.reason)
        self.assertIn("confirmation threshold", decision.reason)

    def test_ask_reasons_are_deterministically_ordered(self) -> None:
        for _ in range(5):
            decision = self.firewall.evaluate_purchase_plans(
                FirewallRequest(
                    plans=(plan(1, total="250.00", credit=55, feedback=50),),
                    context=context(),
                )
            )
            self.assertEqual(
                [reason.value for reason in decision.ask_reasons],
                ["MERCHANT_RATING_LOW", "CONFIRMATION_THRESHOLD_EXCEEDED"],
            )


class HardDenyPrecedenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.firewall = FinancialFirewall(AuthorizationEngine())
        self.context = context()

    def evaluate(self, **plan_kwargs):
        return self.firewall.evaluate_purchase_plans(
            FirewallRequest(plans=(plan(1, **plan_kwargs),), context=self.context)
        )

    def test_transaction_over_limit_with_low_rating_is_denied_not_asked(self) -> None:
        decision = self.evaluate(total="500.00", credit=30, feedback=20)
        self.assertIs(decision.status, DecisionStatus.DENY)
        self.assertIn(RuleCode.MAX_PER_TRANSACTION, decision.failed_rules)
        self.assertNotIn(RuleCode.MERCHANT_RATING_LOW, decision.failed_rules)

    def test_daily_limit_with_low_rating_is_denied_not_asked(self) -> None:
        decision = self.firewall.evaluate_purchase_plans(
            FirewallRequest(
                plans=(plan(1, total="250.00", credit=30, feedback=20),),
                context=context(daily_spent="900.00"),
            )
        )
        self.assertIs(decision.status, DecisionStatus.DENY)
        self.assertIn(RuleCode.MAX_DAILY_SPEND, decision.failed_rules)

    def test_missing_risk_data_beats_the_confirmation_threshold(self) -> None:
        decision = self.evaluate(
            total="250.00", credit=None, feedback=None
        )
        self.assertIs(decision.status, DecisionStatus.DENY)
        self.assertIn(RuleCode.MERCHANT_RISK_DATA_UNAVAILABLE, decision.failed_rules)

    def test_invalid_plan_data_beats_everything_else(self) -> None:
        decision = self.evaluate(
            subtotal="10.00", total="99.00", credit=30, feedback=20
        )
        self.assertIs(decision.status, DecisionStatus.DENY)
        self.assertEqual(decision.failed_rules, (RuleCode.INVALID_PLAN_DATA,))
        self.assertIn("does not match subtotal + shipping + tax", summary(decision).reason)

    def test_all_rules_pass_produces_approve(self) -> None:
        decision = self.evaluate(total="150.00")
        self.assertIs(decision.status, DecisionStatus.APPROVE)
        self.assertEqual(decision.failed_rules, ())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
