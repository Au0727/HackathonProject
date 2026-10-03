"""The three-plan priority engine and the public firewall service.

Plans are evaluated strictly in agent-provided rank order (1 -> 2 -> 3). The
engine never re-ranks plans, never compares prices to pick a "better" plan, and
never consults a language model: given the same authorization settings, spending
state, plans and merchant data it always produces the same decision.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from .audit import ASK_RESOLUTION_EVENT, AuditService
from .blacklist import BlacklistStore
from .messages import (
    APPROVE_AFTER_CONFIRMATION_REASON,
    APPROVE_REASON,
    FINAL_DENY_NO_PLANS_REASON,
    FINAL_DENY_REASON,
    USER_DECLINED_REASON,
)
from .models import (
    AuthorizationContext,
    FirewallDecision,
    PlanDecisionSummary,
    PlanEvaluation,
    PurchasePlan,
    UserConfirmationResponse,
    sorted_rule_codes,
)
from .rule_engine import RuleEngine, to_plan_evaluation
from .types import DecisionStatus, UserConfirmation
from .validation import (
    PlanSetError,
    validate_daily_spent,
    validate_plan_set,
    validate_user_authorization,
)

__all__ = [
    "AuthorizationEngine",
    "FinancialFirewall",
    "FirewallRequest",
    "ConfirmationProvider",
    "UnknownAskError",
    "PlanSetError",
]

ConfirmationProvider = Callable[[PlanEvaluation], UserConfirmationResponse]


class UnknownAskError(KeyError):
    """Raised when resolve_ask() is called with an unknown confirmation id."""


@dataclass(frozen=True)
class _PendingAsk:
    ask_id: str
    evaluation: PlanEvaluation
    plans: tuple[PurchasePlan, ...]
    next_index: int
    context: AuthorizationContext
    summaries: tuple[PlanDecisionSummary, ...]


@dataclass(frozen=True)
class _ConfirmationOutcome:
    approved: bool
    merchant_blacklisted: bool = False


@dataclass(frozen=True)
class FirewallRequest:
    """Everything needed to evaluate one shopping request's purchase plans."""

    plans: tuple[PurchasePlan, ...]
    context: AuthorizationContext
    confirmation_provider: ConfirmationProvider | None = None


class AuthorizationEngine:
    """Deterministic priority engine over up to three ranked purchase plans."""

    def __init__(
        self,
        rule_engine: RuleEngine | None = None,
        audit_service: AuditService | None = None,
        blacklist_store: BlacklistStore | None = None,
    ) -> None:
        self._rule_engine = rule_engine if rule_engine is not None else RuleEngine()
        self._audit = audit_service if audit_service is not None else AuditService()
        self._blacklist = (
            blacklist_store if blacklist_store is not None else BlacklistStore()
        )
        self._pending_asks: dict[str, _PendingAsk] = {}
        self._ask_sequence = 0

    # -- accessors -------------------------------------------------------
    @property
    def audit_service(self) -> AuditService:
        return self._audit

    @property
    def blacklist(self) -> BlacklistStore:
        return self._blacklist

    @property
    def pending_ask_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._pending_asks))

    # -- single plan -----------------------------------------------------
    def evaluate_plan(
        self, plan: PurchasePlan, context: AuthorizationContext
    ) -> PlanEvaluation:
        """Evaluate one plan against every rule (no ranking, no selection)."""

        pipeline = self._rule_engine.evaluate_plan(
            plan, context, self._effective_blacklist(context)
        )
        return to_plan_evaluation(plan, pipeline)

    def _effective_blacklist(self, context: AuthorizationContext) -> tuple[str, ...]:
        merged = set(context.blacklisted_merchants) | set(self._blacklist.merchants)
        return tuple(sorted(merged))

    # -- priority engine -------------------------------------------------
    @staticmethod
    def order_plans(plans: Iterable[PurchasePlan]) -> tuple[PurchasePlan, ...]:
        """Order plans by their supplied rank only, validating uniqueness."""

        ordered = tuple(plans)
        validate_plan_set(ordered)
        return tuple(sorted(ordered, key=lambda plan: plan.rank))

    def evaluate_plans(
        self,
        plans: Iterable[PurchasePlan],
        context: AuthorizationContext,
        confirmation_provider: ConfirmationProvider | None = None,
    ) -> FirewallDecision:
        """Synchronous priority engine.

        With no confirmation provider, the first ASK suspends the engine and
        returns an ASK decision carrying an ``ask_id`` for :meth:`resolve_ask`.
        """

        ordered = self.order_plans(plans)
        if not ordered:
            return FirewallDecision(
                status=DecisionStatus.DENY, reason=FINAL_DENY_NO_PLANS_REASON
            )
        summaries: list[PlanDecisionSummary] = []
        runner = self._drive(ordered, 0, context, summaries)
        supplied: Any = None
        while True:
            try:
                evaluation = runner.send(supplied)
            except StopIteration as stop:
                return stop.value
            if confirmation_provider is None:
                supplied = None
                continue
            response = confirmation_provider(evaluation)
            if inspect.isawaitable(response):
                raise TypeError(
                    "The confirmation provider returned an awaitable. Use "
                    "evaluate_plans_async() for asynchronous providers."
                )
            supplied = response

    async def evaluate_plans_async(
        self,
        plans: Iterable[PurchasePlan],
        context: AuthorizationContext,
        confirmation_provider: ConfirmationProvider | None = None,
    ) -> FirewallDecision:
        """Asynchronous priority engine; the provider may be sync or async."""

        ordered = self.order_plans(plans)
        if not ordered:
            return FirewallDecision(
                status=DecisionStatus.DENY, reason=FINAL_DENY_NO_PLANS_REASON
            )
        summaries: list[PlanDecisionSummary] = []
        runner = self._drive(ordered, 0, context, summaries)
        supplied: Any = None
        while True:
            try:
                evaluation = runner.send(supplied)
            except StopIteration as stop:
                return stop.value
            if confirmation_provider is None:
                supplied = None
                continue
            response = confirmation_provider(evaluation)
            if inspect.isawaitable(response):
                response = await response
            supplied = response

    def resolve_ask(
        self, ask_id: str, response: UserConfirmationResponse
    ) -> FirewallDecision:
        """Continue a suspended ASK with the user's answer."""

        pending = self._pending_asks.pop(ask_id, None)
        if pending is None:
            raise UnknownAskError(
                f"Unknown or already resolved confirmation request: {ask_id!r}."
            )
        if not isinstance(response, UserConfirmationResponse):
            raise TypeError("A confirmation response must be a UserConfirmationResponse.")
        summaries = list(pending.summaries)
        evaluation = pending.evaluation
        domain_plan = evaluation.plan
        outcome = self._apply_confirmation(evaluation, pending.context, response, ask_id)
        if outcome.approved:
            return FirewallDecision(
                status=DecisionStatus.APPROVE,
                reason=APPROVE_AFTER_CONFIRMATION_REASON,
                approved_plan=domain_plan,
                evaluated_plan_rank=domain_plan.rank,
                merchant_risk=evaluation.merchant_risk,
                plan_results=tuple(summaries),
            )
        summaries.append(self._declined_summary(evaluation))
        return self.run_remaining(
            pending.plans, pending.next_index, pending.context, summaries
        )

    def run_remaining(
        self,
        plans: tuple[PurchasePlan, ...],
        start_index: int,
        context: AuthorizationContext,
        summaries: list[PlanDecisionSummary] | None = None,
    ) -> FirewallDecision:
        """Continue evaluation from ``start_index``, suspending on the next ASK."""

        collected = [] if summaries is None else summaries
        runner = self._drive(tuple(plans), start_index, context, collected)
        supplied: Any = None
        while True:
            try:
                runner.send(supplied)
            except StopIteration as stop:
                return stop.value
            supplied = None

    # -- the generator that drives one plan at a time ---------------------
    def _drive(
        self,
        plans: tuple[PurchasePlan, ...],
        start_index: int,
        context: AuthorizationContext,
        summaries: list[PlanDecisionSummary],
    ):
        """Yield each ASK evaluation; send a response back, or None to suspend.

        The generator's return value is the resulting :class:`FirewallDecision`.
        """

        index = start_index
        while index < len(plans):
            plan = plans[index]
            evaluation = self.evaluate_plan(plan, context)
            if evaluation.status is DecisionStatus.DENY:
                self._audit.record(evaluation, context, decision=DecisionStatus.DENY)
                summaries.append(self._summarise(evaluation))
                index += 1
                continue
            if evaluation.status is DecisionStatus.APPROVE:
                self._audit.record(evaluation, context, decision=DecisionStatus.APPROVE)
                return FirewallDecision(
                    status=DecisionStatus.APPROVE,
                    reason=APPROVE_REASON,
                    approved_plan=plan,
                    evaluated_plan_rank=plan.rank,
                    merchant_risk=evaluation.merchant_risk,
                    plan_results=tuple(summaries),
                )
            # ASK: user input is required before this plan can be authorized.
            self._audit.record(evaluation, context, decision=DecisionStatus.ASK)
            response = yield evaluation
            if response is None:
                ask_id = self._next_ask_id()
                self._pending_asks[ask_id] = _PendingAsk(
                    ask_id=ask_id,
                    evaluation=evaluation,
                    plans=tuple(plans),
                    next_index=index + 1,
                    context=context,
                    summaries=tuple(summaries),
                )
                return FirewallDecision(
                    status=DecisionStatus.ASK,
                    reason=evaluation.reason,
                    evaluated_plan_rank=plan.rank,
                    ask_id=ask_id,
                    ask_reasons=evaluation.ask_reasons,
                    merchant_risk=evaluation.merchant_risk,
                    allow_blacklist_option=evaluation.allow_blacklist_option,
                    plan_results=tuple(summaries),
                )
            outcome = self._apply_confirmation(evaluation, context, response)
            if outcome.approved:
                return FirewallDecision(
                    status=DecisionStatus.APPROVE,
                    reason=APPROVE_AFTER_CONFIRMATION_REASON,
                    approved_plan=plan,
                    evaluated_plan_rank=plan.rank,
                    merchant_risk=evaluation.merchant_risk,
                    plan_results=tuple(summaries),
                )
            summaries.append(self._declined_summary(evaluation))
            index += 1
        return self._final_deny(summaries)

    # -- helpers ---------------------------------------------------------
    def _apply_confirmation(
        self,
        evaluation: PlanEvaluation,
        context: AuthorizationContext,
        response: UserConfirmationResponse,
        ask_id: str | None = None,
    ) -> _ConfirmationOutcome:
        if not isinstance(response, UserConfirmationResponse):
            raise TypeError("A confirmation response must be a UserConfirmationResponse.")
        plan = evaluation.plan
        if response.approved:
            blacklisted = False
            if response.blacklist_merchant:
                blacklisted = self._blacklist.add(plan.merchant_id)
                self._audit.record_blacklist_action(evaluation, context, ask_id=ask_id)
            self._audit.record(
                evaluation,
                context,
                decision=DecisionStatus.APPROVE,
                reason=APPROVE_AFTER_CONFIRMATION_REASON,
                user_confirmation=UserConfirmation.CONFIRMED,
                merchant_blacklisted=blacklisted,
                ask_id=ask_id,
                event_type=ASK_RESOLUTION_EVENT,
            )
            return _ConfirmationOutcome(True, blacklisted)
        self._audit.record(
            evaluation,
            context,
            decision=DecisionStatus.DENY,
            reason=USER_DECLINED_REASON,
            user_confirmation=UserConfirmation.DECLINED,
            ask_id=ask_id,
            event_type=ASK_RESOLUTION_EVENT,
        )
        return _ConfirmationOutcome(False)

    @staticmethod
    def _summarise(evaluation: PlanEvaluation) -> PlanDecisionSummary:
        return PlanDecisionSummary(
            rank=evaluation.plan.rank,
            status=evaluation.status,
            failed_rules=evaluation.failed_rules,
            ask_reasons=evaluation.ask_reasons,
            reason=evaluation.reason,
        )

    @staticmethod
    def _declined_summary(evaluation: PlanEvaluation) -> PlanDecisionSummary:
        """A plan the user declined is treated as rejected for this request."""

        return PlanDecisionSummary(
            rank=evaluation.plan.rank,
            status=DecisionStatus.DENY,
            failed_rules=(),
            ask_reasons=evaluation.ask_reasons,
            reason=USER_DECLINED_REASON,
        )

    @staticmethod
    def _final_deny(summaries: list[PlanDecisionSummary]) -> FirewallDecision:
        if not summaries:
            return FirewallDecision(
                status=DecisionStatus.DENY, reason=FINAL_DENY_NO_PLANS_REASON
            )
        failed = sorted_rule_codes(
            [code for summary in summaries for code in summary.failed_rules]
        )
        return FirewallDecision(
            status=DecisionStatus.DENY,
            reason=FINAL_DENY_REASON,
            failed_rules=failed,
            plan_results=tuple(summaries),
        )

    def _next_ask_id(self) -> str:
        self._ask_sequence += 1
        return f"ask-{self._ask_sequence:04d}"


class FinancialFirewall:
    """Public service boundary: ``evaluate_purchase_plans(request)``."""

    def __init__(self, engine: AuthorizationEngine | None = None) -> None:
        self._engine = engine if engine is not None else AuthorizationEngine()

    @property
    def engine(self) -> AuthorizationEngine:
        return self._engine

    @property
    def audit_service(self) -> AuditService:
        return self._engine.audit_service

    @property
    def blacklist(self) -> BlacklistStore:
        return self._engine.blacklist

    def evaluate_purchase_plans(self, request: FirewallRequest) -> FirewallDecision:
        self._validate_request(request)
        return self._engine.evaluate_plans(
            request.plans, request.context, request.confirmation_provider
        )

    async def evaluate_purchase_plans_async(
        self, request: FirewallRequest
    ) -> FirewallDecision:
        self._validate_request(request)
        return await self._engine.evaluate_plans_async(
            request.plans, request.context, request.confirmation_provider
        )

    def resolve_ask(
        self, ask_id: str, response: UserConfirmationResponse
    ) -> FirewallDecision:
        return self._engine.resolve_ask(ask_id, response)

    @staticmethod
    def _validate_request(request: FirewallRequest) -> None:
        if not isinstance(request, FirewallRequest):
            raise TypeError("evaluate_purchase_plans() requires a FirewallRequest.")
        validate_user_authorization(request.context.authorization)
        validate_daily_spent(request.context.daily_spent)
