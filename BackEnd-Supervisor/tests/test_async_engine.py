"""Async evaluation and the synchronous guard against awaitables."""

from __future__ import annotations

import asyncio
import unittest

from firewall import AuthorizationEngine, DecisionStatus
from firewall.authorization_engine import FirewallRequest, FinancialFirewall

from tests.factories import CONFIRM, DECLINE, context, plan


class AsyncEngineTest(unittest.TestCase):
    def test_async_provider_can_confirm(self) -> None:
        firewall = FinancialFirewall(AuthorizationEngine())

        async def provider(evaluation):
            await asyncio.sleep(0)
            return CONFIRM

        decision = asyncio.run(
            firewall.evaluate_purchase_plans_async(
                FirewallRequest(
                    plans=(plan(1, total="250.00"),),
                    context=context(),
                    confirmation_provider=provider,
                )
            )
        )
        self.assertIs(decision.status, DecisionStatus.APPROVE)
        self.assertEqual(decision.approved_plan.rank, 1)

    def test_sync_provider_is_accepted_by_the_async_engine(self) -> None:
        firewall = FinancialFirewall(AuthorizationEngine())
        decision = asyncio.run(
            firewall.evaluate_purchase_plans_async(
                FirewallRequest(
                    plans=(plan(1, total="250.00"),),
                    context=context(),
                    confirmation_provider=lambda evaluation: CONFIRM,
                )
            )
        )
        self.assertIs(decision.status, DecisionStatus.APPROVE)

    def test_async_decline_moves_to_the_next_plan(self) -> None:
        firewall = FinancialFirewall(AuthorizationEngine())

        async def provider(evaluation):
            return DECLINE if evaluation.plan.rank == 1 else CONFIRM

        decision = asyncio.run(
            firewall.evaluate_purchase_plans_async(
                FirewallRequest(
                    plans=(plan(1, total="250.00"), plan(2, total="150.00")),
                    context=context(),
                    confirmation_provider=provider,
                )
            )
        )
        self.assertIs(decision.status, DecisionStatus.APPROVE)
        self.assertEqual(decision.approved_plan.rank, 2)

    def test_async_without_provider_suspends(self) -> None:
        firewall = FinancialFirewall(AuthorizationEngine())
        decision = asyncio.run(
            firewall.evaluate_purchase_plans_async(
                FirewallRequest(plans=(plan(1, total="250.00"),), context=context())
            )
        )
        self.assertIs(decision.status, DecisionStatus.ASK)
        self.assertIsNotNone(decision.ask_id)
        resolved = firewall.resolve_ask(decision.ask_id, CONFIRM)
        self.assertIs(resolved.status, DecisionStatus.APPROVE)

    def test_sync_engine_rejects_an_async_provider(self) -> None:
        firewall = FinancialFirewall(AuthorizationEngine())

        async def provider(evaluation):
            return CONFIRM

        with self.assertRaises(TypeError):
            firewall.evaluate_purchase_plans(
                FirewallRequest(
                    plans=(plan(1, total="250.00"),),
                    context=context(),
                    confirmation_provider=provider,
                )
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
