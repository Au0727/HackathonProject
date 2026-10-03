"""MAX_PER_TRANSACTION: finalTotal <= maxPerTransaction.

The comparison uses the final transaction total (subtotal + shipping + tax) in
exact minor units. Exactly at the limit passes; one cent above denies.
"""

from __future__ import annotations

from ..messages import max_per_transaction_reason
from ..models import PurchasePlan, RuleEvaluation, UserAuthorization
from ..money import Money
from ..types import RuleCode, RuleSeverity
from .base import evaluation

__all__ = ["evaluate_max_per_transaction"]


def evaluate_max_per_transaction(
    plan: PurchasePlan, final_total: Money, authorization: UserAuthorization
) -> RuleEvaluation:
    limit = authorization.max_per_transaction
    passed = final_total <= limit
    return evaluation(
        RuleCode.MAX_PER_TRANSACTION,
        RuleSeverity.HARD_DENY,
        passed,
        max_per_transaction_reason(final_total, limit),
        {"finalTotal": final_total.format(), "maxPerTransaction": limit.format()},
    )
