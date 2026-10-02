"""Deterministic merchant safety rating and the merchant-risk rule."""

from __future__ import annotations

import unittest
from decimal import Decimal

from firewall import (
    AuthorizationEngine,
    DecisionStatus,
    RiskLevel,
    RuleCode,
    calculate_merchant_rating,
    risk_level_for,
)
from firewall.authorization_engine import FirewallRequest, FinancialFirewall
from firewall.rules import evaluate_merchant_risk, resolve_merchant_risk

from tests.factories import StaticRiskProvider, auth, context, plan, risk


class RatingFormulaTest(unittest.TestCase):
    def test_spec_example(self) -> None:
        self.assertEqual(calculate_merchant_rating(90, 50), Decimal("74.00"))

    def test_rating_is_deterministic_for_a_known_pair(self) -> None:
        self.assertEqual(calculate_merchant_rating(82, 71), Decimal("77.60"))

    def test_weighting(self) -> None:
        self.assertEqual(calculate_merchant_rating(100, 0), Decimal("60.00"))
        self.assertEqual(calculate_merchant_rating(0, 100), Decimal("40.00"))

    def test_bands_follow_the_exact_table(self) -> None:
        cases = {
            "100": RiskLevel.GOOD,
            "80": RiskLevel.GOOD,
            "79.99": RiskLevel.FAIR,
            "60": RiskLevel.FAIR,
            "59.99": RiskLevel.LOW,
            "40": RiskLevel.LOW,
            "39.99": RiskLevel.VERY_LOW,
            "0": RiskLevel.VERY_LOW,
        }
        for rating, expected in cases.items():
            with self.subTest(rating=rating):
                self.assertIs(risk_level_for(Decimal(rating)), expected)

    def test_out_of_range_scores_are_rejected(self) -> None:
        for bad in (-1, 101, "abc", None, True):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    calculate_merchant_rating(bad, 50)


class MerchantRiskRuleTest(unittest.TestCase):
    def test_rating_at_or_above_60_does_not_ask(self) -> None:
        for credit, feedback in ((90, 78), (68, 60), (100, 100)):
            with self.subTest(credit=credit, feedback=feedback):
                evaluation = evaluate_merchant_risk(
                    plan(1), risk(credit=credit, feedback=feedback)
                )
                self.assertTrue(evaluation.passed, evaluation.reason)

    def test_rating_below_60_triggers_ask_not_deny(self) -> None:
        for credit, feedback in ((55, 50), (0, 0), (58, 58)):
            with self.subTest(credit=credit, feedback=feedback):
                evaluation = evaluate_merchant_risk(
                    plan(1), risk(credit=credit, feedback=feedback)
                )
                self.assertFalse(evaluation.passed)
                self.assertIs(evaluation.severity.value, "ASK")
                self.assertEqual(evaluation.code, RuleCode.MERCHANT_RATING_LOW)

    def test_missing_risk_data_is_a_hard_denial(self) -> None:
        evaluation = evaluate_merchant_risk(plan(1), None)
        self.assertFalse(evaluation.passed)
        self.assertEqual(evaluation.code, RuleCode.MERCHANT_RISK_DATA_UNAVAILABLE)
        self.assertEqual(evaluation.severity.value, "HARD_DENY")
        self.assertIn("Merchant risk data is unavailable", evaluation.reason)

    def test_reason_never_describes_low_as_low_risk(self) -> None:
        evaluation = evaluate_merchant_risk(plan(1), risk(credit=55, feedback=50))
        self.assertIn("low safety rating", evaluation.reason)
        self.assertNotIn("low risk", evaluation.reason)


class MerchantRiskResolutionTest(unittest.TestCase):
    def test_plan_scores_win_when_present(self) -> None:
        provider = StaticRiskProvider({"merchant-001": risk(credit=10, feedback=10)})
        resolved = resolve_merchant_risk(plan(1, credit=90, feedback=78), provider)
        self.assertEqual(resolved.merchant_rating, Decimal("85.20"))

    def test_provider_is_used_when_plan_scores_are_absent(self) -> None:
        provider = StaticRiskProvider({"merchant-001": risk(credit=90, feedback=78)})
        resolved = resolve_merchant_risk(plan(1, credit=None, feedback=None), provider)
        self.assertEqual(resolved.merchant_rating, Decimal("85.20"))

    def test_no_provider_and_no_scores_means_unavailable(self) -> None:
        self.assertIsNone(resolve_merchant_risk(plan(1, credit=None, feedback=None), None))

    def test_invalid_plan_scores_are_unavailable_not_approved(self) -> None:
        self.assertIsNone(resolve_merchant_risk(plan(1, credit=150, feedback=78), None))
        self.assertIsNone(resolve_merchant_risk(plan(1, credit="junk", feedback=78), None))

    def test_provider_failure_is_unavailable_not_approved(self) -> None:
        class ExplodingProvider:
            def lookup(self, purchase_plan):
                raise RuntimeError("catalog offline")

        self.assertIsNone(
            resolve_merchant_risk(plan(1, credit=None, feedback=None), ExplodingProvider())
        )


class MerchantRiskDecisionTest(unittest.TestCase):
    def test_low_rating_produces_ask_with_blacklist_option(self) -> None:
        firewall = FinancialFirewall(AuthorizationEngine())
        decision = firewall.evaluate_purchase_plans(
            FirewallRequest(
                plans=(plan(1, total="150.00", credit=55, feedback=50),),
                context=context(),
            )
        )
        self.assertIs(decision.status, DecisionStatus.ASK)
        self.assertTrue(decision.allow_blacklist_option)
        self.assertEqual(decision.ask_reasons[0].value, "MERCHANT_RATING_LOW")
        self.assertEqual(decision.merchant_risk.merchant_rating, Decimal("53.00"))
        self.assertIs(decision.merchant_risk.risk_level, RiskLevel.LOW)

    def test_missing_risk_data_denies_the_plan(self) -> None:
        firewall = FinancialFirewall(AuthorizationEngine())
        decision = firewall.evaluate_purchase_plans(
            FirewallRequest(
                plans=(plan(1, total="150.00", credit=None, feedback=None),),
                context=context(),
            )
        )
        self.assertIs(decision.status, DecisionStatus.DENY)
        self.assertIn(RuleCode.MERCHANT_RISK_DATA_UNAVAILABLE, decision.failed_rules)

    def test_catalog_provider_supplies_risk_data(self) -> None:
        provider = StaticRiskProvider({"merchant-001": risk(credit=95, feedback=82)})
        firewall = FinancialFirewall(AuthorizationEngine())
        decision = firewall.evaluate_purchase_plans(
            FirewallRequest(
                plans=(plan(1, total="150.00", credit=None, feedback=None),),
                context=context(provider=provider),
            )
        )
        self.assertIs(decision.status, DecisionStatus.APPROVE)
        self.assertEqual(decision.merchant_risk.merchant_rating, Decimal("89.80"))

    def test_low_rating_does_not_deny_even_when_user_setting_is_strict(self) -> None:
        firewall = FinancialFirewall(AuthorizationEngine())
        decision = firewall.evaluate_purchase_plans(
            FirewallRequest(
                plans=(plan(1, total="150.00", credit=30, feedback=20),),
                context=context(authorization=auth("300", "1000", "200")),
            )
        )
        self.assertIs(decision.status, DecisionStatus.ASK)
        self.assertEqual(decision.failed_rules, ())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
