"""Trusted merchant risk data: local JSON catalogue with deterministic lookup.

Scores come from this structured source or from an internal service. They are
never estimated from product descriptions, merchant names or any language model.
A merchant with missing or out-of-range scores simply has no risk data, which
makes its plans un-authorizable rather than approvable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from ..models import MerchantRisk, PurchasePlan
from ..rating import MerchantScoreError, to_score
from ..rules.merchant_risk import build_merchant_risk

__all__ = [
    "MerchantCatalog",
    "MerchantRecord",
    "CatalogMerchantRiskProvider",
    "MerchantCatalogError",
]


class MerchantCatalogError(ValueError):
    """Raised when the merchant catalogue is unreadable or inconsistent."""


@dataclass(frozen=True)
class MerchantRecord:
    merchant_id: str
    merchant_name: str | None = None
    merchant_credit_score: Decimal | None = None
    buyer_feedback_score: Decimal | None = None

    @property
    def has_risk_scores(self) -> bool:
        return (
            self.merchant_credit_score is not None
            and self.buyer_feedback_score is not None
        )


@dataclass(frozen=True, eq=False)
class MerchantCatalog:
    """Merchant records keyed by merchant id, plus product -> merchant mapping."""

    merchants: Mapping[str, MerchantRecord] = field(default_factory=dict)
    product_merchant_ids: Mapping[str, str] = field(default_factory=dict)

    # -- construction ----------------------------------------------------
    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "MerchantCatalog":
        if not isinstance(raw, Mapping):
            raise MerchantCatalogError("The merchant catalogue must be a JSON object.")
        merchants_raw = raw.get("merchants", {}) or {}
        if not isinstance(merchants_raw, Mapping):
            raise MerchantCatalogError(
                "The merchant catalogue 'merchants' entry must be an object."
            )
        merchants: dict[str, MerchantRecord] = {}
        for raw_id, entry in merchants_raw.items():
            merchant_id = str(raw_id)
            if not isinstance(entry, Mapping):
                raise MerchantCatalogError(
                    f"Merchant entry {merchant_id!r} must be an object."
                )
            name = entry.get("merchantName", entry.get("merchant_name"))
            credit = _optional_score(
                entry.get("merchantCreditScore", entry.get("merchant_credit_score")),
                merchant_id,
                "merchantCreditScore",
            )
            feedback = _optional_score(
                entry.get("buyerFeedbackScore", entry.get("buyer_feedback_score")),
                merchant_id,
                "buyerFeedbackScore",
            )
            merchants[merchant_id] = MerchantRecord(
                merchant_id=merchant_id,
                merchant_name=None if name is None else str(name),
                merchant_credit_score=credit,
                buyer_feedback_score=feedback,
            )
        products_raw = raw.get("productMerchants", raw.get("product_merchants", {})) or {}
        if not isinstance(products_raw, Mapping):
            raise MerchantCatalogError(
                "The merchant catalogue 'productMerchants' entry must be an object."
            )
        product_merchant_ids = {
            str(product_id): str(merchant_id)
            for product_id, merchant_id in products_raw.items()
        }
        return cls(merchants=merchants, product_merchant_ids=product_merchant_ids)

    @classmethod
    def load(cls, path: str | Path) -> "MerchantCatalog":
        location = Path(path)
        try:
            raw = json.loads(location.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise MerchantCatalogError(
                f"Could not read the merchant catalogue {location}: {error}"
            ) from error
        return cls.from_dict(raw)

    # -- lookup ----------------------------------------------------------
    def merchant_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.merchants))

    def record_for(self, merchant_id: str) -> MerchantRecord | None:
        return self.merchants.get(merchant_id)

    def merchant_id_for_product(self, product_id: str) -> str | None:
        return self.product_merchant_ids.get(product_id)

    def risk_for(self, merchant_id: str) -> MerchantRisk | None:
        """Return risk data, or ``None`` when it is missing or invalid."""

        record = self.record_for(merchant_id)
        if record is None or not record.has_risk_scores:
            return None
        try:
            return build_merchant_risk(
                record.merchant_id,
                record.merchant_credit_score,
                record.buyer_feedback_score,
            )
        except MerchantScoreError:
            return None


class CatalogMerchantRiskProvider:
    """A :class:`~firewall.models.MerchantRiskProvider` backed by the catalogue."""

    def __init__(self, catalog: MerchantCatalog) -> None:
        self._catalog = catalog

    @property
    def catalog(self) -> MerchantCatalog:
        return self._catalog

    def lookup(self, plan: PurchasePlan) -> MerchantRisk | None:
        merchant_id = plan.merchant_id or self._catalog.merchant_id_for_product(
            plan.product_id
        )
        if not merchant_id:
            return None
        return self._catalog.risk_for(merchant_id)


def _optional_score(value: Any, merchant_id: str, field_name: str) -> Decimal | None:
    if value is None:
        return None
    try:
        return to_score(value, field_name)
    except MerchantScoreError as error:
        raise MerchantCatalogError(
            f"Merchant {merchant_id!r} has an invalid {field_name}: {error}"
        ) from error
