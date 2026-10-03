"""The audit trail: every evaluation recorded, with reasons from real rule data."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from firewall import AuditService, AuthorizationEngine, DecisionStatus, UserConfirmation
from firewall.authorization_engine import FirewallRequest, FinancialFirewall

from tests.factories import CONFIRM, CONFIRM_AND_BLACKLIST, DECLINE, context, plan, responses

FIXED = datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)


def _firewall(**kwargs):
    engine = AuthorizationEngine(**kwargs)
    return FinancialFirewall(engine), engine


class AuditRecordTest(unittest.TestCase):
    def test_every_plan_evaluation_is_recorded(self) -> None:
        firewall, engine = _firewall()
        firewall.evaluate_purchase_plans(
            FirewallRequest(
                plans=(plan(1, total="400.00"), plan(2, total="150.00")),
                context=context(daily_spent="100.00"),
            )
        )
        events = engine.audit_service.events
        self.assertEqual([event.plan_rank for event in events], [1, 2])
        self.assertEqual([event.decision.value for event in events], ["DENY", "APPROVE"])

    def test_denied_event_records_rule_data(self) -> None:
        firewall, engine = _firewall()
        firewall.evaluate_purchase_plans(
            FirewallRequest(
                plans=(plan(1, total="350.00", merchant_id="merchant-007"),),
                context=context(daily_spent="800.00"),
            )
        )
        event = engine.audit_service.events[0]
        self.assertEqual(event.decision, DecisionStatus.DENY)
        self.assertEqual(event.merchant_id, "merchant-007")
        self.assertEqual(event.product_id, "WM-001")
        self.assertEqual(event.final_total.amount_string(), "350.00")
        self.assertEqual(event.daily_spent_before.amount_string(), "800.00")
        self.assertEqual(event.projected_daily_spent.amount_string(), "1150.00")
        self.assertIn("MAX_PER_TRANSACTION", [code.value for code in event.evaluated_rules])
        self.assertIn("MAX_DAILY_SPEND", [code.value for code in event.failed_rules])
        self.assertIn("MAX_PER_TRANSACTION", [code.value for code in event.failed_rules])
        self.assertTrue(event.reason)
        self.assertEqual(event.merchant_rating, event.merchant_rating)  # present, not None
        self.assertIsNotNone(event.merchant_rating)
        self.assertEqual(event.final_total.currency.value, "HKD")

    def test_ask_event_then_confirmation_event(self) -> None:
        firewall, engine = _firewall()
        firewall.evaluate_purchase_plans(
            FirewallRequest(
                plans=(plan(1, total="250.00"),),
                context=context(),
                confirmation_provider=lambda evaluation: CONFIRM,
            )
        )
        events = engine.audit_service.events
        self.assertEqual([event.decision.value for event in events], ["ASK", "APPROVE"])
        self.assertIsNone(events[0].user_confirmation)
        self.assertIs(events[1].user_confirmation, UserConfirmation.CONFIRMED)
        self.assertEqual(events[1].event_type, "ASK_RESOLUTION")

    def test_declined_ask_is_recorded_as_declined(self) -> None:
        firewall, engine = _firewall()
        firewall.evaluate_purchase_plans(
            FirewallRequest(
                plans=(plan(1, total="250.00"),),
                context=context(),
                confirmation_provider=lambda evaluation: DECLINE,
            )
        )
        events = engine.audit_service.events
        self.assertIs(events[-1].user_confirmation, UserConfirmation.DECLINED)
        self.assertEqual(events[-1].decision, DecisionStatus.DENY)

    def test_blacklist_action_is_recorded(self) -> None:
        firewall, engine = _firewall()
        firewall.evaluate_purchase_plans(
            FirewallRequest(
                plans=(plan(1, total="250.00", credit=55, feedback=50),),
                context=context(),
                confirmation_provider=lambda evaluation: CONFIRM_AND_BLACKLIST,
            )
        )
        action = [
            event
            for event in engine.audit_service.events
            if event.event_type == "BLACKLIST_ACTION"
        ]
        self.assertEqual(len(action), 1)
        self.assertTrue(action[0].merchant_blacklisted)
        self.assertIn("blacklist", action[0].reason)

    def test_decision_reasons_are_derived_from_recorded_rules(self) -> None:
        firewall, engine = _firewall()
        decision = firewall.evaluate_purchase_plans(
            FirewallRequest(
                plans=(plan(1, total="310.00", shipping="30.00"),), context=context()
            )
        )
        event = engine.audit_service.events[0]
        self.assertIn(event.final_total.format(), decision.plan_results[0].reason)
        self.assertEqual(event.reason, decision.plan_results[0].reason)

    def test_events_carry_session_and_request_ids(self) -> None:
        firewall, engine = _firewall()
        firewall.evaluate_purchase_plans(
            FirewallRequest(
                plans=(plan(1, total="100.00"),),
                context=context(request_id="REQ-42", session_id="session-7"),
            )
        )
        event = engine.audit_service.events[0]
        self.assertEqual(event.request_id, "REQ-42")
        self.assertEqual(event.session_id, "session-7")

    def test_timestamps_use_the_injected_clock(self) -> None:
        audit = AuditService(clock=lambda: FIXED)
        engine = AuthorizationEngine(audit_service=audit)
        FinancialFirewall(engine).evaluate_purchase_plans(
            FirewallRequest(plans=(plan(1, total="100.00"),), context=context())
        )
        self.assertEqual(audit.events[0].timestamp, FIXED.isoformat())


class AuditPersistenceTest(unittest.TestCase):
    def test_jsonl_file_is_written_and_parseable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.jsonl"
            audit = AuditService(path=path)
            engine = AuthorizationEngine(audit_service=audit)
            FinancialFirewall(engine).evaluate_purchase_plans(
                FirewallRequest(
                    plans=(plan(1, total="400.00"), plan(2, total="150.00")),
                    context=context(),
                )
            )
            lines = path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            payloads = [json.loads(line) for line in lines]
            self.assertEqual(payloads[0]["planRank"], 1)
            self.assertEqual(payloads[0]["decision"], "DENY")
            self.assertIn("evaluatedRules", payloads[0])
            self.assertIn("projectedDailySpent", payloads[0])

    def test_to_jsonl_matches_recorded_events(self) -> None:
        audit = AuditService(clock=lambda: FIXED)
        engine = AuthorizationEngine(audit_service=audit)
        FinancialFirewall(engine).evaluate_purchase_plans(
            FirewallRequest(plans=(plan(1, total="100.00"),), context=context())
        )
        lines = audit.to_jsonl().strip().splitlines()
        self.assertEqual(len(lines), len(audit.events))
        self.assertEqual(json.loads(lines[0])["id"], "audit-000001")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
