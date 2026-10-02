"""Every user-facing string, in English.

The specification requires an English-only system and explicit, human-readable
decision reasons. Keeping the wording in one module means no language model is
ever in the wording path, and reviewers can check the whole vocabulary of the
product in one file.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from .money import Money
from .rating import format_score

__all__ = [
    "APPROVE_REASON",
    "APPROVE_AFTER_CONFIRMATION_REASON",
    "FINAL_DENY_REASON",
    "FINAL_DENY_NO_PLANS_REASON",
    "USER_DECLINED_REASON",
    "BLACKLISTED_REASON",
    "MERCHANT_RISK_UNAVAILABLE_REASON",
    "BLACKLIST_ACTION_REASON",
    "max_per_transaction_reason",
    "max_daily_spend_reason",
    "merchant_rating_low_reason",
    "confirmation_threshold_reason",
    "invalid_plan_data_reason",
]

APPROVE_REASON = "Purchase plan satisfies all authorization rules."
APPROVE_AFTER_CONFIRMATION_REASON = (
    "The user confirmed this purchase, so the purchase plan is approved."
)
FINAL_DENY_REASON = (
    "No suitable purchase plan is available under your current authorization settings."
)
FINAL_DENY_NO_PLANS_REASON = "No suitable purchase plan is available."
USER_DECLINED_REASON = "The user declined to confirm this purchase plan."
BLACKLISTED_REASON = "This merchant is on your blacklist."
MERCHANT_RISK_UNAVAILABLE_REASON = (
    "Merchant risk data is unavailable, so this purchase plan cannot be authorized."
)
BLACKLIST_ACTION_REASON = (
    "The user chose to continue with this purchase and blacklist the merchant "
    "for future purchases."
)


def max_per_transaction_reason(final_total: Money, limit: Money) -> str:
    return (
        f"Final transaction total {final_total.format()} exceeds the maximum "
        f"per-transaction limit of {limit.format()}."
    )


def max_daily_spend_reason(projected: Money, limit: Money) -> str:
    return (
        f"This purchase would increase today's spending to {projected.format()}, "
        f"which exceeds the daily spending limit of {limit.format()}."
    )


def merchant_rating_low_reason(
    rating: Decimal, credit_score: Decimal, buyer_feedback_score: Decimal
) -> str:
    return (
        f"Merchant Safety Rating: {format_score(rating)} / 100. This merchant has a "
        f"low safety rating based on its merchant credit score "
        f"({format_score(credit_score)} / 100) and buyer feedback score "
        f"({format_score(buyer_feedback_score)} / 100)."
    )


def confirmation_threshold_reason(final_total: Money, threshold: Money) -> str:
    return (
        f"This purchase is {final_total.format()}, which exceeds your confirmation "
        f"threshold of {threshold.format()}. Would you like to continue?"
    )


def invalid_plan_data_reason(problems: Iterable[str]) -> str:
    return (
        "This purchase plan contains invalid data and cannot be authorized. "
        + " ".join(problems)
    )
