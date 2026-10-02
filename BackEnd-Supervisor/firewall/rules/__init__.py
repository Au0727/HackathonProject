"""Independent, deterministic rule evaluators.

Each rule lives in its own module with a pure function. The rule engine combines
their results; no rule inspects the product catalogue, no rule re-ranks plans and
no rule consults a language model.
"""

from .base import evaluation
from .confirmation_threshold import evaluate_confirmation_threshold
from .invalid_plan import evaluate_invalid_plan_data
from .max_daily_spend import evaluate_max_daily_spend
from .max_per_transaction import evaluate_max_per_transaction
from .merchant_blacklist import evaluate_merchant_blacklist
from .merchant_risk import (
    build_merchant_risk,
    evaluate_merchant_risk,
    resolve_merchant_risk,
)

__all__ = [
    "evaluation",
    "evaluate_invalid_plan_data",
    "evaluate_merchant_blacklist",
    "evaluate_max_per_transaction",
    "evaluate_max_daily_spend",
    "evaluate_merchant_risk",
    "resolve_merchant_risk",
    "build_merchant_risk",
]
