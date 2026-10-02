"""Core immutable data models shared by every firewall component.

The shopping agent produces :class:`PurchasePlan` objects. The firewall produces
:class:`PlanEvaluation` objects and, at the top level, a
:class:`FirewallDecision`. Everything here is plain structured data: no field is
derived from free-form language at authorization time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping, Protocol, Sequence

from .money import HKD_ZERO, Money
from .types import (
    AskReason,
    Currency,
    DecisionStatus,
    RiskLevel,
    RuleCode,
    RuleSeverity,
    UserConfirmation,
    rule_sort_key,
)

__all__ = [
    "PurchasePlan",
    "MerchantRisk",
    "MerchantRiskProvider",
    "UserAuthorization",
    "AuthorizationContext",
    "RuleEvaluation",
    "PlanEvaluation",
    "PlanDecisionSummary",
    "UserConfirmationResponse",
    "FirewallDecision",
    "FirewallAuditEvent",
]


def _as_float(value: Decimal | int | float | None) -> float | None:
    return None if value is None else float(value)


@dataclass(frozen=True)
class PurchasePlan:
    """One already-ranked purchase plan proposed by the shopping agent.

    ``rank`` is agent-provided priority and is never re-derived or re-sorted by
    value. ``merchant_credit_score`` / ``buyer_feedback_score`` are trusted
    structured values supplied by an internal service or merchant catalog; the
    shopping-report adapter never reads them from report text.
    """

    rank: int
    product_id: str
    product_name: str
    merchant_id: str
    subtotal: Money
    shipping: Money = HKD_ZERO
    tax: Money = HKD_ZERO
    total: Money = HKD_ZERO
    currency: Currency = Currency.HKD
    quantity: int = 1
    brand: str | None = None
    description: str | None = None
    merchant_name: str | None = None
    merchant_credit_score: Decimal | None = None
    buyer_feedback_score: Decimal | None = None

    def calculated_total(self) -> Money:
        """Exact ``subtotal + shipping + tax`` in minor units."""

        return self.subtotal + self.shipping + self.tax

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "productId": self.product_id,
            "productName": self.product_name,
            "brand": self.brand,
            "description": self.description,
            "merchantId": self.merchant_id,
            "merchantName": self.merchant_name,
            "subtotal": _as_float(self.subtotal.amount),
            "shipping": _as_float(self.shipping.amount),
            "tax": _as_float(self.tax.amount),
            "total": _as_float(self.total.amount),
            "currency": self.currency.value,
            "quantity": self.quantity,
            "merchantCreditScore": _as_float(self.merchant_credit_score),
            "buyerFeedbackScore": _as_float(self.buyer_feedback_score),
        }


@dataclass(frozen=True)
class MerchantRisk:
    """Trusted merchant risk data for one merchant."""

    merchant_id: str
    merchant_credit_score: Decimal
    buyer_feedback_score: Decimal
    merchant_rating: Decimal
    risk_level: RiskLevel

    def to_dict(self) -> dict[str, Any]:
        return {
            "merchantId": self.merchant_id,
            "merchantCreditScore": _as_float(self.merchant_credit_score),
            "buyerFeedbackScore": _as_float(self.buyer_feedback_score),
            "merchantRating": _as_float(self.merchant_rating),
            "riskLevel": self.risk_level.value,
        }


class MerchantRiskProvider(Protocol):
    """Trusted, structured source of merchant risk data (catalog, DB, service)."""

    def lookup(self, plan: PurchasePlan) -> MerchantRisk | None:
        """Return risk data, or ``None`` when it is unavailable."""


@dataclass(frozen=True)
class UserAuthorization:
    """The user's explicit authorization policy. Only the user sets these."""

    max_per_transaction: Money
    max_daily_spend: Money
    confirmation_threshold: Money
    currency: Currency = Currency.HKD


@dataclass(frozen=True)
class AuthorizationContext:
    """Everything the firewall needs besides the candidate plans."""

    authorization: UserAuthorization
    daily_spent: Money
    blacklisted_merchants: tuple[str, ...] = ()
    session_id: str | None = None
    request_id: str | None = None
    merchant_risk_provider: MerchantRiskProvider | None = field(
        default=None, compare=False, repr=False
    )


@dataclass(frozen=True)
class RuleEvaluation:
    """Result of one deterministic rule evaluator."""

    code: RuleCode
    passed: bool
    severity: RuleSeverity
    reason: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)


@dataclass(frozen=True)
class PlanEvaluation:
    """Full, auditable evaluation of a single purchase plan."""

    plan: PurchasePlan
    status: DecisionStatus
    final_total: Money
    evaluations: tuple[RuleEvaluation, ...]
    reason: str
    merchant_risk: MerchantRisk | None = None

    @property
    def evaluated_rules(self) -> tuple[RuleCode, ...]:
        return tuple(evaluation.code for evaluation in self.evaluations)

    @property
    def passed_rules(self) -> tuple[RuleCode, ...]:
        return tuple(evaluation.code for evaluation in self.evaluations if evaluation.passed)

    @property
    def failed_rules(self) -> tuple[RuleCode, ...]:
        return tuple(
            evaluation.code
            for evaluation in self.evaluations
            if not evaluation.passed and evaluation.severity is RuleSeverity.HARD_DENY
        )

    @property
    def ask_reasons(self) -> tuple[AskReason, ...]:
        reasons: list[AskReason] = []
        for evaluation in self.evaluations:
            if evaluation.passed or evaluation.severity is not RuleSeverity.ASK:
                continue
            reasons.append(AskReason(evaluation.code.value))
        return tuple(reasons)

    @property
    def allow_blacklist_option(self) -> bool:
        return (
            self.status is DecisionStatus.ASK
            and AskReason.MERCHANT_RATING_LOW in self.ask_reasons
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status.value,
            "evaluatedPlanRank": self.plan.rank,
            "finalTotal": _as_float(self.final_total.amount),
            "currency": self.final_total.currency.value,
            "reason": self.reason,
            "evaluatedRules": [code.value for code in self.evaluated_rules],
            "passedRules": [code.value for code in self.passed_rules],
            "failedRules": [code.value for code in self.failed_rules],
            "askReasons": [reason.value for reason in self.ask_reasons],
        }
        if self.merchant_risk is not None:
            payload["merchantRisk"] = self.merchant_risk.to_dict()
        return payload


@dataclass(frozen=True)
class PlanDecisionSummary:
    """Compact per-plan outcome, kept for the final DENY and the audit view."""

    rank: int
    status: DecisionStatus
    failed_rules: tuple[RuleCode, ...] = ()
    ask_reasons: tuple[AskReason, ...] = ()
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "status": self.status.value,
            "failedRules": [code.value for code in self.failed_rules],
            "askReasons": [reason.value for reason in self.ask_reasons],
            "reason": self.reason,
        }


@dataclass(frozen=True)
class UserConfirmationResponse:
    """The user's answer to an ASK dialog."""

    approved: bool
    blacklist_merchant: bool = False


@dataclass(frozen=True)
class FirewallDecision:
    """Top-level decision returned to the caller."""

    status: DecisionStatus
    reason: str
    approved_plan: PurchasePlan | None = None
    evaluated_plan_rank: int | None = None
    ask_id: str | None = None
    ask_reasons: tuple[AskReason, ...] = ()
    merchant_risk: MerchantRisk | None = None
    allow_blacklist_option: bool = False
    failed_rules: tuple[RuleCode, ...] = ()
    plan_results: tuple[PlanDecisionSummary, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status.value, "reason": self.reason}
        if self.status is DecisionStatus.APPROVE and self.approved_plan is not None:
            payload["evaluatedPlanRank"] = self.approved_plan.rank
            payload["approvedPlan"] = self.approved_plan.to_dict()
            if self.merchant_risk is not None:
                payload["merchantRisk"] = self.merchant_risk.to_dict()
            return payload
        if self.status is DecisionStatus.ASK:
            payload["evaluatedPlanRank"] = self.evaluated_plan_rank
            payload["askReasons"] = [reason.value for reason in self.ask_reasons]
            if self.ask_id is not None:
                payload["askId"] = self.ask_id
            if self.merchant_risk is not None:
                payload["merchantRisk"] = self.merchant_risk.to_dict()
            payload["allowBlacklistOption"] = self.allow_blacklist_option
            return payload
        payload["evaluatedPlanRank"] = self.evaluated_plan_rank
        payload["failedRules"] = [code.value for code in self.failed_rules]
        payload["planResults"] = [summary.to_dict() for summary in self.plan_results]
        return payload


@dataclass(frozen=True)
class FirewallAuditEvent:
    """One audit record per plan evaluation (and per blacklist action)."""

    id: str
    timestamp: str
    event_type: str
    plan_rank: int
    product_id: str
    merchant_id: str
    final_total: Money
    daily_spent_before: Money
    projected_daily_spent: Money
    evaluated_rules: tuple[RuleCode, ...]
    passed_rules: tuple[RuleCode, ...]
    failed_rules: tuple[RuleCode, ...]
    decision: DecisionStatus
    reason: str
    session_id: str | None = None
    request_id: str | None = None
    merchant_credit_score: Decimal | None = None
    buyer_feedback_score: Decimal | None = None
    merchant_rating: Decimal | None = None
    risk_level: RiskLevel | None = None
    user_confirmation: UserConfirmation | None = None
    merchant_blacklisted: bool | None = None
    ask_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "eventType": self.event_type,
            "sessionId": self.session_id,
            "requestId": self.request_id,
            "planRank": self.plan_rank,
            "productId": self.product_id,
            "merchantId": self.merchant_id,
            "finalTotal": _as_float(self.final_total.amount),
            "currency": self.final_total.currency.value,
            "dailySpentBefore": _as_float(self.daily_spent_before.amount),
            "projectedDailySpent": _as_float(self.projected_daily_spent.amount),
            "evaluatedRules": [code.value for code in self.evaluated_rules],
            "passedRules": [code.value for code in self.passed_rules],
            "failedRules": [code.value for code in self.failed_rules],
            "merchantCreditScore": _as_float(self.merchant_credit_score),
            "buyerFeedbackScore": _as_float(self.buyer_feedback_score),
            "merchantRating": _as_float(self.merchant_rating),
            "riskLevel": None if self.risk_level is None else self.risk_level.value,
            "decision": self.decision.value,
            "reason": self.reason,
            "userConfirmation": (
                None if self.user_confirmation is None else self.user_confirmation.value
            ),
            "merchantBlacklisted": self.merchant_blacklisted,
            "askId": self.ask_id,
        }


def sorted_rule_codes(codes: Sequence[RuleCode]) -> tuple[RuleCode, ...]:
    """De-duplicate rule codes and return them in pipeline order."""

    unique = {code for code in codes}
    return tuple(sorted(unique, key=rule_sort_key))
