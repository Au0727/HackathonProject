"""Exact money arithmetic: no floating point boundary surprises."""

from __future__ import annotations

import unittest
from decimal import Decimal

from firewall import Currency, Money, MoneyError
from firewall.money import HKD_ZERO


class MoneyTest(unittest.TestCase):
    def test_minor_units_represent_cents(self) -> None:
        self.assertEqual(Money.parse("300.00").minor_units, 30000)
        self.assertEqual(Money.parse(300).minor_units, 30000)
        self.assertEqual(Money.parse(300.0).minor_units, 30000)
        self.assertEqual(Money.parse(Decimal("300.01")).minor_units, 30001)

    def test_float_inputs_do_not_drift(self) -> None:
        # 0.1 + 0.2 == 0.30000000000000004 in binary floating point.
        self.assertEqual(Money.parse(0.1 + 0.2), Money.parse("0.30"))
        self.assertEqual(Money.parse(116.92).amount_string(), "116.92")

    def test_boundary_comparisons_are_exact(self) -> None:
        limit = Money.parse("300.00")
        self.assertLessEqual(Money.parse("300.00"), limit)
        self.assertGreater(Money.parse("300.01"), limit)
        self.assertLess(Money.parse("299.99"), limit)
        self.assertEqual(Money.parse("300.00").compare(limit), 0)

    def test_arithmetic_is_exact(self) -> None:
        total = Money.parse("280.00") + Money.parse("30.00") + Money.parse("0.00")
        self.assertEqual(total, Money.parse("310.00"))
        self.assertEqual((Money.parse("800.00") + Money.parse("250.00")).amount_string(), "1050.00")

    def test_rounding_is_half_up_to_cents(self) -> None:
        self.assertEqual(Money.parse("0.005").minor_units, 1)
        self.assertEqual(Money.parse("0.004").minor_units, 0)

    def test_formatting(self) -> None:
        self.assertEqual(Money.parse("310").format(), "HKD 310.00")
        self.assertEqual(Money.parse("0").format(), "HKD 0.00")
        self.assertEqual(str(Money.parse("12.5")), "12.50")

    def test_currency_mismatch_is_rejected(self) -> None:
        usd = Money(100, Currency.HKD)  # only HKD exists today
        with self.assertRaises(MoneyError):
            Money.parse("10.00", currency=Currency.HKD) + Money(1, "HKD")  # type: ignore[arg-type]

    def test_invalid_values_raise(self) -> None:
        for bad in ("abc", None, True, float("nan"), float("inf")):
            with self.subTest(value=bad):
                with self.assertRaises(MoneyError):
                    Money.parse(bad)

    def test_negative_and_zero_helpers(self) -> None:
        self.assertTrue(HKD_ZERO.is_zero())
        self.assertTrue(Money.parse("-1.00").is_negative())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
