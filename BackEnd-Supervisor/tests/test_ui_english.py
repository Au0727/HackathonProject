"""User-facing rendering: English only, progressive disclosure."""

from __future__ import annotations

import unittest

from firewall import AuthorizationEngine, ui
from firewall.authorization_engine import FirewallRequest, FinancialFirewall
from firewall.models import PlanEvaluation

from tests.factories import auth, context, plan


def _evaluate(plans, provider=None, **context_kwargs):
    firewall = FinancialFirewall(AuthorizationEngine())
    return firewall.evaluate_purchase_plans(
        FirewallRequest(
            plans=tuple(plans), context=context(**context_kwargs), confirmation_provider=provider
        )
    )


def _evaluation(purchase_plan, **context_kwargs) -> PlanEvaluation:
    engine = AuthorizationEngine()
    return engine.evaluate_plan(purchase_plan, context(**context_kwargs))


class EnglishOnlyTest(unittest.TestCase):
    def test_all_rendered_text_is_ascii(self) -> None:
        rendered = [
            ui.render_authorization_summary(auth(), __import__("firewall").Money.parse("400")),
            ui.render_ask(_evaluation(plan(1, total="250.00", credit=55, feedback=50))),
            ui.render_decision(_evaluate((plan(1, total="100.00"),))),
            ui.render_decision(_evaluate((plan(1, total="500.00"),))),
            ui.render_decision(_evaluate((plan(1, total="250.00"),))),
        ]
        for text in rendered:
            with self.subTest(text=text[:40]):
                self.assertTrue(text.isascii(), "user-facing text must be English/ASCII")

    def test_key_phrases_are_present(self) -> None:
        approval = ui.render_decision(_evaluate((plan(1, total="100.00"),)))
        self.assertIn("Purchase Approved", approval)
        self.assertIn("Authorization: APPROVE", approval)

        denial = ui.render_decision(_evaluate((plan(1, total="500.00"),)))
        self.assertIn("Authorization: DENY", denial)
        self.assertIn("Why?", denial)
        self.assertIn("MAX_PER_TRANSACTION", denial)

        ask = ui.render_ask(_evaluation(plan(1, total="250.00", credit=55, feedback=50)))
        self.assertIn("Purchase Confirmation Required", ask)
        self.assertIn("Merchant Safety Rating is low", ask)
        self.assertIn("exceeds your confirmation threshold", ask)
        self.assertIn("[1] Continue Purchase", ask)
        self.assertIn("[2] Cancel Purchase", ask)
        self.assertIn("[3] Continue Purchase and Blacklist Merchant", ask)


class AskDialogTest(unittest.TestCase):
    def test_blacklist_option_hidden_without_merchant_risk(self) -> None:
        ask = ui.render_ask(_evaluation(plan(1, total="250.00")))
        self.assertNotIn("Blacklist Merchant", ask)
        self.assertIn("[2] Cancel Purchase", ask)

    def test_single_reason_uses_singular_wording(self) -> None:
        ask = ui.render_ask(_evaluation(plan(1, total="250.00")))
        self.assertIn("for 1 reason:", ask)

    def test_two_reasons_are_combined_in_one_dialog(self) -> None:
        ask = ui.render_ask(_evaluation(plan(1, total="250.00", credit=55, feedback=50)))
        self.assertIn("for 2 reasons:", ask)
        self.assertIn("1.", ask)
        self.assertIn("2.", ask)

    def test_risk_language_never_calls_low_rating_low_risk(self) -> None:
        ask = ui.render_ask(_evaluation(plan(1, total="150.00", credit=40, feedback=30)))
        self.assertIn("Merchant Safety Rating is low", ask)
        self.assertNotIn("low risk", ask.lower())


class ProgressiveDisclosureTest(unittest.TestCase):
    def test_approval_lists_the_plan_and_totals(self) -> None:
        decision = _evaluate((plan(1, total="150.00", shipping="0.00"),))
        rendered = ui.render_decision(decision)
        self.assertIn("Total: HKD 150.00", rendered)
        self.assertIn("Merchant Safety Rating", rendered)
        self.assertIn("Evaluated plan: rank 1", rendered)

    def test_denial_explains_each_plan(self) -> None:
        decision = _evaluate(
            (plan(1, total="500.00"), plan(2, total="400.00")), daily_spent="0.00"
        )
        rendered = ui.render_decision(decision)
        self.assertIn("Plan 1: DENY", rendered)
        self.assertIn("Plan 2: DENY", rendered)
        self.assertIn("No suitable purchase plan is available", rendered)

    def test_pending_ask_rendering_mentions_that_it_is_not_authorized(self) -> None:
        decision = _evaluate((plan(1, total="250.00"),))
        rendered = ui.render_decision(decision)
        self.assertIn("not authorized", rendered)
        self.assertIn("Confirmation request id", rendered)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
