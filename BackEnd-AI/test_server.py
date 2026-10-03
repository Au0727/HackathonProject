"""Contract tests for the FastAPI adapter joining the UI, agent, and firewall.

These exercise endpoint functions directly; they do not start a server or
perform model/network calls.
"""

from __future__ import annotations

import json
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import server
from intent_to_purchase import StructuredIntent


class _MerchantCatalog:
    def merchant_id_for_product(self, product_id: str) -> str | None:
        return {"p-allowed": "merchant-allowed", "p-other": "merchant-other"}.get(product_id)

    def record_for(self, merchant_id: str):
        return SimpleNamespace(merchant_name=f"Name for {merchant_id}")


class TestApiIntegrationContracts(unittest.TestCase):
    """Verify that mandate constraints and trusted IDs cross the API boundary."""

    def tearDown(self):
        server._payment_transactions.clear()
        server._authorized_transactions.clear()

    def test_search_passes_policy_and_filters_to_the_bridge(self):
        products = [
            SimpleNamespace(product_id="p-allowed", category="Computer Accessories"),
            SimpleNamespace(product_id="p-other", category="Computer Accessories"),
        ]
        intent = StructuredIntent(
            product_keywords=["mouse"],
            raw_request="Find me a mouse",
        )
        mandate = {
            "id": "mandate-test",
            "maxPerTransaction": "300.00",
            "maxDailySpend": "600.00",
            "requiresConfirmationAbove": "250.00",
            "allowedCategories": ["Computer Accessories"],
            "allowedMerchants": ["merchant-allowed"],
        }
        with (
            patch.object(server, "load_products", return_value=products),
            patch.object(server, "_merchant_catalog", return_value=_MerchantCatalog()),
            patch.object(
                server.firewall_bridge,
                "run",
                return_value=({"results": [], "halts": []}, {}),
            ) as run,
        ):
            response = server.shopping_search(
                server.SearchRequest(intent=intent, mandate=mandate, max_results=3)
            )

        self.assertEqual(response.status_code, 200)
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["allowed_product_ids"], {"p-allowed"})
        self.assertEqual(kwargs["max_per_transaction"], "300.00")
        self.assertEqual(kwargs["max_daily_spend"], "600.00")
        self.assertEqual(kwargs["confirmation_threshold"], "250.00")

    def test_catalog_uses_the_supervisors_trusted_merchant_mapping(self):
        product = SimpleNamespace(
            product_id="p-allowed",
            product_name="Test mouse",
            brand="Example",
            price=Decimal("10.00"),
            shipping_fee=Decimal("1.00"),
            description="A test product",
        )
        with (
            patch.object(server, "load_products", return_value=[product]),
            patch.object(server, "_merchant_catalog", return_value=_MerchantCatalog()),
        ):
            response = server.get_catalog()

        row = json.loads(response.body)[0]
        self.assertEqual(row["merchantId"], "merchant-allowed")
        self.assertEqual(row["merchantName"], "Name for merchant-allowed")

    def test_unsupported_ask_decision_fails_closed(self):
        self.assertEqual(server._api_decision("APPROVE"), "ALLOW")
        self.assertEqual(server._api_decision("ASK"), "DENY")
        self.assertEqual(server._api_decision("DENY"), "DENY")

    def test_payment_start_requires_a_server_allow_snapshot(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as raised:
            server.start_payment("txn-unknown", {"id": "txn-unknown"})
        self.assertEqual(raised.exception.status_code, 403)

    def test_payment_completion_uses_the_authorized_mandate_snapshot(self):
        transaction = {
            "id": "txn-bound",
            "productId": "p-allowed",
            "merchantId": "merchant-allowed",
            "subtotal": "10.00",
            "shipping": "1.00",
            "total": "11.00",
            "currency": "HKD",
            "createdAt": "2026-10-03T00:00:00Z",
            "status": "PROPOSED",
        }
        mandate = {"id": "mandate-approved", "maxPerTransaction": "20.00"}
        server._authorized_transactions["txn-bound"] = {
            "mandate": mandate,
            "transaction": transaction,
        }
        server._payment_transactions["txn-bound"] = {
            **transaction,
            "status": "PAYMENT_PENDING",
        }
        submitted = server.TransactionRequest(
            mandate={"id": "mandate-relaxed", "maxPerTransaction": "9999.00"},
            transaction={**transaction, "status": "PAYMENT_PENDING"},
        )
        evaluated = []

        def deny(request):
            evaluated.append(request)
            return {"decision": "DENY"}

        with patch.object(server, "_evaluate_authorization_result", side_effect=deny):
            result = server.complete_payment("txn-bound", submitted)

        self.assertEqual(evaluated[0].mandate, mandate)
        self.assertEqual(json.loads(result.body)["status"], "CANCELLED")

    def test_payment_start_rejects_a_changed_transaction(self):
        from fastapi import HTTPException

        original = {
            "id": "txn-changed",
            "productId": "p-allowed",
            "merchantId": "merchant-allowed",
            "subtotal": "10.00",
            "shipping": "1.00",
            "total": "11.00",
            "currency": "HKD",
            "createdAt": "2026-10-03T00:00:00Z",
        }
        server._authorized_transactions["txn-changed"] = {
            "mandate": {"id": "mandate"},
            "transaction": original,
        }
        changed = {**original, "total": "1.00"}
        with self.assertRaises(HTTPException) as raised:
            server.start_payment("txn-changed", changed)
        self.assertEqual(raised.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main(verbosity=2)
