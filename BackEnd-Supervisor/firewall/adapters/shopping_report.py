"""Adapter: upstream shopping report JSON -> internal purchase plans.

Interpretation rules enforced here:

* different ``request_id`` values are different shopping requests, never
  competing plans for one decision;
* ``best_options[].rank`` is preserved exactly and never re-derived or re-sorted
  by value;
* a plan's own ``total_cost`` is its transaction total; report-level
  ``totals.grand_total`` is never used, and plans are never summed together;
* informational fields (``decision_rule``, ``reason``, ``considered``,
  ``refused``, ``stop_reason``, ``model_*``, ``generated_at``) are read-only
  noise and cannot influence authorization;
* merchant risk scores are never read from the report - only the trusted
  catalogue supplies them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..models import PurchasePlan
from ..money import HKD_ZERO, Money, MoneyError
from ..types import Currency
from .merchant_catalog import MerchantCatalog

__all__ = [
    "ShoppingReportAdapter",
    "ShoppingReport",
    "RequestReport",
    "ShoppingReportError",
    "UnknownRequestError",
    "MAX_PLANS_PER_REQUEST",
    "INFORMATIONAL_FIELDS",
]

#: The firewall considers at most the three highest explicitly ranked options.
MAX_PLANS_PER_REQUEST = 3

#: Upstream fields that describe the agent's reasoning, never the policy.
INFORMATIONAL_FIELDS = frozenset(
    {
        "decision_rule",
        "decisionRule",
        "reason",
        "considered",
        "refused",
        "stop_reason",
        "stopReason",
        "model_backend",
        "modelBackend",
        "model_name",
        "modelName",
        "generated_at",
        "generatedAt",
        "report_type",
        "reportType",
        "session",
        "requests_made",
        "requestsMade",
        "requests_with_options",
        "requestsWithOptions",
        "analysis",
        "notes",
    }
)


class ShoppingReportError(ValueError):
    """Raised when the upstream report cannot be read as structured data."""


class UnknownRequestError(KeyError):
    """Raised when the requested ``request_id`` is not present in the report."""


@dataclass(frozen=True)
class RequestReport:
    """One shopping request and its candidate plans (its own authorization context)."""

    request_id: str
    plans: tuple[PurchasePlan, ...]
    request_text: str | None = None
    currency: Currency = Currency.HKD
    cap_enforced: str | None = None

    @property
    def plan_count(self) -> int:
        return len(self.plans)


@dataclass(frozen=True)
class ShoppingReport:
    """A parsed report; each entry is an independent authorization context."""

    requests: tuple[RequestReport, ...] = ()
    report_type: str | None = None
    currency: Currency = Currency.HKD

    @property
    def request_ids(self) -> tuple[str, ...]:
        return tuple(entry.request_id for entry in self.requests)

    def request(self, request_id: str) -> RequestReport:
        for entry in self.requests:
            if entry.request_id == str(request_id):
                return entry
        available = ", ".join(self.request_ids) or "none"
        raise UnknownRequestError(
            f"Request id {request_id!r} is not present in the shopping report. "
            f"Available request ids: {available}."
        )


class ShoppingReportAdapter:
    """Converts the upstream ``optimal_selection`` report into purchase plans."""

    def __init__(self, catalog: MerchantCatalog | None = None) -> None:
        self._catalog = catalog

    # -- report level ----------------------------------------------------
    def parse(self, raw: Mapping[str, Any]) -> ShoppingReport:
        if not isinstance(raw, Mapping):
            raise ShoppingReportError("The shopping report must be a JSON object.")
        results = raw.get("results", [])
        if results is None:
            results = []
        if not isinstance(results, list):
            raise ShoppingReportError("The shopping report 'results' entry must be a list.")
        requests: list[RequestReport] = []
        for index, result in enumerate(results, start=1):
            if not isinstance(result, Mapping):
                raise ShoppingReportError(f"Report result #{index} must be an object.")
            request_id = result.get("request_id", result.get("requestId"))
            if request_id is None or str(request_id).strip() == "":
                raise ShoppingReportError(f"Report result #{index} is missing a request_id.")
            requests.append(
                RequestReport(
                    request_id=str(request_id),
                    plans=self._plans_from_result(result),
                    request_text=_text(result, ("request",)),
                    currency=_currency(result.get("currency")),
                    cap_enforced=_optional_text(
                        result, ("cap_enforced", "capEnforced")
                    ),
                )
            )
        return ShoppingReport(
            requests=tuple(requests),
            report_type=_optional_text(raw, ("report_type", "reportType")),
            currency=_currency(raw.get("currency")),
        )

    def parse_file(self, path: str | Path) -> ShoppingReport:
        location = Path(path)
        try:
            raw = json.loads(location.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ShoppingReportError(
                f"Could not read the shopping report {location}: {error}"
            ) from error
        return self.parse(raw)

    def plans_for_request(
        self, raw: Mapping[str, Any], request_id: str
    ) -> tuple[PurchasePlan, ...]:
        return self.parse(raw).request(request_id).plans

    # -- request level ---------------------------------------------------
    def _plans_from_result(self, result: Mapping[str, Any]) -> tuple[PurchasePlan, ...]:
        options = result.get("best_options", result.get("bestOptions", []))
        if options is None:
            options = []
        if not isinstance(options, list):
            raise ShoppingReportError("The 'best_options' entry must be a list.")
        ranked: list[tuple[int, Mapping[str, Any]]] = []
        for option in options:
            if not isinstance(option, Mapping):
                continue
            rank = _coerce_rank(option.get("rank"))
            if rank is None:
                continue  # only validly ranked options are considered
            ranked.append((rank, option))
        ranked.sort(key=lambda pair: pair[0])
        selected: list[tuple[int, Mapping[str, Any]]] = []
        seen: set[int] = set()
        for rank, option in ranked:
            if rank in seen:
                continue  # keep the first option for a duplicated rank
            seen.add(rank)
            selected.append((rank, option))
            if len(selected) == MAX_PLANS_PER_REQUEST:
                break
        return tuple(self._plan_from_option(rank, option) for rank, option in selected)

    def _plan_from_option(self, rank: int, option: Mapping[str, Any]) -> PurchasePlan:
        product_id = _optional_text(option, ("product_id", "productId")) or ""
        merchant_id = _optional_text(option, ("merchant_id", "merchantId")) or ""
        merchant_name = _optional_text(option, ("merchant_name", "merchantName"))
        if self._catalog is not None:
            if not merchant_id:
                merchant_id = (
                    self._catalog.merchant_id_for_product(product_id) or ""
                )
            if not merchant_name and merchant_id:
                record = self._catalog.record_for(merchant_id)
                if record is not None:
                    merchant_name = record.merchant_name
        return PurchasePlan(
            rank=rank,
            product_id=product_id,
            product_name=(
                _optional_text(option, ("product_name", "productName")) or product_id
            ),
            merchant_id=merchant_id,
            subtotal=_money(option, ("price", "subtotal")),
            shipping=_money(option, ("shipping_fee", "shippingFee", "shipping")),
            tax=_money(option, ("tax", "tax_fee", "taxFee")),
            total=_money(option, ("total_cost", "totalCost", "total")),
            currency=_currency(option.get("currency")),
            quantity=_quantity(option.get("quantity")),
            brand=_optional_text(option, ("brand",)),
            description=_optional_text(option, ("description",)),
            merchant_name=merchant_name,
            # Merchant risk scores are deliberately never read from the report.
            merchant_credit_score=None,
            buyer_feedback_score=None,
        )


# -- coercion helpers ----------------------------------------------------
def _coerce_rank(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
    return None


def _currency(value: Any) -> Currency:
    if value is None:
        return Currency.HKD
    if isinstance(value, Currency):
        return value
    text = str(value).strip().upper()
    if text == Currency.HKD.value:
        return Currency.HKD
    raise ShoppingReportError(
        f"Unsupported currency {value!r}: the financial firewall only supports HKD."
    )


def _money(option: Mapping[str, Any], keys: Sequence[str]) -> Money:
    for key in keys:
        if key in option and option[key] is not None:
            try:
                return Money.parse(option[key])
            except MoneyError as error:
                raise ShoppingReportError(
                    f"Field {key!r} is not a readable amount: {error}"
                ) from error
    return HKD_ZERO


def _quantity(value: Any) -> int:
    if value is None:
        return 1
    if isinstance(value, bool):
        raise ShoppingReportError("Field 'quantity' must be a whole number.")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    raise ShoppingReportError("Field 'quantity' must be a whole number.")


def _optional_text(option: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        value = option.get(key)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return None


def _text(option: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    return _optional_text(option, keys)
