"""
test_firewall_bridge.py
=======================
Tests for the integration between the shopping agent and the Financial Firewall.

These cover the bridge's own contract -- what it builds, what it keeps, and what
it refuses to invent. They do **not** re-test the firewall's rules; those have
their own 158 tests in ``BackEnd-Supervisor/tests``.

No network, no API key: the agent runs on ``OfflineRuleBasedLLM`` and the firewall
contains no language model at all.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import firewall_bridge as bridge  # noqa: E402


def _tiny_inventory():
    """Two products: one mapped by the base catalogue, one that is not."""
    from intent_to_purchase import Product

    return [
        Product.model_validate({
            "product_id": "WM-022", "brand": "Kensington",
            "product_name": "Kensington BioFit Mouse (Elite, Matte Black)",
            "description": "Ergonomic wireless mouse.",
            "price": "389.92", "shipping_fee": "0.00", "bundle_promotion": None,
        }),
        Product.model_validate({
            "product_id": "WM-999", "brand": "Brand New",
            "product_name": "Brand New Vertical Mouse (V1, Graphite)",
            "description": "Ergonomic wireless mouse from a new merchant.",
            "price": "120.00", "shipping_fee": "0.00", "bundle_promotion": None,
        }),
    ]


class TestMerchantDirectory(unittest.TestCase):
    """The bridge must extend coverage without inventing anything silently."""

    @classmethod
    def setUpClass(cls):
        cls.repo = HERE
        cls.base_catalog = bridge.SUPERVISOR_DIR / "samples" / "merchant_catalog.json"
        cls.scratch = cls.repo / ".tmpbridge-dir"
        cls.scratch.mkdir(exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.scratch, ignore_errors=True)

    def _build(self):
        return bridge.build_merchant_directory(
            _tiny_inventory(),
            base_catalog_path=self.base_catalog,
            output_path=self.scratch / "merchant_directory.json",
            verbose=False,
        )

    def test_every_product_gets_a_merchant(self):
        directory, stats = self._build()
        for product in _tiny_inventory():
            self.assertIn(product.product_id, directory["productMerchants"])
        self.assertEqual(stats["products_added"], 1)   # WM-022 was already mapped

    def test_existing_records_are_preserved_exactly(self):
        base = json.loads(self.base_catalog.read_text(encoding="utf-8"))
        directory, _ = self._build()
        for merchant_id, record in base["merchants"].items():
            self.assertEqual(directory["merchants"][merchant_id], record)
        # The pre-existing product mapping is untouched.
        self.assertEqual(
            directory["productMerchants"]["WM-022"],
            base["productMerchants"]["WM-022"],
        )

    def test_scores_are_deterministic(self):
        """The firewall promises identical decisions for identical inputs, so a
        randomised risk score would break it."""
        first, _ = self._build()
        second, _ = self._build()
        self.assertEqual(first["merchants"], second["merchants"])

    def test_new_merchants_carry_both_scores(self):
        directory, _ = self._build()
        record = directory["merchants"]["brand-brand-new"]
        self.assertIsNotNone(record["merchantCreditScore"])
        self.assertIsNotNone(record["buyerFeedbackScore"])
        # Scores stay inside the range the bridge advertises.
        self.assertTrue(72 <= record["merchantCreditScore"] <= 95)
        self.assertTrue(70 <= record["buyerFeedbackScore"] <= 94)

    def test_auto_mapped_merchant_is_labelled(self):
        directory, _ = self._build()
        name = directory["merchants"]["brand-brand-new"]["merchantName"]
        self.assertIn("auto-mapped", name)

    def test_missing_base_catalogue_raises(self):
        with self.assertRaises(bridge.BridgeError):
            bridge.build_merchant_directory(
                _tiny_inventory(),
                base_catalog_path=self.scratch / "nope.json",
                output_path=self.scratch / "out.json",
                verbose=False,
            )


class TestFinalReport(unittest.TestCase):
    """The bridge emits at most `keep` authorized options, and only APPROVED ones."""

    def _base_report(self, options_per_request=3):
        return {
            "report_type": "optimal_selection",
            "session": "test",
            "currency": "HKD",
            "requests_made": 1,
            "results": [{
                "request_id": "REQ-001",
                "request": "a mouse",
                "status": "OK",
                "cap_enforced": "800.00",
                "best_options": [
                    {"rank": rank, "product_id": f"WM-{rank:03d}",
                     "product_name": f"Mouse {rank}", "brand": "MX",
                     "description": "d", "price": "100.00",
                     "shipping_fee": "0.00", "total_cost": "100.00",
                     "currency": "HKD", "quantity": 1}
                    for rank in range(1, options_per_request + 1)
                ],
            }],
        }

    def _bridge_outcome(self, approved_ranks):
        class _Plan:
            def __init__(self, rank):
                self.rank = rank
                self.merchant_id = f"brand-{rank}"
                self.merchant_name = f"Merchant {rank}"

        return {
            "selected": {"REQ-001": list(approved_ranks)},
            "evaluations": {"REQ-001": []},
            "plans_by_request": {
                "REQ-001": {r: _Plan(r) for r in range(1, 4)}
            },
            "priority": {},
            "authorization": {"currency": "HKD"},
        }

    def test_keeps_at_most_two_options(self):
        report = bridge.build_final_report(
            self._base_report(3), self._bridge_outcome([1, 2, 3]), keep=2
        )
        options = report["results"][0]["best_options"]
        self.assertEqual(len(options), 2)
        self.assertEqual([o["rank"] for o in options], [1, 2])

    def test_keep_one_is_honoured(self):
        report = bridge.build_final_report(
            self._base_report(3), self._bridge_outcome([1, 2, 3]), keep=1
        )
        self.assertEqual(len(report["results"][0]["best_options"]), 1)

    def test_denied_ranks_are_excluded(self):
        report = bridge.build_final_report(
            self._base_report(3), self._bridge_outcome([2, 3]), keep=2
        )
        ranks = [o["rank"] for o in report["results"][0]["best_options"]]
        self.assertEqual(ranks, [2, 3])
        self.assertNotIn(1, ranks)

    def test_nothing_approved_yields_no_results_and_zero_total(self):
        report = bridge.build_final_report(
            self._base_report(3), self._bridge_outcome([]), keep=2
        )
        self.assertEqual(report["results"], [])
        self.assertEqual(report["requests_with_options"], 0)
        self.assertEqual(report["grand_total"]["grand_total"], "0.00")
        self.assertEqual(report["grand_total"]["items_selected"], 0)

    def test_grand_total_sums_only_authorized_options(self):
        report = bridge.build_final_report(
            self._base_report(3), self._bridge_outcome([1, 2, 3]), keep=2
        )
        self.assertEqual(report["grand_total"]["grand_total"], "200.00")
        self.assertEqual(report["grand_total"]["items_selected"], 2)

    def test_options_are_flagged_as_authorized(self):
        report = bridge.build_final_report(
            self._base_report(2), self._bridge_outcome([1, 2]), keep=2
        )
        for option in report["results"][0]["best_options"]:
            self.assertTrue(option["authorized"])
            self.assertEqual(option["authorized_by"], "financial_firewall")

    def test_merchant_details_are_attached(self):
        report = bridge.build_final_report(
            self._base_report(2), self._bridge_outcome([1, 2]), keep=2
        )
        options = report["results"][0]["best_options"]
        self.assertEqual(options[0]["merchant_name"], "Merchant 1")
        self.assertEqual(options[0]["merchant_id"], "brand-1")

    def test_report_type_marks_the_authorized_stage(self):
        report = bridge.build_final_report(self._base_report(1), self._bridge_outcome([1]))
        self.assertEqual(report["report_type"], "authorized_selection")


class TestEndToEnd(unittest.TestCase):
    """The whole pipeline, offline, against the real supervisor package."""

    def test_three_options_reduce_to_two(self):
        final, meta = bridge.run(
            ["Find me a Kensington wireless mouse under $800 total."],
            options=3, keep=2, stream=None, offline=True,
        )
        self.assertEqual(final["report_type"], "authorized_selection")
        emitted = sum(len(r["best_options"]) for r in final["results"])
        self.assertLessEqual(emitted, 2)
        self.assertEqual(final["grand_total"]["items_selected"], emitted)

    def test_a_tight_transaction_cap_denies_everything(self):
        final, _ = bridge.run(
            ["Find me a Kensington wireless mouse under $800 total."],
            options=3, keep=2, stream=None, offline=True,
            max_per_transaction="1.00",
        )
        self.assertEqual(final["results"], [])
        self.assertEqual(final["grand_total"]["grand_total"], "0.00")

    def test_an_exhausted_daily_budget_denies_everything(self):
        final, _ = bridge.run(
            ["Find me a Kensington wireless mouse under $800 total."],
            options=3, keep=2, stream=None, offline=True,
            max_daily_spend="10.00", daily_spent="10.00",
        )
        self.assertEqual(final["results"], [])

    def test_the_agent_report_is_written_to_disk(self):
        _, meta = bridge.run(
            ["Find me a Kensington wireless mouse under $800 total."],
            options=3, keep=2, stream=None, offline=True,
        )
        path = Path(meta["report_path"])
        self.assertTrue(path.is_file())
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["report_type"], "optimal_selection")

    def test_final_report_round_trips_through_json(self):
        final, _ = bridge.run(
            ["Find me a Kensington wireless mouse under $800 total."],
            options=3, keep=2, stream=None, offline=True,
        )
        text = json.dumps(final, ensure_ascii=False)
        restored = json.loads(text)
        self.assertEqual(restored["grand_total"], final["grand_total"])

    def test_dry_run_skips_the_firewall(self):
        _, meta = bridge.run(
            ["Find me a Kensington wireless mouse under $800 total."],
            options=3, keep=2, stream=None, offline=True, dry_run=True,
        )
        self.assertTrue(meta["dry_run"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
