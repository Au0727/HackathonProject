"""English-language rendering of firewall decisions.

Pure formatting: these functions decide nothing and never touch a model. Output
is progressive - the answer first, technical detail second (the "Why?" view).
"""

from __future__ import annotations

from decimal import Decimal

from .models import FirewallDecision, PlanEvaluation, PurchasePlan, UserAuthorization
from .money import Money
from .rating import format_score
from .types import DecisionStatus, RuleCode, TransactionState

__all__ = [
    "render_authorization_summary",
    "render_plan_line",
    "render_ask",
    "render_pending_ask",
    "render_approval",
    "render_deny",
    "render_decision",
    "render_transaction",
]


def render_authorization_summary(
    authorization: UserAuthorization, daily_spent: Money | None = None
) -> str:
    lines = [
        "Your authorization settings",
        f"  Maximum Per Transaction: {authorization.max_per_transaction.format()}",
        f"  Maximum Daily Spend:     {authorization.max_daily_spend.format()}",
        f"  Confirmation Threshold:  {authorization.confirmation_threshold.format()}",
    ]
    if daily_spent is not None:
        lines.append(f"  Spent today so far:      {daily_spent.format()}")
    return "\n".join(lines)


def render_plan_line(plan: PurchasePlan, final_total: Money | None = None) -> str:
    total = plan.total if final_total is None else final_total
    label = f"Plan {plan.rank}: {plan.product_name}"
    if plan.brand:
        label += f" ({plan.brand})"
    return f"{label} - {total.format()}"


def render_ask(evaluation: PlanEvaluation) -> str:
    """The confirmation dialog shown for a plan that needs user input."""

    lines = [
        "Purchase Confirmation Required",
        "",
        render_plan_line(evaluation.plan, evaluation.final_total),
    ]
    merchant_label = evaluation.plan.merchant_name or evaluation.plan.merchant_id
    if merchant_label:
        lines.append(f"Merchant: {merchant_label} ({evaluation.plan.merchant_id})")
    reasons = _ask_reason_lines(evaluation)
    lines.append("")
    plural = "" if len(reasons) == 1 else "s"
    lines.append(
        f"This purchase requires your confirmation for {len(reasons)} reason{plural}:"
    )
    lines.append("")
    for index, reason in enumerate(reasons, start=1):
        lines.append(f"{index}. {reason}")
    lines.append("")
    lines.append("Would you like to continue?")
    lines.append("")
    lines.append("[1] Continue Purchase")
    lines.append("[2] Cancel Purchase")
    if evaluation.allow_blacklist_option:
        lines.append("[3] Continue Purchase and Blacklist Merchant")
    return "\n".join(lines)


def render_pending_ask(decision: FirewallDecision) -> str:
    """Render an ASK decision returned without an interactive session."""

    lines = [
        "Confirmation Required",
        f"Plan rank: {decision.evaluated_plan_rank}",
        f"Reason: {decision.reason}",
    ]
    if decision.merchant_risk is not None:
        lines.append(
            f"Merchant Safety Rating: "
            f"{format_score(decision.merchant_risk.merchant_rating)} / 100"
        )
    if decision.ask_reasons:
        lines.append(
            "Confirmation reasons: "
            + ", ".join(reason.value for reason in decision.ask_reasons)
        )
    if decision.ask_id is not None:
        lines.append(f"Confirmation request id: {decision.ask_id}")
    lines.append("This purchase is not authorized until the user confirms.")
    return "\n".join(lines)


def render_approval(decision: FirewallDecision) -> str:
    plan = decision.approved_plan
    lines = ["Purchase Approved", ""]
    if plan is not None:
        product = plan.product_name
        if plan.brand:
            product += f" ({plan.brand})"
        lines.extend(
            [
                f"Product: {product}",
                f"Merchant: {plan.merchant_name or plan.merchant_id}",
                f"Quantity: {plan.quantity}",
                "",
                f"Subtotal: {plan.subtotal.format()}",
                f"Shipping: {plan.shipping.format()}",
                f"Tax: {plan.tax.format()}",
                f"Total: {plan.total.format()}",
            ]
        )
        if decision.merchant_risk is not None:
            lines.extend(
                [
                    "",
                    "Merchant Safety Rating: "
                    f"{format_score(decision.merchant_risk.merchant_rating)} / 100",
                ]
            )
        lines.extend(
            [
                "",
                f"Authorization: {decision.status.value}",
                f"Evaluated plan: rank {plan.rank}",
                f"Reason: {decision.reason}",
            ]
        )
    return "\n".join(lines)


def render_deny(decision: FirewallDecision) -> str:
    lines = [decision.reason, "", f"Authorization: {decision.status.value}"]
    if decision.failed_rules:
        lines.append(
            "Failed rules: " + ", ".join(code.value for code in decision.failed_rules)
        )
    if decision.plan_results:
        lines.extend(["", "Why?"])
        for summary in decision.plan_results:
            lines.append(f"  Plan {summary.rank}: {summary.status.value} - {summary.reason}")
            if summary.failed_rules:
                lines.append(
                    "    Failed rules: "
                    + ", ".join(code.value for code in summary.failed_rules)
                )
            if summary.ask_reasons and not summary.failed_rules:
                # Only plans the user was actually asked about were not hard-denied.
                lines.append(
                    "    Confirmation required: "
                    + ", ".join(reason.value for reason in summary.ask_reasons)
                )
    return "\n".join(lines)


def render_decision(decision: FirewallDecision) -> str:
    if decision.status is DecisionStatus.APPROVE:
        return render_approval(decision)
    if decision.status is DecisionStatus.ASK:
        return render_pending_ask(decision)
    return render_deny(decision)


def render_transaction(states: list[tuple[TransactionState, str]]) -> str:
    lines = ["SIMULATED PAYMENT"]
    for state, note in states:
        lines.append(f"  {state.value}: {note}")
    lines.append("No real money was transferred. This is a simulated commerce flow.")
    return "\n".join(lines)


# -- internals -----------------------------------------------------------
def _ask_reason_lines(evaluation: PlanEvaluation) -> list[str]:
    lines: list[str] = []
    for entry in evaluation.evaluations:
        if entry.passed:
            continue
        if entry.code is RuleCode.MERCHANT_RATING_LOW:
            rating = _score(entry.metadata.get("merchantRating"))
            credit = _score(entry.metadata.get("merchantCreditScore"))
            feedback = _score(entry.metadata.get("buyerFeedbackScore"))
            lines.append(
                "Merchant Safety Rating is low: "
                f"{format_score(rating)} / 100 "
                f"(merchant credit score {format_score(credit)} / 100, "
                f"buyer feedback score {format_score(feedback)} / 100)"
            )
        elif entry.code is RuleCode.CONFIRMATION_THRESHOLD_EXCEEDED:
            total = entry.metadata.get("finalTotal", "")
            threshold = entry.metadata.get("confirmationThreshold", "")
            lines.append(
                "Purchase amount exceeds your confirmation threshold: "
                f"{total} > {threshold}"
            )
    return lines


def _score(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except ArithmeticError:
        return Decimal("0")
