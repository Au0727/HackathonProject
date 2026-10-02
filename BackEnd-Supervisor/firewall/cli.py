"""Command line interface for the Financial Firewall (English only).

    python -m firewall configure   # set the three authorization values
    python -m firewall evaluate    # evaluate one request_id from a report
    python -m firewall demo        # run the built-in sample scenarios

Exit codes for ``evaluate``: 0 = APPROVE, 1 = DENY, 2 = invalid input,
3 = ASK still awaiting the user's decision.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

from . import ui
from .adapters import (
    CatalogMerchantRiskProvider,
    MerchantCatalog,
    MerchantCatalogError,
    ShoppingReportAdapter,
    ShoppingReportError,
    UnknownRequestError,
)
from .audit import AuditService
from .authorization_engine import AuthorizationEngine, FinancialFirewall, FirewallRequest
from .blacklist import BlacklistError, BlacklistStore
from .models import (
    AuthorizationContext,
    FirewallDecision,
    PlanEvaluation,
    PurchasePlan,
    UserAuthorization,
    UserConfirmationResponse,
)
from .money import Money, MoneyError
from .transaction import Transaction
from .types import Currency, DecisionStatus
from .validation import AuthorizationValidationError, validate_user_authorization

DEFAULT_STATE_FILE = "firewall_state.json"
DEFAULT_BLACKLIST_FILE = "blacklist.json"
DEFAULT_CATALOG_FILE = "samples/merchant_catalog.json"

EXIT_APPROVE = 0
EXIT_DENY = 1
EXIT_INVALID = 2
EXIT_PENDING_ASK = 3


class CliError(RuntimeError):
    """Raised when the command cannot continue without an interactive console."""


def _is_interactive() -> bool:
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (ValueError, OSError):  # pragma: no cover - platform dependent
        return False


# ----------------------------------------------------------------------
# shared helpers
# ----------------------------------------------------------------------
def _parse_amount(value: Any, label: str) -> Money:
    text = str(value).strip()
    if text.upper().startswith(Currency.HKD.value):
        text = text[3:].strip()
    try:
        return Money.parse(text)
    except MoneyError as error:
        raise AuthorizationValidationError(f"{label} is not a valid amount: {error}") from error


def _authorization(max_per_transaction: Any, max_daily_spend: Any, confirmation_threshold: Any) -> UserAuthorization:
    authorization = UserAuthorization(
        max_per_transaction=_parse_amount(max_per_transaction, "Maximum per transaction"),
        max_daily_spend=_parse_amount(max_daily_spend, "Maximum daily spend"),
        confirmation_threshold=_parse_amount(confirmation_threshold, "Confirmation threshold"),
    )
    validate_user_authorization(authorization)
    return authorization


def _resolve_authorization(args: argparse.Namespace, saved: dict[str, Any]) -> UserAuthorization:
    """Use flags, then saved settings, then ask the user - prompting only if needed."""

    def resolve(flag_value: Any, saved_key: str, question: str, default: str) -> Any:
        if flag_value not in (None, ""):
            return flag_value
        stored = saved.get(saved_key)
        if stored not in (None, ""):
            return stored
        return _prompt(question, default)

    return _authorization(
        resolve(
            args.max_per_transaction,
            "maxPerTransaction",
            "What is the maximum amount the AI may spend in a single transaction?",
            "300",
        ),
        resolve(
            args.max_daily_spend,
            "maxDailySpend",
            "What is the maximum amount the AI may spend in one day?",
            "1000",
        ),
        resolve(
            args.confirmation_threshold,
            "confirmationThreshold",
            "Above what amount should the AI ask for your confirmation?",
            "200",
        ),
    )


def _load_state(path: str | Path) -> dict[str, Any]:
    location = Path(path)
    if not location.exists():
        return {}
    try:
        raw = json.loads(location.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuthorizationValidationError(
            f"Could not read the saved authorization settings {location}: {error}"
        ) from error
    return raw if isinstance(raw, dict) else {}


def _save_state(path: str | Path, authorization: UserAuthorization, daily_spent: Money) -> Path:
    location = Path(path)
    payload = {
        "currency": authorization.currency.value,
        "maxPerTransaction": float(authorization.max_per_transaction.amount),
        "maxDailySpend": float(authorization.max_daily_spend.amount),
        "confirmationThreshold": float(authorization.confirmation_threshold.amount),
        "dailySpent": float(daily_spent.amount),
    }
    location.parent.mkdir(parents=True, exist_ok=True)
    location.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return location


def _prompt(question: str, default: str) -> str:
    if not _is_interactive():
        raise CliError(
            f"{question} No interactive console is available. Pass the value as a "
            "command line flag, or run 'python -m firewall configure' first."
        )
    banner = f"{question}\n[HKD {default}] > "
    try:
        answer = input(banner).strip()
    except EOFError:
        answer = ""
    return answer or default


def _interactive_confirmation(evaluation: PlanEvaluation) -> UserConfirmationResponse:
    """English ASK dialog used by the CLI."""

    if not _is_interactive():
        raise CliError(
            "This purchase needs your confirmation, but no interactive console is "
            "available. Re-run with --non-interactive to receive the ASK decision "
            "and resolve it yourself."
        )
    print()
    print(ui.render_ask(evaluation))
    print()
    allowed = {"1", "2"} | ({"3"} if evaluation.allow_blacklist_option else set())
    while True:
        try:
            answer = input("Your choice: ").strip()
        except EOFError:
            answer = ""
        if answer in allowed:
            break
        print("Please enter one of: " + ", ".join(sorted(allowed)))
    if answer == "3":
        return UserConfirmationResponse(approved=True, blacklist_merchant=True)
    if answer == "1":
        return UserConfirmationResponse(approved=True)
    return UserConfirmationResponse(approved=False)


def _run_simulated_payment(decision: FirewallDecision, transaction_id: str) -> str:
    """Drive the simulated transaction state machine after an APPROVE."""

    if decision.approved_plan is None:
        raise ValueError("A transaction needs an approved plan.")
    transaction = Transaction(transaction_id, decision.approved_plan)
    transaction.authorize(decision)
    transaction.begin_checkout()
    transaction.begin_payment()
    transaction.complete()
    return ui.render_transaction(transaction.history)


def _load_catalog(path: str | Path | None) -> MerchantCatalog | None:
    if path is None:
        return None
    location = Path(path)
    if not location.exists():
        return None
    return MerchantCatalog.load(location)


# ----------------------------------------------------------------------
# configure
# ----------------------------------------------------------------------
def _cmd_configure(args: argparse.Namespace) -> int:
    saved = _load_state(args.state_file)
    print("Set your financial authorization policy. All amounts are in HKD.")
    max_per_transaction = args.max_per_transaction or _prompt(
        "What is the maximum amount the AI may spend in a single transaction?",
        str(saved.get("maxPerTransaction", "300")),
    )
    max_daily_spend = args.max_daily_spend or _prompt(
        "What is the maximum amount the AI may spend in one day?",
        str(saved.get("maxDailySpend", "1000")),
    )
    confirmation_threshold = args.confirmation_threshold or _prompt(
        "Above what amount should the AI ask for your confirmation?",
        str(saved.get("confirmationThreshold", "200")),
    )
    daily_spent = args.daily_spent if args.daily_spent is not None else saved.get("dailySpent", "0")
    authorization = _authorization(max_per_transaction, max_daily_spend, confirmation_threshold)
    daily_spent_money = _parse_amount(daily_spent, "Daily spending so far")
    location = _save_state(args.state_file, authorization, daily_spent_money)
    print()
    print(ui.render_authorization_summary(authorization, daily_spent_money))
    print()
    print(f"Saved to {location}.")
    return EXIT_APPROVE


# ----------------------------------------------------------------------
# evaluate
# ----------------------------------------------------------------------
def _cmd_evaluate(args: argparse.Namespace) -> int:
    saved = _load_state(args.state_file)
    authorization = _resolve_authorization(args, saved)
    daily_spent = _parse_amount(
        args.daily_spent if args.daily_spent is not None else saved.get("dailySpent", "0"),
        "Daily spending so far",
    )
    catalog = _load_catalog(args.catalog)
    adapter = ShoppingReportAdapter(catalog)
    report = adapter.parse_file(args.report)
    request_id = args.request_id
    if request_id is None:
        if len(report.requests) != 1:
            raise ShoppingReportError(
                "This report contains several shopping requests; please pass "
                "--request-id. Available request ids: "
                + ", ".join(report.request_ids)
            )
        request_id = report.requests[0].request_id
    request_report = report.request(request_id)
    plans = request_report.plans
    if not plans:
        print("No candidate purchase plans are available for this request.")
        print("No suitable purchase plan is available.")
        return EXIT_DENY

    blacklist = BlacklistStore(path=args.blacklist_file)
    audit = AuditService(path=args.audit_log)
    engine = AuthorizationEngine(audit_service=audit, blacklist_store=blacklist)
    firewall = FinancialFirewall(engine)
    context = AuthorizationContext(
        authorization=authorization,
        daily_spent=daily_spent,
        blacklisted_merchants=blacklist.merchants,
        session_id=report.report_type,
        request_id=request_report.request_id,
        merchant_risk_provider=(
            CatalogMerchantRiskProvider(catalog) if catalog is not None else None
        ),
    )
    print(ui.render_authorization_summary(authorization, daily_spent))
    print()
    print(f"Request: {request_report.request_id}")
    if request_report.request_text:
        print(f"  {request_report.request_text}")
    for plan in plans:
        print("  " + ui.render_plan_line(plan))
    print()

    provider = None if args.non_interactive else _interactive_confirmation
    decision = firewall.evaluate_purchase_plans(
        FirewallRequest(plans=plans, context=context, confirmation_provider=provider)
    )
    print(ui.render_decision(decision))
    print()
    if args.json:
        print(json.dumps(decision.to_dict(), indent=2))
    if decision.status is DecisionStatus.APPROVE:
        print()
        print(_run_simulated_payment(decision, f"TXN-{request_report.request_id}"))
    if args.show_audit:
        print()
        print("Audit trail")
        print(audit.to_jsonl().rstrip())
    if not args.quiet:
        print()
        print(f"Audit events recorded: {len(audit)} (reasons above come from recorded rule data).")
    if decision.status is DecisionStatus.APPROVE:
        return EXIT_APPROVE
    if decision.status is DecisionStatus.ASK:
        return EXIT_PENDING_ASK
    return EXIT_DENY


# ----------------------------------------------------------------------
# demo
# ----------------------------------------------------------------------
def _make_plan(
    rank: int,
    product_id: str,
    product_name: str,
    merchant_id: str,
    total: str,
    *,
    credit: Any | None = None,
    feedback: Any | None = None,
    shipping: str = "0.00",
    merchant_name: str | None = None,
    brand: str | None = None,
) -> PurchasePlan:
    total_money = Money.parse(total)
    shipping_money = Money.parse(shipping)
    return PurchasePlan(
        rank=rank,
        product_id=product_id,
        product_name=product_name,
        merchant_id=merchant_id,
        subtotal=total_money - shipping_money,
        shipping=shipping_money,
        tax=Money.zero(),
        total=total_money,
        currency=Currency.HKD,
        quantity=1,
        brand=brand,
        merchant_name=merchant_name,
        merchant_credit_score=None if credit is None else Decimal(str(credit)),
        buyer_feedback_score=None if feedback is None else Decimal(str(feedback)),
    )


def _context(
    authorization: UserAuthorization,
    daily_spent: str,
    *,
    request_id: str | None = None,
    blacklist: Sequence[str] = (),
) -> AuthorizationContext:
    return AuthorizationContext(
        authorization=authorization,
        daily_spent=Money.parse(daily_spent),
        blacklisted_merchants=tuple(blacklist),
        request_id=request_id,
    )


def _print_flow(title: str, decision: FirewallDecision, audit: AuditService) -> None:
    print("-" * 72)
    print(title)
    print("-" * 72)
    print(ui.render_decision(decision))
    if decision.status is DecisionStatus.APPROVE and decision.approved_plan is not None:
        print()
        print(_run_simulated_payment(decision, f"TXN-{audit._sequence:04d}"))  # noqa: SLF001
    print(f"[audit events: {len(audit)}]")
    print()


def _cmd_demo(args: argparse.Namespace) -> int:
    """The four sample flows from the specification, non-interactively."""

    print("Financial Firewall demo - simulated commerce only, no real money moves.")
    print()

    # Flow 1: Plan 1 needs confirmation and the user confirms.
    audit = AuditService(path=args.audit_log)
    engine = AuthorizationEngine(audit_service=audit)
    firewall = FinancialFirewall(engine)
    authorization = _authorization("300", "1000", "200")
    plans = (
        _make_plan(1, "WM-022", "Kensington BioFit Mouse", "merchant-001", "250.00", credit=90, feedback=78, merchant_name="Kensington Direct"),
        _make_plan(2, "WM-031", "Ergo Keyboard", "merchant-004", "180.00", credit=50, feedback=38, merchant_name="Unknown Deals Ltd"),
        _make_plan(3, "WM-055", "Budget Mouse", "merchant-002", "150.00", credit=95, feedback=82, merchant_name="Budget Gadgets HK"),
    )
    decision = firewall.evaluate_purchase_plans(
        FirewallRequest(
            plans=plans,
            context=_context(authorization, "400", request_id="DEMO-1"),
            confirmation_provider=lambda evaluation: UserConfirmationResponse(approved=True),
        )
    )
    _print_flow("Flow 1 - Plan 1 needs confirmation; the user confirms (Plan 2 and 3 are never evaluated)", decision, audit)

    # Flow 2: Plan 1 breaks the daily limit, Plan 2 is approved.
    audit = AuditService(path=args.audit_log)
    engine = AuthorizationEngine(audit_service=audit)
    firewall = FinancialFirewall(engine)
    plans = (
        _make_plan(1, "WM-022", "Kensington BioFit Mouse", "merchant-001", "250.00", credit=90, feedback=78, merchant_name="Kensington Direct"),
        _make_plan(2, "WM-041", "Compact Keyboard", "merchant-002", "150.00", credit=95, feedback=82, merchant_name="Budget Gadgets HK"),
        _make_plan(3, "WM-055", "Budget Mouse", "merchant-002", "100.00", credit=95, feedback=82, merchant_name="Budget Gadgets HK"),
    )
    decision = firewall.evaluate_purchase_plans(
        FirewallRequest(plans=plans, context=_context(authorization, "850", request_id="DEMO-2"))
    )
    _print_flow("Flow 2 - Plan 1 exceeds the daily limit; Plan 2 is approved (Plan 3 is never evaluated)", decision, audit)

    # Flow 3: low merchant rating plus confirmation threshold; user continues and blacklists.
    audit = AuditService(path=args.audit_log)
    store = BlacklistStore()
    engine = AuthorizationEngine(audit_service=audit, blacklist_store=store)
    firewall = FinancialFirewall(engine)
    looser = _authorization("500", "1000", "300")
    risky = (
        _make_plan(1, "WM-077", "Wireless Headset", "merchant-004", "350.00", credit=55, feedback=50, merchant_name="Unknown Deals Ltd"),
        _make_plan(2, "WM-102", "Wired Headset", "merchant-001", "120.00", credit=90, feedback=78, merchant_name="Kensington Direct"),
    )
    decision = firewall.evaluate_purchase_plans(
        FirewallRequest(
            plans=risky,
            context=_context(looser, "200", request_id="DEMO-3"),
            confirmation_provider=lambda evaluation: UserConfirmationResponse(approved=True, blacklist_merchant=True),
        )
    )
    _print_flow("Flow 3 - low merchant rating and confirmation threshold: user continues and blacklists the merchant", decision, audit)
    print(f"Blacklisted merchants now: {', '.join(store.merchants)}")
    print()

    follow_up_audit = AuditService(path=args.audit_log)
    follow_up_engine = AuthorizationEngine(
        audit_service=follow_up_audit, blacklist_store=store
    )
    follow_up = FinancialFirewall(follow_up_engine).evaluate_purchase_plans(
        FirewallRequest(
            plans=(
                _make_plan(1, "WM-077", "Wireless Headset", "merchant-004", "350.00", credit=55, feedback=50, merchant_name="Unknown Deals Ltd"),
            ),
            context=_context(looser, "200", request_id="DEMO-3-FOLLOW-UP", blacklist=store.merchants),
        )
    )
    _print_flow("Flow 3b - a later request from the blacklisted merchant is denied", follow_up, follow_up_audit)

    # Flow 4: every plan is denied.
    audit = AuditService(path=args.audit_log)
    engine = AuthorizationEngine(
        audit_service=audit, blacklist_store=BlacklistStore(["merchant-004"])
    )
    firewall = FinancialFirewall(engine)
    denied_plans = (
        _make_plan(1, "WM-200", "Premium Monitor", "merchant-001", "500.00", credit=90, feedback=78, merchant_name="Kensington Direct"),
        _make_plan(2, "WM-201", "Compact Monitor", "merchant-002", "300.00", credit=95, feedback=82, merchant_name="Budget Gadgets HK"),
        _make_plan(3, "WM-202", "Cheap Monitor", "merchant-004", "120.00", credit=55, feedback=50, merchant_name="Unknown Deals Ltd"),
    )
    decision = firewall.evaluate_purchase_plans(
        FirewallRequest(plans=denied_plans, context=_context(authorization, "750", request_id="DEMO-4"))
    )
    _print_flow("Flow 4 - all three plans are denied, so the request is denied", decision, audit)

    return EXIT_APPROVE


# ----------------------------------------------------------------------
# parser
# ----------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m firewall",
        description="Financial Firewall: deterministic authorization of AI-proposed purchases.",
    )
    subparsers = parser.add_subparsers(dest="command")

    configure = subparsers.add_parser(
        "configure", help="Set Maximum Per Transaction, Maximum Daily Spend and Confirmation Threshold."
    )
    configure.add_argument("--max-per-transaction")
    configure.add_argument("--max-daily-spend")
    configure.add_argument("--confirmation-threshold")
    configure.add_argument("--daily-spent", default=None, help="Amount already spent today.")
    configure.add_argument("--state-file", default=DEFAULT_STATE_FILE)
    configure.set_defaults(handler=_cmd_configure)

    evaluate = subparsers.add_parser(
        "evaluate", help="Evaluate the purchase plans of one request_id from a shopping report."
    )
    evaluate.add_argument("--report", required=True, help="Path to the upstream shopping report JSON.")
    evaluate.add_argument("--request-id", default=None, help="Which request_id to authorize.")
    evaluate.add_argument("--catalog", default=DEFAULT_CATALOG_FILE, help="Trusted merchant catalogue JSON.")
    evaluate.add_argument("--state-file", default=DEFAULT_STATE_FILE)
    evaluate.add_argument("--blacklist-file", default=DEFAULT_BLACKLIST_FILE)
    evaluate.add_argument("--audit-log", default=None, help="Optional JSONL audit log path.")
    evaluate.add_argument("--max-per-transaction", default=None)
    evaluate.add_argument("--max-daily-spend", default=None)
    evaluate.add_argument("--confirmation-threshold", default=None)
    evaluate.add_argument("--daily-spent", default=None)
    evaluate.add_argument("--non-interactive", action="store_true", help="Never prompt; return ASK instead.")
    evaluate.add_argument("--json", action="store_true", help="Also print the decision as JSON.")
    evaluate.add_argument("--show-audit", action="store_true", help="Print the audit trail as JSON lines.")
    evaluate.add_argument("--quiet", action="store_true")
    evaluate.set_defaults(handler=_cmd_evaluate)

    demo = subparsers.add_parser("demo", help="Run the built-in sample scenarios.")
    demo.add_argument("--audit-log", default=None, help="Optional JSONL audit log path.")
    demo.set_defaults(handler=_cmd_demo)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return EXIT_INVALID
    try:
        return handler(args)
    except CliError as error:
        print(f"Error: {error}", file=sys.stderr)
        return EXIT_INVALID
    except (
        AuthorizationValidationError,
        ShoppingReportError,
        UnknownRequestError,
        BlacklistError,
        MerchantCatalogError,
        MoneyError,
    ) as error:
        print(f"Error: {error}", file=sys.stderr)
        return EXIT_INVALID


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
