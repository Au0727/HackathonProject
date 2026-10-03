"""Validation: fail closed, never silently approve."""

from __future__ import annotations

import unittest
from decimal import Decimal

from firewall import (
    AuthorizationContext,
    AuthorizationEngine,
    AuthorizationValidationError,
    Currency,
    Money,
    PlanSetError,
    PurchasePlan,
    UserAuthorization,
    validate_plan,
    validate_user_authorization,
)
from firewall.authorization_engine import FirewallRequest, FinancialFirewall

from tests.factories import auth, context, plan


class AuthorizationValidationTest(unittest.TestCase):
    def test_valid_settings_pass(self) -> None:
        validate_user_authorization(auth("300", "1000", "200"))

    def test_threshold_equal_to_max_per_transaction_is_allowed(self) -> None:
        validate_user_authorization(auth("300", "1000", "300"))

    def test_invalid_settings_raise_english_messages(self) -> None:
        cases = {
            "max_per_transaction zero": auth("0", "1000", "0"),
            "max_per_transaction negative": auth("-1", "1000", "0"),
            "max_daily_spend zero": auth("300", "0", "0"),
            "confirmation_threshold negative": auth("300", "1000", "-1"),
            "confirmation_threshold above limit": auth("300", "1000", "301"),
        }
        for label, authorization in cases.items():
            with self.subTest(label):
                with self.assertRaises(AuthorizationValidationError) as caught:
                    validate_user_authorization(authorization)
                message = str(caught.exception)
                self.assertTrue(message.isascii())
                self.assertTrue(message.endswith("."))
                self.assertNotIn("Exception", message)

    def test_engine_refuses_to_evaluate_with_invalid_settings(self) -> None:
        firewall = FinancialFirewall(AuthorizationEngine())
        bad_context = AuthorizationContext(
            authorization=auth("300", "1000", "400"),
            daily_spent=Money.zero(),
        )
        with self.assertRaises(AuthorizationValidationError):
            firewall.evaluate_purchase_plans(
                FirewallRequest(plans=(plan(1, total="100.00"),), context=bad_context)
            )

    def test_negative_daily_spending_is_rejected(self) -> None:
        firewall = FinancialFirewall(AuthorizationEngine())
        with self.assertRaises(AuthorizationValidationError):
            firewall.evaluate_purchase_plans(
                FirewallRequest(
                    plans=(plan(1, total="100.00"),), context=context(daily_spent="-1.00")
                )
            )

    def test_currency_must_be_hkd(self) -> None:
        authorization = UserAuthorization(
            max_per_transaction=Money(30000, Currency.HKD),
            max_daily_spend=Money(100000, Currency.HKD),
            confirmation_threshold=Money(20000, Currency.HKD),
        )
        validate_user_authorization(authorization)


class PlanValidationTest(unittest.TestCase):
    def test_valid_plan_has_no_problems(self) -> None:
        self.assertEqual(validate_plan(plan(1, total="100.00")), ())

    def test_each_invalid_plan_reports_a_reason(self) -> None:
        cases = {
            "rank 0": plan(0, total="100.00"),
            "rank 4": plan(4, total="100.00"),
            "quantity 0": plan(1, total="100.00", quantity=0),
            "quantity not an int": plan(1, total="100.00", quantity="1"),  # type: ignore[arg-type]
            "negative total": plan(1, subtotal="-50.00", total="-50.00"),
            "total mismatch": plan(1, subtotal="10.00", total="99.00"),
            "missing product id": plan(1, total="100.00", product_id=""),
            "missing merchant id": plan(1, total="100.00", merchant_id=""),
            "credit score out of range": plan(1, total="100.00", credit=150),
            "feedback score out of range": plan(1, total="100.00", feedback=-1),
            "credit score not a number": plan(1, total="100.00", credit="junk"),
        }
        for label, purchase_plan in cases.items():
            with self.subTest(label):
                problems = validate_plan(purchase_plan)
                self.assertTrue(problems, f"{label} should be invalid")

    def test_plan_invalid_data_denies_rather_than_approves(self) -> None:
        firewall = FinancialFirewall(AuthorizationEngine())
        decision = firewall.evaluate_purchase_plans(
            FirewallRequest(
                plans=(plan(1, quantity=0, total="100.00"),),
                context=context(),
            )
        )
        self.assertTrue(decision.failed_rules)
        self.assertIn("INVALID_PLAN_DATA", [code.value for code in decision.failed_rules])


class PlanSetValidationTest(unittest.TestCase):
    def test_duplicate_ranks_raise(self) -> None:
        firewall = FinancialFirewall(AuthorizationEngine())
        with self.assertRaises(PlanSetError):
            firewall.evaluate_purchase_plans(
                FirewallRequest(
                    plans=(plan(1, total="100.00"), plan(1, total="100.00")),
                    context=context(),
                )
            )

    def test_an_invalid_rank_plan_is_denied_not_raised(self) -> None:
        firewall = FinancialFirewall(AuthorizationEngine())
        decision = firewall.evaluate_purchase_plans(
            FirewallRequest(plans=(plan(7, total="100.00"),), context=context())
        )
        self.assertTrue(decision.failed_rules)

    def test_structurally_wrong_object_is_rejected(self) -> None:
        firewall = FinancialFirewall(AuthorizationEngine())
        with self.assertRaises(PlanSetError):
            firewall.evaluate_purchase_plans(
                FirewallRequest(plans=(({"rank": 1},)), context=context())  # type: ignore[arg-type]
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
