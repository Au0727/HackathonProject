"""Input validation.

Fail-closed by design: malformed, missing or inconsistent data makes a plan
un-authorizable. Missing security-relevant data never silently becomes approval.
"""

from __future__ import annotations

from .messages import invalid_plan_data_reason
from .models import PurchasePlan, UserAuthorization
from .money import Money, MoneyError
from .rating import MerchantScoreError, to_score
from .types import Currency

__all__ = [
    "AuthorizationValidationError",
    "PlanSetError",
    "validate_user_authorization",
    "validate_daily_spent",
    "validate_plan",
    "validate_plan_set",
    "invalid_plan_reason",
]


class AuthorizationValidationError(ValueError):
    """Raised when the user's authorization settings are invalid."""


class PlanSetError(ValueError):
    """Raised when the supplied plans cannot form a priority-ordered set."""


def validate_user_authorization(authorization: UserAuthorization) -> None:
    """Raise :class:`AuthorizationValidationError` if settings are invalid."""

    problems: list[str] = []
    if not isinstance(authorization, UserAuthorization):
        raise AuthorizationValidationError("User authorization settings are missing.")
    if authorization.currency is not Currency.HKD:
        problems.append(f"Currency must be HKD, received {authorization.currency.value}.")
    if authorization.max_per_transaction.minor_units <= 0:
        problems.append("Maximum per transaction must be greater than HKD 0.00.")
    if authorization.max_daily_spend.minor_units <= 0:
        problems.append("Maximum daily spend must be greater than HKD 0.00.")
    if authorization.confirmation_threshold.minor_units < 0:
        problems.append("Confirmation threshold cannot be negative.")
    if authorization.confirmation_threshold > authorization.max_per_transaction:
        problems.append(
            "Confirmation threshold cannot exceed the maximum per-transaction limit."
        )
    if problems:
        raise AuthorizationValidationError(" ".join(problems))


def validate_daily_spent(daily_spent: Money) -> None:
    """Raise :class:`AuthorizationValidationError` if daily spending is invalid."""

    if not isinstance(daily_spent, Money):
        raise AuthorizationValidationError("Daily spending state is missing.")
    if daily_spent.currency is not Currency.HKD:
        raise AuthorizationValidationError("Daily spending state must be in HKD.")
    if daily_spent.minor_units < 0:
        raise AuthorizationValidationError("Daily spending state cannot be negative.")


def validate_plan(plan: PurchasePlan) -> tuple[str, ...]:
    """Return the list of reasons this plan is invalid (empty when it is valid)."""

    problems: list[str] = []
    if not isinstance(plan, PurchasePlan):
        return ("Purchase plan is missing or is not a structured purchase plan.",)
    if plan.rank not in (1, 2, 3):
        problems.append(f"Plan rank must be 1, 2 or 3, received {plan.rank!r}.")
    if isinstance(plan.quantity, bool) or not isinstance(plan.quantity, int) or plan.quantity < 1:
        problems.append("Quantity must be an integer of at least 1.")
    if plan.currency is not Currency.HKD:
        problems.append(f"Plan currency must be HKD, received {plan.currency.value}.")
    if not plan.product_id:
        problems.append("Plan is missing a product id.")
    if not plan.merchant_id:
        problems.append("Plan is missing a merchant id.")
    for label, value in (
        ("subtotal", plan.subtotal),
        ("shipping", plan.shipping),
        ("tax", plan.tax),
        ("total", plan.total),
    ):
        if not isinstance(value, Money):
            problems.append(f"Plan {label} is not a monetary amount.")
        elif value.currency is not Currency.HKD:
            problems.append(f"Plan {label} must be in HKD.")
        elif value.is_negative():
            problems.append(f"Plan {label} cannot be negative.")
    if not problems:
        try:
            calculated = plan.calculated_total()
        except MoneyError as error:
            problems.append(str(error))
        else:
            if calculated != plan.total:
                problems.append(
                    f"Plan total {plan.total.format()} does not match "
                    f"subtotal + shipping + tax ({calculated.format()})."
                )
    for label, score in (
        ("Merchant credit score", plan.merchant_credit_score),
        ("Buyer feedback score", plan.buyer_feedback_score),
    ):
        if score is None:
            continue
        try:
            to_score(score, label)
        except MerchantScoreError as error:
            problems.append(str(error))
    return tuple(problems)


def invalid_plan_reason(problems: tuple[str, ...]) -> str:
    return invalid_plan_data_reason(problems)


def validate_plan_set(plans: tuple[PurchasePlan, ...]) -> None:
    """Raise :class:`PlanSetError` when plan ranks are ambiguous."""

    seen: dict[int, int] = {}
    for index, plan in enumerate(plans):
        if not isinstance(plan, PurchasePlan):
            raise PlanSetError(
                f"Purchase plan entry #{index + 1} is not a structured purchase plan."
            )
        rank = plan.rank
        if rank not in (1, 2, 3):
            continue  # reported per plan as INVALID_PLAN_DATA
        if rank in seen:
            raise PlanSetError(
                f"Two purchase plans share rank {rank}; the priority order is ambiguous."
            )
        seen[rank] = index
