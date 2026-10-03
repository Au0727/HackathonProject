"""Deterministic merchant safety rating.

    merchantRating = merchantCreditScore * 0.60 + buyerFeedbackScore * 0.40

rounded to two decimal places. No model, no randomness, no web lookup: two
explicit structured scores always produce the same rating.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Union

from .types import RiskLevel

__all__ = [
    "MerchantScoreError",
    "CREDIT_SCORE_WEIGHT",
    "BUYER_FEEDBACK_WEIGHT",
    "RATING_QUANTUM",
    "MERCHANT_RATING_ASK_THRESHOLD",
    "RISK_LEVEL_GOOD_MIN",
    "RISK_LEVEL_FAIR_MIN",
    "RISK_LEVEL_LOW_MIN",
    "SCORE_MIN",
    "SCORE_MAX",
    "to_score",
    "calculate_merchant_rating",
    "risk_level_for",
    "format_score",
]

NumberLike = Union[int, float, str, Decimal]

CREDIT_SCORE_WEIGHT = Decimal("0.60")
BUYER_FEEDBACK_WEIGHT = Decimal("0.40")
RATING_QUANTUM = Decimal("0.01")

#: A rating below this value triggers the ASK merchant-risk warning.
MERCHANT_RATING_ASK_THRESHOLD = Decimal("60")

RISK_LEVEL_GOOD_MIN = Decimal("80")
RISK_LEVEL_FAIR_MIN = Decimal("60")
RISK_LEVEL_LOW_MIN = Decimal("40")

SCORE_MIN = Decimal("0")
SCORE_MAX = Decimal("100")


class MerchantScoreError(ValueError):
    """Raised when a merchant score is missing, malformed or out of range."""


def to_score(value: NumberLike | None, label: str) -> Decimal:
    """Validate and normalise a 0-100 merchant score."""

    if value is None:
        raise MerchantScoreError(f"{label} is missing.")
    if isinstance(value, bool):
        raise MerchantScoreError(f"{label} must be a number between 0 and 100.")
    if isinstance(value, Decimal):
        score = value
    elif isinstance(value, int):
        score = Decimal(value)
    elif isinstance(value, float):
        score = Decimal(repr(value))
    elif isinstance(value, str):
        try:
            score = Decimal(value.strip())
        except Exception as error:  # noqa: BLE001 - normalised into a domain error
            raise MerchantScoreError(
                f"{label} must be a number between 0 and 100."
            ) from error
    else:
        raise MerchantScoreError(f"{label} must be a number between 0 and 100.")
    if not score.is_finite() or score < SCORE_MIN or score > SCORE_MAX:
        raise MerchantScoreError(
            f"{label} must be between 0 and 100, received {value!r}."
        )
    return score


def calculate_merchant_rating(credit_score: NumberLike, buyer_feedback_score: NumberLike) -> Decimal:
    """Return the rating rounded to two decimal places (ROUND_HALF_UP)."""

    credit = to_score(credit_score, "Merchant credit score")
    feedback = to_score(buyer_feedback_score, "Buyer feedback score")
    raw = (credit * CREDIT_SCORE_WEIGHT) + (feedback * BUYER_FEEDBACK_WEIGHT)
    return raw.quantize(RATING_QUANTUM, rounding=ROUND_HALF_UP)


def risk_level_for(rating: Decimal) -> RiskLevel:
    """Map a rating onto the fixed band table."""

    if rating >= RISK_LEVEL_GOOD_MIN:
        return RiskLevel.GOOD
    if rating >= RISK_LEVEL_FAIR_MIN:
        return RiskLevel.FAIR
    if rating >= RISK_LEVEL_LOW_MIN:
        return RiskLevel.LOW
    return RiskLevel.VERY_LOW


def format_score(value: Decimal) -> str:
    """Display a score without meaningless trailing zeros (53, 77.6, 82.25)."""

    normalised = value.quantize(RATING_QUANTUM, rounding=ROUND_HALF_UP)
    text = f"{normalised:f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"
