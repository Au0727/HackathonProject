"""MERCHANT_RATING_LOW / MERCHANT_RISK_DATA_UNAVAILABLE.

Missing risk data is a hard denial (never a silent approval). A low rating is an
ASK, never an automatic denial.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Union

from ..messages import MERCHANT_RISK_UNAVAILABLE_REASON, merchant_rating_low_reason
from ..models import MerchantRisk, MerchantRiskProvider, PurchasePlan, RuleEvaluation
from ..rating import (
    MERCHANT_RATING_ASK_THRESHOLD,
    MerchantScoreError,
    calculate_merchant_rating,
    risk_level_for,
    to_score,
)
from ..types import RuleCode, RuleSeverity
from .base import evaluation

__all__ = ["build_merchant_risk", "resolve_merchant_risk", "evaluate_merchant_risk"]

NumberLike = Union[int, float, str, Decimal]


def build_merchant_risk(
    merchant_id: str, merchant_credit_score: NumberLike, buyer_feedback_score: NumberLike
) -> MerchantRisk:
    """Build validated risk data from two explicit 0-100 scores."""

    credit = to_score(merchant_credit_score, "Merchant credit score")
    feedback = to_score(buyer_feedback_score, "Buyer feedback score")
    rating = calculate_merchant_rating(credit, feedback)
    return MerchantRisk(
        merchant_id=merchant_id,
        merchant_credit_score=credit,
        buyer_feedback_score=feedback,
        merchant_rating=rating,
        risk_level=risk_level_for(rating),
    )


def resolve_merchant_risk(
    plan: PurchasePlan, provider: MerchantRiskProvider | None = None
) -> MerchantRisk | None:
    """Resolve trusted risk data, or ``None`` when it is unavailable.

    Inline plan scores are used only when an internal caller supplies them
    explicitly. The shopping-report adapter never populates them, because report
    content is untrusted input.
    """

    if plan.merchant_credit_score is not None and plan.buyer_feedback_score is not None:
        try:
            return build_merchant_risk(
                plan.merchant_id, plan.merchant_credit_score, plan.buyer_feedback_score
            )
        except MerchantScoreError:
            return None
    if provider is None:
        return None
    try:
        risk = provider.lookup(plan)
    except Exception:  # noqa: BLE001 - a failing trusted source means "unavailable"
        return None
    if not isinstance(risk, MerchantRisk):
        return None
    return risk


def evaluate_merchant_risk(plan: PurchasePlan, risk: MerchantRisk | None) -> RuleEvaluation:
    if risk is None:
        return evaluation(
            RuleCode.MERCHANT_RISK_DATA_UNAVAILABLE,
            RuleSeverity.HARD_DENY,
            False,
            MERCHANT_RISK_UNAVAILABLE_REASON,
            {"merchantId": plan.merchant_id},
        )
    passed = risk.merchant_rating >= MERCHANT_RATING_ASK_THRESHOLD
    return evaluation(
        RuleCode.MERCHANT_RATING_LOW,
        RuleSeverity.ASK,
        passed,
        merchant_rating_low_reason(
            risk.merchant_rating, risk.merchant_credit_score, risk.buyer_feedback_score
        ),
        {
            "merchantId": risk.merchant_id,
            "merchantCreditScore": str(risk.merchant_credit_score),
            "buyerFeedbackScore": str(risk.buyer_feedback_score),
            "merchantRating": str(risk.merchant_rating),
            "riskLevel": risk.risk_level.value,
            "askThreshold": str(MERCHANT_RATING_ASK_THRESHOLD),
        },
    )
