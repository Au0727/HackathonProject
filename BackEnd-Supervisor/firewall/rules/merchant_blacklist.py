"""MERCHANT_BLACKLISTED: hard denial for user-blacklisted merchants.

Matching is exact string equality on ``merchantId``. There is deliberately no
normalisation, no case folding and no fuzzy matching.
"""

from __future__ import annotations

from typing import Iterable

from ..messages import BLACKLISTED_REASON
from ..models import PurchasePlan, RuleEvaluation
from ..types import RuleCode, RuleSeverity
from .base import evaluation

__all__ = ["evaluate_merchant_blacklist"]


def evaluate_merchant_blacklist(
    plan: PurchasePlan, blacklisted_merchants: Iterable[str]
) -> RuleEvaluation:
    blacklist = {merchant_id for merchant_id in blacklisted_merchants if merchant_id}
    blacklisted = plan.merchant_id in blacklist
    return evaluation(
        RuleCode.MERCHANT_BLACKLISTED,
        RuleSeverity.HARD_DENY,
        not blacklisted,
        BLACKLISTED_REASON,
        {
            "merchantId": plan.merchant_id,
            "blacklistedMerchants": sorted(blacklist),
        },
    )
