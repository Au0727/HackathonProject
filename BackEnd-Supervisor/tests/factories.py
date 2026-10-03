"""Builders shared by the test-suite.

Defaults are deliberately authorizable (merchant rating 85.2 = GOOD) so that a
test only sees a failure when it asks for one.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable, Mapping

from firewall import (
    AuthorizationContext,
    Currency,
    FirewallDecision,
    MerchantRisk,
    Money,
    PurchasePlan,
    UserAuthorization,
    UserConfirmationResponse,
)
from firewall.rating import calculate_merchant_rating, risk_level_for

DEFAULT_CREDIT_SCORE = "90"
DEFAULT_FEEDBACK_SCORE = "78"


def _score_or_raw(value: Any) -> Any:
    """Convert a score to Decimal, or keep malformed input as-is for rejection."""

    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError):
        return value


def money(value: Any) -> Money:
    return Money.parse(value)


def auth(
    max_per_transaction: Any = "300.00",
    max_daily_spend: Any = "1000.00",
    confirmation_threshold: Any = "200.00",
) -> UserAuthorization:
    return UserAuthorization(
        max_per_transaction=Money.parse(max_per_transaction),
        max_daily_spend=Money.parse(max_daily_spend),
        confirmation_threshold=Money.parse(confirmation_threshold),
    )


def plan(
    rank: int = 1,
    *,
    total: Any = "100.00",
    shipping: Any = "0.00",
    tax: Any = "0.00",
    subtotal: Any | None = None,
    product_id: str = "WM-001",
    product_name: str = "Sample Product",
    merchant_id: str = "merchant-001",
    merchant_name: str | None = "Sample Merchant",
    quantity: int = 1,
    credit: Any | None = DEFAULT_CREDIT_SCORE,
    feedback: Any | None = DEFAULT_FEEDBACK_SCORE,
    currency: Currency = Currency.HKD,
    description: str | None = None,
    brand: str | None = None,
) -> PurchasePlan:
    total_money = Money.parse(total)
    shipping_money = Money.parse(shipping)
    tax_money = Money.parse(tax)
    subtotal_money = (
        total_money - shipping_money - tax_money
        if subtotal is None
        else Money.parse(subtotal)
    )
    return PurchasePlan(
        rank=rank,
        product_id=product_id,
        product_name=product_name,
        merchant_id=merchant_id,
        subtotal=subtotal_money,
        shipping=shipping_money,
        tax=tax_money,
        total=total_money,
        currency=currency,
        quantity=quantity,
        brand=brand,
        description=description,
        merchant_name=merchant_name,
        merchant_credit_score=_score_or_raw(credit),
        buyer_feedback_score=_score_or_raw(feedback),
    )


def risk(
    merchant_id: str = "merchant-001", credit: Any = DEFAULT_CREDIT_SCORE, feedback: Any = DEFAULT_FEEDBACK_SCORE
) -> MerchantRisk:
    credit_score = Decimal(str(credit))
    feedback_score = Decimal(str(feedback))
    rating = calculate_merchant_rating(credit_score, feedback_score)
    return MerchantRisk(
        merchant_id=merchant_id,
        merchant_credit_score=credit_score,
        buyer_feedback_score=feedback_score,
        merchant_rating=rating,
        risk_level=risk_level_for(rating),
    )


def context(
    daily_spent: Any = "0.00",
    *,
    authorization: UserAuthorization | None = None,
    blacklist: Iterable[str] = (),
    request_id: str | None = "REQ-TEST",
    session_id: str | None = "test-session",
    provider: Any | None = None,
) -> AuthorizationContext:
    return AuthorizationContext(
        authorization=authorization if authorization is not None else auth(),
        daily_spent=Money.parse(daily_spent),
        blacklisted_merchants=tuple(blacklist),
        session_id=session_id,
        request_id=request_id,
        merchant_risk_provider=provider,
    )


class StaticRiskProvider:
    """A trusted-but-static provider used to model a merchant catalogue."""

    def __init__(self, risks: Mapping[str, MerchantRisk]) -> None:
        self._risks = dict(risks)

    def lookup(self, plan: PurchasePlan) -> MerchantRisk | None:
        return self._risks.get(plan.merchant_id)


def responses(
    by_rank: Mapping[int, UserConfirmationResponse] | None = None,
    default: UserConfirmationResponse | None = None,
):
    """A confirmation provider keyed by plan rank."""

    mapping = dict(by_rank or {})
    fallback = default if default is not None else UserConfirmationResponse(approved=True)

    def provider(evaluation) -> UserConfirmationResponse:
        return mapping.get(evaluation.plan.rank, fallback)

    return provider


CONFIRM = UserConfirmationResponse(approved=True)
DECLINE = UserConfirmationResponse(approved=False)
CONFIRM_AND_BLACKLIST = UserConfirmationResponse(approved=True, blacklist_merchant=True)


def audit_ranks(engine) -> list[int]:
    """Plan ranks that produced PLAN_EVALUATION audit events, in order."""

    return [
        event.plan_rank
        for event in engine.audit_service.events
        if event.event_type == "PLAN_EVALUATION"
    ]


def summary(decision: FirewallDecision, rank: int = 1):
    """Fetch one per-plan summary from a decision."""

    for entry in decision.plan_results:
        if entry.rank == rank:
            return entry
    raise AssertionError(f"No plan summary for rank {rank} in {decision.to_dict()}")
