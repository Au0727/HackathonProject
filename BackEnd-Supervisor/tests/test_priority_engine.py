"""The three-plan priority engine: spec tests 1-8 plus ordering guarantees."""

from __future__ import annotations

import unittest

from firewall import (
    AuthorizationEngine,
    DecisionStatus,
    PlanSetError,
    RuleCode,
)
from firewall.authorization_engine import (
    FirewallRequest,
    FinancialFirewall,
    UnknownAskError,
)
from firewall.messages import FINAL_DENY_NO_PLANS_REASON, FINAL_DENY_REASON, USER_DECLINED_REASON

from tests.factories import CONFIRM, DECLINE, audit_ranks, context, plan, responses, summary


def _firewall():
    engine = AuthorizationEngine()
    return FinancialFirewall(engine), engine


def _runs(plans, *, provider=None, daily_spent="0.00", authorization=None):
    firewall, engine = _firewall()
    decision = firewall.evaluate_purchase_plans(
        FirewallRequest(
            plans=tuple(plans),
            context=context(daily_spent=daily_spent, authorization=authorization),
            confirmation_provider=provider,
        )
    )
    return decision, engine


# Plans that would fail loudly if they were ever evaluated.
BLOCKED_RANK_2 = plan(2, merchant_id="merchant-404", subtotal="10.00", total="99.00")
BLOCKED_RANK_3 = plan(3, merchant_id="merchant-404", subtotal="10.00", total="99.00")
UNKNOWN_MERCHANT_RANK_3 = plan(3, merchant_id="merchant-404")


class ThreePlanPriorityTest(unittest.TestCase):
    def test_1_plan_1_approved_stops_evaluation(self) -> None:
        decision, engine = _runs(
            (plan(1, total="100.00"), BLOCKED_RANK_2, UNKNOWN_MERCHANT_RANK_3)
        )
        self.assertIs(decision.status, DecisionStatus.APPROVE)
        self.assertEqual(decision.approved_plan.rank, 1)
        self.assertEqual(audit_ranks(engine), [1])

    def test_2_plan_1_denied_then_plan_2_approved(self) -> None:
        decision, engine = _runs(
            (plan(1, total="400.00"), plan(2, total="150.00"), BLOCKED_RANK_3)
        )
        self.assertIs(decision.status, DecisionStatus.APPROVE)
        self.assertEqual(decision.approved_plan.rank, 2)
        self.assertEqual(audit_ranks(engine), [1, 2])

    def test_3_plan_1_and_2_denied_then_plan_3_approved(self) -> None:
        decision, engine = _runs(
            (plan(1, total="400.00"), plan(2, total="350.00"), plan(3, total="150.00"))
        )
        self.assertIs(decision.status, DecisionStatus.APPROVE)
        self.assertEqual(decision.approved_plan.rank, 3)
        self.assertEqual(audit_ranks(engine), [1, 2, 3])

    def test_4_all_plans_denied(self) -> None:
        decision, engine = _runs(
            (
                plan(1, total="400.00"),
                plan(2, total="350.00"),
                plan(3, total="400.01"),
            )
        )
        self.assertIs(decision.status, DecisionStatus.DENY)
        self.assertEqual(decision.reason, FINAL_DENY_REASON)
        self.assertEqual([entry.rank for entry in decision.plan_results], [1, 2, 3])
        self.assertTrue(
            all(entry.status is DecisionStatus.DENY for entry in decision.plan_results)
        )
        self.assertEqual(audit_ranks(engine), [1, 2, 3])

    def test_4b_all_plans_denied_for_distinct_reasons(self) -> None:
        engine = AuthorizationEngine()
        decision = FinancialFirewall(engine).evaluate_purchase_plans(
            FirewallRequest(
                plans=(
                    plan(1, total="500.00", merchant_id="merchant-001"),
                    plan(2, total="300.00", merchant_id="merchant-002"),
                    plan(3, total="100.00", merchant_id="merchant-003"),
                ),
                context=context(daily_spent="800.00", blacklist=["merchant-003"]),
            )
        )
        self.assertIs(decision.status, DecisionStatus.DENY)
        failures = {entry.rank: entry.failed_rules for entry in decision.plan_results}
        self.assertIn(RuleCode.MAX_PER_TRANSACTION, failures[1])
        self.assertIn(RuleCode.MAX_DAILY_SPEND, failures[2])
        self.assertIn(RuleCode.MERCHANT_BLACKLISTED, failures[3])

    def test_5_plan_1_ask_confirmed_approves_plan_1_only(self) -> None:
        decision, engine = _runs(
            (plan(1, total="250.00"), BLOCKED_RANK_2, UNKNOWN_MERCHANT_RANK_3),
            provider=responses({1: CONFIRM}, default=CONFIRM),
        )
        self.assertIs(decision.status, DecisionStatus.APPROVE)
        self.assertEqual(decision.approved_plan.rank, 1)
        self.assertEqual(audit_ranks(engine), [1])

    def test_6_plan_1_ask_rejected_then_plan_2_approved(self) -> None:
        decision, engine = _runs(
            (plan(1, total="250.00"), plan(2, total="150.00"), BLOCKED_RANK_3),
            provider=responses({1: DECLINE}, default=CONFIRM),
        )
        self.assertIs(decision.status, DecisionStatus.APPROVE)
        self.assertEqual(decision.approved_plan.rank, 2)
        self.assertEqual(audit_ranks(engine), [1, 2])

    def test_7_plan_1_ask_rejected_plan_2_denied_plan_3_approved(self) -> None:
        decision, engine = _runs(
            (plan(1, total="250.00"), plan(2, total="400.00"), plan(3, total="150.00")),
            provider=responses({1: DECLINE}, default=CONFIRM),
        )
        self.assertIs(decision.status, DecisionStatus.APPROVE)
        self.assertEqual(decision.approved_plan.rank, 3)
        self.assertEqual(audit_ranks(engine), [1, 2, 3])

    def test_8_plan_1_ask_rejected_plan_2_and_3_denied(self) -> None:
        decision, engine = _runs(
            (plan(1, total="250.00"), plan(2, total="400.00"), plan(3, total="350.00")),
            provider=responses({1: DECLINE}, default=CONFIRM),
        )
        self.assertIs(decision.status, DecisionStatus.DENY)
        self.assertEqual(decision.reason, FINAL_DENY_REASON)
        self.assertEqual(decision.plan_results[0].reason, USER_DECLINED_REASON)
        self.assertIs(decision.plan_results[0].status, DecisionStatus.DENY)


class OrderingGuaranteesTest(unittest.TestCase):
    def test_plans_are_evaluated_in_rank_order_even_when_input_is_scrambled(self) -> None:
        decision, engine = _runs(
            (plan(3, total="150.00"), plan(1, total="100.00"), plan(2, total="400.00"))
        )
        self.assertIs(decision.status, DecisionStatus.APPROVE)
        self.assertEqual(decision.approved_plan.rank, 1)
        self.assertEqual(audit_ranks(engine), [1])

    def test_cheaper_lower_ranked_plan_is_not_preferred(self) -> None:
        decision, engine = _runs((plan(1, total="190.00"), plan(2, total="100.00")))
        self.assertIs(decision.status, DecisionStatus.APPROVE)
        self.assertEqual(decision.approved_plan.rank, 1)
        self.assertEqual(audit_ranks(engine), [1])

    def test_lower_merchant_risk_on_plan_2_does_not_override_plan_1(self) -> None:
        decision, _ = _runs(
            (
                plan(1, total="100.00", credit=65, feedback=60),
                plan(2, total="100.00", credit=100, feedback=100),
            )
        )
        self.assertEqual(decision.approved_plan.rank, 1)

    def test_duplicate_ranks_are_rejected(self) -> None:
        firewall, _ = _firewall()
        with self.assertRaises(PlanSetError):
            firewall.evaluate_purchase_plans(
                FirewallRequest(
                    plans=(plan(1, total="100.00"), plan(1, total="150.00")),
                    context=context(),
                )
            )

    def test_no_plans_is_denied(self) -> None:
        firewall, _ = _firewall()
        decision = firewall.evaluate_purchase_plans(
            FirewallRequest(plans=(), context=context())
        )
        self.assertIs(decision.status, DecisionStatus.DENY)
        self.assertEqual(decision.reason, FINAL_DENY_NO_PLANS_REASON)

    def test_two_plans_are_supported(self) -> None:
        decision, engine = _runs((plan(1, total="400.00"), plan(2, total="150.00")))
        self.assertEqual(decision.approved_plan.rank, 2)
        self.assertEqual(audit_ranks(engine), [1, 2])

    def test_one_plan_is_supported(self) -> None:
        decision, engine = _runs((plan(1, total="150.00"),))
        self.assertIs(decision.status, DecisionStatus.APPROVE)
        self.assertEqual(audit_ranks(engine), [1])


class SuspendedAskTest(unittest.TestCase):
    def test_ask_is_returned_with_an_id_and_can_be_confirmed(self) -> None:
        firewall, engine = _firewall()
        decision = firewall.evaluate_purchase_plans(
            FirewallRequest(
                plans=(plan(1, total="250.00"), BLOCKED_RANK_2, UNKNOWN_MERCHANT_RANK_3),
                context=context(),
            )
        )
        self.assertIs(decision.status, DecisionStatus.ASK)
        self.assertIsNotNone(decision.ask_id)
        self.assertEqual(decision.evaluated_plan_rank, 1)
        self.assertIn(decision.ask_id, engine.pending_ask_ids)

        resolved = firewall.resolve_ask(decision.ask_id, CONFIRM)
        self.assertIs(resolved.status, DecisionStatus.APPROVE)
        self.assertEqual(resolved.approved_plan.rank, 1)
        self.assertEqual(audit_ranks(engine), [1])

    def test_ask_can_be_declined_and_evaluation_continues(self) -> None:
        firewall, engine = _firewall()
        decision = firewall.evaluate_purchase_plans(
            FirewallRequest(
                plans=(plan(1, total="250.00"), plan(2, total="150.00"), BLOCKED_RANK_3),
                context=context(),
            )
        )
        self.assertIs(decision.status, DecisionStatus.ASK)
        resolved = firewall.resolve_ask(decision.ask_id, DECLINE)
        self.assertIs(resolved.status, DecisionStatus.APPROVE)
        self.assertEqual(resolved.approved_plan.rank, 2)
        self.assertEqual(audit_ranks(engine), [1, 2])

    def test_second_suspended_ask_after_a_decline(self) -> None:
        firewall, engine = _firewall()
        first = firewall.evaluate_purchase_plans(
            FirewallRequest(
                plans=(plan(1, total="250.00"), plan(2, total="260.00"), plan(3, total="150.00")),
                context=context(),
            )
        )
        second = firewall.resolve_ask(first.ask_id, DECLINE)
        self.assertIs(second.status, DecisionStatus.ASK)
        self.assertEqual(second.evaluated_plan_rank, 2)
        third = firewall.resolve_ask(second.ask_id, CONFIRM)
        self.assertIs(third.status, DecisionStatus.APPROVE)
        self.assertEqual(third.approved_plan.rank, 2)

    def test_unknown_ask_id_raises(self) -> None:
        firewall, _ = _firewall()
        with self.assertRaises(UnknownAskError):
            firewall.resolve_ask("ask-9999", CONFIRM)

    def test_ask_id_cannot_be_resolved_twice(self) -> None:
        firewall, _ = _firewall()
        decision = firewall.evaluate_purchase_plans(
            FirewallRequest(plans=(plan(1, total="250.00"),), context=context())
        )
        firewall.resolve_ask(decision.ask_id, CONFIRM)
        with self.assertRaises(UnknownAskError):
            firewall.resolve_ask(decision.ask_id, CONFIRM)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
