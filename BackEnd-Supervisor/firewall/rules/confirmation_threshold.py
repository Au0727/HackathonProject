"""CONFIRMATION_THRESHOLD_EXCEEDED: finalTotal > confirmationThreshold.

Exactly at the threshold needs no confirmation; one cent above triggers ASK.
"""

from __future__ import annotations

from ..messages import confirmation_threshold_reason
from ..models import PurchasePlan, RuleEvaluation, UserAuthorization
from ..money import Money
from ..types import RuleCode, RuleSeverity
from .base import evaluation

__all__ = ["evaluate_confirmation_threshold"]


def evaluate_confirmation_threshold(
    plan: PurchasePlan, final_total: Money, authorization: UserAuthorization
) -> RuleEvaluation:
    threshold = authorization.confirmation_threshold
    passed = final_total <= threshold
    return evaluation(
        RuleCode.CONFIRMATION_THRESHOLD_EXCEEDED,
        RuleSeverity.ASK,
        passed,
        confirmation_threshold_reason(final_total, threshold),
        {
            "finalTotal": final_total.format(),
            "confirmationThreshold": threshold.format(),
        },
    )
