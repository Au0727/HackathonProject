"""The single-plan evaluation pipeline.

    validate -> final total -> blacklist -> per transaction -> daily spend
             -> merchant risk -> confirmation threshold -> decision

Hard failures take precedence over ASK conditions, and every rule in the
pipeline is evaluated so the audit record shows the complete picture.
"""

from __future__ import annotations

from dataclasses import dataclass

from .messages import APPROVE_REASON
from .models import (
    AskReason,
    AuthorizationContext,
    MerchantRisk,
    PlanEvaluation,
    PurchasePlan,
    RuleEvaluation,
)
from .money import HKD_ZERO, Money, MoneyError
from .rules import (
    evaluate_confirmation_threshold,
    evaluate_invalid_plan_data,
    evaluate_max_daily_spend,
    evaluate_max_per_transaction,
    evaluate_merchant_blacklist,
    evaluate_merchant_risk,
    resolve_merchant_risk,
)
from .types import DecisionStatus, RuleCode, RuleSeverity
from .validation import validate_plan

__all__ = [
    "RulePipelineResult",
    "RuleEngine",
    "decide_status",
    "describe_decision",
    "to_plan_evaluation",
]


@dataclass(frozen=True)
class RulePipelineResult:
    """Outcome of running every rule against one plan."""

    final_total: Money
    evaluations: tuple[RuleEvaluation, ...]
    merchant_risk: MerchantRisk | None = None
    plan_problems: tuple[str, ...] = ()

    @property
    def status(self) -> DecisionStatus:
        return decide_status(self.evaluations)

    @property
    def failed_rules(self) -> tuple[RuleCode, ...]:
        return tuple(
            entry.code
            for entry in self.evaluations
            if not entry.passed and entry.severity is RuleSeverity.HARD_DENY
        )

    @property
    def ask_reasons(self) -> tuple[AskReason, ...]:
        return tuple(
            AskReason(entry.code.value)
            for entry in self.evaluations
            if not entry.passed and entry.severity is RuleSeverity.ASK
        )


def decide_status(evaluations: tuple[RuleEvaluation, ...]) -> DecisionStatus:
    """Any hard failure denies; otherwise any ASK trigger asks; otherwise approve."""

    if any(
        not entry.passed and entry.severity is RuleSeverity.HARD_DENY
        for entry in evaluations
    ):
        return DecisionStatus.DENY
    if any(
        not entry.passed and entry.severity is RuleSeverity.ASK for entry in evaluations
    ):
        return DecisionStatus.ASK
    return DecisionStatus.APPROVE


def describe_decision(
    evaluations: tuple[RuleEvaluation, ...], status: DecisionStatus
) -> str:
    """Human-readable, data-derived reason (never generated after the fact)."""

    if status is DecisionStatus.APPROVE:
        return APPROVE_REASON
    severity = (
        RuleSeverity.HARD_DENY if status is DecisionStatus.DENY else RuleSeverity.ASK
    )
    reasons = [
        entry.reason
        for entry in evaluations
        if not entry.passed and entry.severity is severity and entry.reason
    ]
    return " ".join(reasons)


def to_plan_evaluation(plan: PurchasePlan, pipeline: RulePipelineResult) -> PlanEvaluation:
    status = pipeline.status
    return PlanEvaluation(
        plan=plan,
        status=status,
        final_total=pipeline.final_total,
        evaluations=pipeline.evaluations,
        reason=describe_decision(pipeline.evaluations, status),
        merchant_risk=pipeline.merchant_risk,
    )


def _final_transaction_total(plan: PurchasePlan) -> Money:
    """subtotal + shipping + tax, falling back safely for malformed plans."""

    try:
        return plan.calculated_total()
    except (MoneyError, AttributeError):
        total = getattr(plan, "total", None)
        return total if isinstance(total, Money) else HKD_ZERO


class RuleEngine:
    """Runs the fixed rule pipeline for a single plan."""

    def evaluate_plan(
        self,
        plan: PurchasePlan,
        context: AuthorizationContext,
        blacklisted_merchants: tuple[str, ...] | None = None,
    ) -> RulePipelineResult:
        problems = validate_plan(plan)
        final_total = _final_transaction_total(plan)
        if problems:
            # Structurally invalid data: nothing downstream may be trusted, so the
            # plan is denied on data grounds alone.
            return RulePipelineResult(
                final_total=final_total,
                evaluations=(evaluate_invalid_plan_data(problems),),
                merchant_risk=None,
                plan_problems=problems,
            )
        blacklist = (
            tuple(blacklisted_merchants)
            if blacklisted_merchants is not None
            else tuple(context.blacklisted_merchants)
        )
        evaluations: list[RuleEvaluation] = [
            evaluate_merchant_blacklist(plan, blacklist),
            evaluate_max_per_transaction(plan, final_total, context.authorization),
            evaluate_max_daily_spend(plan, final_total, context),
        ]
        merchant_risk = resolve_merchant_risk(plan, context.merchant_risk_provider)
        evaluations.append(evaluate_merchant_risk(plan, merchant_risk))
        evaluations.append(
            evaluate_confirmation_threshold(plan, final_total, context.authorization)
        )
        return RulePipelineResult(
            final_total=final_total,
            evaluations=tuple(evaluations),
            merchant_risk=merchant_risk,
        )
