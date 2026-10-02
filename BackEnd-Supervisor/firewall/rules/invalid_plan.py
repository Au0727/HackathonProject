"""INVALID_PLAN_DATA: structural validation of one plan."""

from __future__ import annotations

from ..models import RuleEvaluation
from ..types import RuleCode, RuleSeverity
from ..validation import invalid_plan_reason
from .base import evaluation

__all__ = ["evaluate_invalid_plan_data"]


def evaluate_invalid_plan_data(problems: tuple[str, ...]) -> RuleEvaluation:
    """Fail closed when a plan is structurally unsound or self-inconsistent."""

    if not problems:
        return evaluation(RuleCode.INVALID_PLAN_DATA, RuleSeverity.HARD_DENY, True)
    return evaluation(
        RuleCode.INVALID_PLAN_DATA,
        RuleSeverity.HARD_DENY,
        False,
        invalid_plan_reason(problems),
        {"problems": list(problems)},
    )
