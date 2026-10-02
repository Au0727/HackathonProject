"""Shared helper for building :class:`RuleEvaluation` objects."""

from __future__ import annotations

from typing import Any, Mapping

from ..models import RuleEvaluation
from ..types import RuleCode, RuleSeverity

__all__ = ["evaluation"]


def evaluation(
    code: RuleCode,
    severity: RuleSeverity,
    passed: bool,
    reason: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> RuleEvaluation:
    """Build one rule result. A passing rule carries no failure reason."""

    return RuleEvaluation(
        code=code,
        passed=passed,
        severity=severity,
        reason="" if passed else reason,
        metadata=dict(metadata or {}),
    )
