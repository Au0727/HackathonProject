"""Fixed enumerations and policy constants for the Financial Firewall.

Every value in this module is fixed by the specification. Nothing here is
produced by a language model at runtime, and nothing here may be influenced by
the shopping agent or by free-form product text.
"""

from __future__ import annotations

from enum import Enum

__all__ = [
    "Currency",
    "DecisionStatus",
    "RuleSeverity",
    "RiskLevel",
    "AskReason",
    "RuleCode",
    "RULE_PIPELINE_ORDER",
    "HARD_DENY_RULES",
    "ASK_RULES",
    "rule_sort_key",
    "TransactionState",
    "UserConfirmation",
]


class Currency(str, Enum):
    """Currencies the firewall understands."""

    HKD = "HKD"


class DecisionStatus(str, Enum):
    """The three external firewall decision statuses."""

    APPROVE = "APPROVE"
    ASK = "ASK"
    DENY = "DENY"


class RuleSeverity(str, Enum):
    """How a failed rule affects a plan."""

    HARD_DENY = "HARD_DENY"
    ASK = "ASK"


class RiskLevel(str, Enum):
    """Merchant safety rating bands."""

    GOOD = "GOOD"
    FAIR = "FAIR"
    LOW = "LOW"
    VERY_LOW = "VERY_LOW"


class AskReason(str, Enum):
    """Reasons a plan needs explicit user confirmation."""

    MERCHANT_RATING_LOW = "MERCHANT_RATING_LOW"
    CONFIRMATION_THRESHOLD_EXCEEDED = "CONFIRMATION_THRESHOLD_EXCEEDED"


class RuleCode(str, Enum):
    """Stable rule identifiers used in decisions, audits and tests."""

    INVALID_PLAN_DATA = "INVALID_PLAN_DATA"
    MERCHANT_BLACKLISTED = "MERCHANT_BLACKLISTED"
    MAX_PER_TRANSACTION = "MAX_PER_TRANSACTION"
    MAX_DAILY_SPEND = "MAX_DAILY_SPEND"
    MERCHANT_RISK_DATA_UNAVAILABLE = "MERCHANT_RISK_DATA_UNAVAILABLE"
    MERCHANT_RATING_LOW = "MERCHANT_RATING_LOW"
    CONFIRMATION_THRESHOLD_EXCEEDED = "CONFIRMATION_THRESHOLD_EXCEEDED"


#: Evaluation order of the single-plan pipeline.
RULE_PIPELINE_ORDER: tuple[RuleCode, ...] = (
    RuleCode.INVALID_PLAN_DATA,
    RuleCode.MERCHANT_BLACKLISTED,
    RuleCode.MAX_PER_TRANSACTION,
    RuleCode.MAX_DAILY_SPEND,
    RuleCode.MERCHANT_RISK_DATA_UNAVAILABLE,
    RuleCode.MERCHANT_RATING_LOW,
    RuleCode.CONFIRMATION_THRESHOLD_EXCEEDED,
)

#: Rules that hard-deny a plan when they fail.
HARD_DENY_RULES: tuple[RuleCode, ...] = (
    RuleCode.INVALID_PLAN_DATA,
    RuleCode.MERCHANT_BLACKLISTED,
    RuleCode.MAX_PER_TRANSACTION,
    RuleCode.MAX_DAILY_SPEND,
    RuleCode.MERCHANT_RISK_DATA_UNAVAILABLE,
)

#: Rules that put a plan into the ASK state when they fail.
ASK_RULES: tuple[RuleCode, ...] = (
    RuleCode.MERCHANT_RATING_LOW,
    RuleCode.CONFIRMATION_THRESHOLD_EXCEEDED,
)

_RULE_ORDER_INDEX: dict[RuleCode, int] = {
    code: index for index, code in enumerate(RULE_PIPELINE_ORDER)
}


def rule_sort_key(code: RuleCode) -> int:
    """Deterministic ordering helper for rule codes."""

    return _RULE_ORDER_INDEX.get(code, len(RULE_PIPELINE_ORDER))


class TransactionState(str, Enum):
    """Transaction lifecycle (simulated payment only)."""

    PROPOSED = "PROPOSED"
    AUTHORIZED = "AUTHORIZED"
    CHECKOUT = "CHECKOUT"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    COMPLETED = "COMPLETED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class UserConfirmation(str, Enum):
    """Recorded user response to an ASK decision."""

    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
