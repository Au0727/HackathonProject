"""The three financial rules: transaction limit, daily limit, confirmation threshold."""

from __future__ import annotations

import unittest

from firewall import AuthorizationEngine, DecisionStatus, RuleCode
from firewall.authorization_engine import FirewallRequest, FinancialFirewall

from tests.factories import auth, context, plan, summary


class MaxPerTransactionTest(unittest.TestCase):
    """Confirmation threshold is pinned at the limit so only this rule can fire."""

    def setUp(self) -> None:
        self.firewall = FinancialFirewall(AuthorizationEngine())
        self.context = context(authorization=auth("300.00", "1000.00", "300.00"))

    def decision(self, **plan_kwargs):
        return self.firewall.evaluate_purchase_plans(
            FirewallRequest(plans=(plan(1, **plan_kwargs),), context=self.context)
        )

    def test_exactly_at_limit_passes(self) -> None:
        decision = self.decision(total="300.00")
        self.assertIs(decision.status, DecisionStatus.APPROVE)

    def test_one_cent_above_limit_is_denied(self) -> None:
        decision = self.decision(total="300.01")
        self.assertIs(decision.status, DecisionStatus.DENY)
        self.assertIn(RuleCode.MAX_PER_TRANSACTION, decision.failed_rules)
        self.assertIn("Final transaction total HKD 300.01 exceeds", summary(decision).reason)

    def test_shipping_pushes_plan_over_limit(self) -> None:
        # 280 + 30 = 310 > 300 even though the subtotal alone would pass.
        decision = self.decision(total="310.00", shipping="30.00")
        self.assertIs(decision.status, DecisionStatus.DENY)
        self.assertIn("HKD 310.00", summary(decision).reason)
        self.assertIn(RuleCode.MAX_PER_TRANSACTION, summary(decision).failed_rules)

    def test_tax_pushes_plan_over_limit(self) -> None:
        decision = self.decision(total="305.00", tax="5.00")
        self.assertIs(decision.status, DecisionStatus.DENY)
        self.assertIn(RuleCode.MAX_PER_TRANSACTION, decision.failed_rules)

    def test_subtotal_alone_is_not_the_transaction_total(self) -> None:
        # subtotal 290 + shipping 20 = 310: only the final total counts.
        decision = self.decision(subtotal="290.00", shipping="20.00", total="310.00")
        self.assertIs(decision.status, DecisionStatus.DENY)


class MaxDailySpendTest(unittest.TestCase):
    def setUp(self) -> None:
        self.firewall = FinancialFirewall(AuthorizationEngine())
        self.context = context(
            authorization=auth("300.00", "1000.00", "300.00"), daily_spent="700.00"
        )

    def decision(self, **plan_kwargs):
        return self.firewall.evaluate_purchase_plans(
            FirewallRequest(plans=(plan(1, **plan_kwargs),), context=self.context)
        )

    def test_exactly_at_daily_limit_passes(self) -> None:
        decision = self.decision(total="300.00")
        self.assertIs(decision.status, DecisionStatus.APPROVE)

    def test_one_cent_above_daily_limit_is_denied(self) -> None:
        decision = self.firewall.evaluate_purchase_plans(
            FirewallRequest(
                plans=(plan(1, total="300.00"),),
                context=context(
                    authorization=self.context.authorization, daily_spent="700.01"
                ),
            )
        )
        self.assertIs(decision.status, DecisionStatus.DENY)
        self.assertIn(RuleCode.MAX_DAILY_SPEND, decision.failed_rules)
        self.assertIn("HKD 1000.01", summary(decision).reason)

    def test_spec_example_denied(self) -> None:
        decision = self.firewall.evaluate_purchase_plans(
            FirewallRequest(
                plans=(plan(1, total="250.00"),),
                context=context(
                    authorization=auth("300.00", "1000.00", "300.00"), daily_spent="800.00"
                ),
            )
        )
        self.assertIs(decision.status, DecisionStatus.DENY)
        self.assertIn(
            "This purchase would increase today's spending to HKD 1050.00",
            summary(decision).reason,
        )

    def test_ask_is_not_counted_as_committed_spending(self) -> None:
        # Plan 1 needs confirmation (ASK). If that ASK were counted as spending,
        # the next decision would exceed the daily limit.
        authorization = auth("300.00", "1000.00", "200.00")
        firewall = FinancialFirewall(AuthorizationEngine())
        first = firewall.evaluate_purchase_plans(
            FirewallRequest(
                plans=(plan(1, total="250.00"),),
                context=context(authorization=authorization, daily_spent="700.00"),
            )
        )
        self.assertIs(first.status, DecisionStatus.ASK)
        second = firewall.evaluate_purchase_plans(
            FirewallRequest(
                plans=(plan(1, total="50.00"),),
                context=context(authorization=authorization, daily_spent="950.00"),
            )
        )
        self.assertIs(second.status, DecisionStatus.APPROVE)


class ConfirmationThresholdTest(unittest.TestCase):
    def setUp(self) -> None:
        self.firewall = FinancialFirewall(AuthorizationEngine())
        self.context = context()

    def decision(self, **plan_kwargs):
        return self.firewall.evaluate_purchase_plans(
            FirewallRequest(plans=(plan(1, **plan_kwargs),), context=self.context)
        )

    def test_exactly_at_threshold_needs_no_confirmation(self) -> None:
        decision = self.decision(total="200.00")
        self.assertIs(decision.status, DecisionStatus.APPROVE)

    def test_one_cent_above_threshold_asks(self) -> None:
        decision = self.decision(total="200.01")
        self.assertIs(decision.status, DecisionStatus.ASK)
        self.assertIn("exceeds your confirmation threshold of HKD 200.00", decision.reason)
        self.assertEqual(
            [reason.value for reason in decision.ask_reasons],
            ["CONFIRMATION_THRESHOLD_EXCEEDED"],
        )
        self.assertFalse(decision.allow_blacklist_option)

    def test_zero_threshold_asks_for_any_purchase(self) -> None:
        decision = self.firewall.evaluate_purchase_plans(
            FirewallRequest(
                plans=(plan(1, total="10.00"),),
                context=context(authorization=auth("300", "1000", "0")),
            )
        )
        self.assertIs(decision.status, DecisionStatus.ASK)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
