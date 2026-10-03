"""MAX_DAILY_SPEND: dailySpent + finalTotal <= maxDailySpend.

Exactly at the limit passes; one cent above denies. An ASK decision never counts
as spending: ``dailySpent`` only reflects committed spending supplied by the
caller.
"""

from __future__ import annotations

from ..messages import max_daily_spend_reason
from ..models import AuthorizationContext, PurchasePlan, RuleEvaluation
from ..money import Money
from ..types import RuleCode, RuleSeverity
from .base import evaluation

__all__ = ["evaluate_max_daily_spend"]


def evaluate_max_daily_spend(
    plan: PurchasePlan, final_total: Money, context: AuthorizationContext
) -> RuleEvaluation:
    limit = context.authorization.max_daily_spend
    projected = context.daily_spent + final_total
    passed = projected <= limit
    return evaluation(
        RuleCode.MAX_DAILY_SPEND,
        RuleSeverity.HARD_DENY,
        passed,
        max_daily_spend_reason(projected, limit),
        {
            "dailySpent": context.daily_spent.format(),
            "projectedDailySpent": projected.format(),
            "maxDailySpend": limit.format(),
        },
    )
