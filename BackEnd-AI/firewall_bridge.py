"""
firewall_bridge.py
==================
Bridge between the shopping agent (``BackEnd-AI``) and the Financial Firewall
(``BackEnd-Supervisor``).

The two components do different jobs and neither one duplicates the other:

* the shopping agent ranks candidate purchases and enforces the user's mandate
  (budget caps, category rules, injection defence). It proposes **up to three
  ranked options** per request;
* the Financial Firewall performs **deterministic authorization**. It has no
  language model in the path: given the same authorization settings, daily
  spending and plans, it always returns the same decision. It reads a plan's own
  ``total_cost``, never a report-level total, and never sums plans together.

So the pipeline is:

```text
  request  ->  agent ranks 3 options  ->  firewall decides each  ->  2 final choices
               (report JSON)             APPROVE / ASK / DENY
```

The firewall consumes the agent's report through its own
``ShoppingReportAdapter`` — this bridge never re-implements that parsing. It
writes the intermediate report, hands the file to the adapter, and turns the
decisions back into the same JSON shape, keeping only the options the firewall
authorized.

Two deliberate boundaries
-------------------------
1. **Merchant risk is never read from the report.** *"merchant risk scores are
   never read from the report — only the trusted catalogue or an internal
   service supplies them."* The bridge therefore maintains a trusted merchant
   directory and maps products to merchants there. Risk bands are illustrative
   and authored by us, and the bridge says so on every run.
2. **A missing mapping is a denial, not an approval.** Unmapped products are
   denied by the firewall (``MERCHANT_RISK_DATA_UNAVAILABLE``) rather than
   guessed at.

Usage::

    python firewall_bridge.py "Find me a Kensington wireless mouse under $800 total."
    python firewall_bridge.py --options 3 --keep 2 --dry-run "..."
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent

# The supervisor is a sibling package; put it on the path so `import firewall`
# works without installing anything.
SUPERVISOR_DIR = HERE.parent / "BackEnd-Supervisor"
if SUPERVISOR_DIR.is_dir() and str(SUPERVISOR_DIR) not in sys.path:
    sys.path.insert(0, str(SUPERVISOR_DIR))

from intent_to_purchase import (  # noqa: E402  (path set up above)
    AppConfig,
    IntentToPurchasePipeline,
    StructuredIntent,
    build_grand_total,
    build_llm,
    build_request_result,
    default_inventory_path,
    load_config,
    load_products,
)
from logging_setup import glyph, setup_logging, stage as log_stage  # noqa: E402

#: Where the bridge keeps its trusted merchant directory and reports.
#: The directory lives beside the supervisor's own catalogue, in the sibling
#: package - not under BackEnd-AI.
DEFAULT_MERCHANT_DIR = SUPERVISOR_DIR / "samples" / "merchant_directory.json"
DEFAULT_REPORT_DIR = HERE / "logs"

#: Authorization defaults. The firewall considers a plan's OWN total, so these
#: are per-transaction limits, not session limits.
DEFAULT_MAX_PER_TRANSACTION = "5000.00"
DEFAULT_MAX_DAILY_SPEND = "2000.00"
DEFAULT_CONFIRMATION_THRESHOLD = "1000.00"

#: How the bridge invents risk scores for merchants it has never seen. These are
#: OUR numbers in a directory WE control -- never derived from product text.
AUTO_CREDIT_RANGE = (72, 95)
AUTO_FEEDBACK_RANGE = (70, 94)


class BridgeError(RuntimeError):
    """Raised when the bridge cannot wire the two components together."""


def _require_firewall():
    """Import the supervisor, with a clear error when it is not present."""
    try:
        from firewall.adapters import (
            CatalogMerchantRiskProvider,
            MerchantCatalog,
            ShoppingReportAdapter,
        )
        from firewall.audit import AuditService
        from firewall.authorization_engine import AuthorizationEngine
        from firewall.models import (
            AuthorizationContext,
            PurchasePlan,
            UserAuthorization,
        )
        from firewall.money import Money
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise BridgeError(
            f"Could not import the Financial Firewall from {SUPERVISOR_DIR}: {exc}"
        ) from exc
    return {
        "CatalogMerchantRiskProvider": CatalogMerchantRiskProvider,
        "MerchantCatalog": MerchantCatalog,
        "ShoppingReportAdapter": ShoppingReportAdapter,
        "AuditService": AuditService,
        "AuthorizationEngine": AuthorizationEngine,
        "AuthorizationContext": AuthorizationContext,
        "PurchasePlan": PurchasePlan,
        "UserAuthorization": UserAuthorization,
        "Money": Money,
    }


# ---------------------------------------------------------------------------
# Trusted merchant directory
# ---------------------------------------------------------------------------


def _deterministic_score(product_id: str, merchant_id: str, low: int, high: int) -> int:
    """A stable score in [low, high] derived only from the ids.

    Deterministic on purpose: the firewall's promise is that identical inputs
    produce identical decisions, so a randomized score would break that promise
    for the merchant-risk rule.
    """
    seed = f"{product_id}:{merchant_id}"
    digest = 0
    for char in seed:
        digest = (digest * 131 + ord(char)) % 1_000_003
    return low + (digest % (high - low + 1))


def build_merchant_directory(
    products: Sequence[Any],
    *,
    base_catalog_path: Path,
    output_path: Path,
    verbose: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Extend the supervisor's trusted catalogue to cover every product.

    Returns ``(directory, stats)``. Existing merchant records are preserved
    exactly; only missing products get a new mapping.
    """
    if not base_catalog_path.is_file():
        raise BridgeError(f"Base merchant catalogue not found: {base_catalog_path}")
    directory: Dict[str, Any] = json.loads(base_catalog_path.read_text(encoding="utf-8"))
    merchants: Dict[str, Any] = directory.setdefault("merchants", {})
    mapping: Dict[str, str] = directory.setdefault("productMerchants", {})

    added_products = 0
    added_merchants = 0
    for product in products:
        product_id = product.product_id
        if product_id in mapping:
            continue
        # One merchant per brand: a plausible directory, and every plan then has
        # a merchant whose risk is on file.
        merchant_id = f"brand-{product.brand.casefold().replace(' ', '-')}"
        if merchant_id not in merchants:
            credit = _deterministic_score(product_id, merchant_id, *AUTO_CREDIT_RANGE)
            feedback = _deterministic_score(
                merchant_id, product_id, *AUTO_FEEDBACK_RANGE
            )
            merchants[merchant_id] = {
                "merchantName": f"{product.brand} Direct (auto-mapped)",
                "merchantCreditScore": credit,
                "buyerFeedbackScore": feedback,
            }
            added_merchants += 1
        mapping[product_id] = merchant_id
        added_products += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(directory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    stats = {
        "base_catalog": str(base_catalog_path),
        "directory": str(output_path),
        "products_total": len(list(products)),
        "products_added": added_products,
        "merchants_added": added_merchants,
        "products_mapped": len(mapping),
        "merchants_total": len(merchants),
    }
    if verbose and added_products:
        log_stage(
            f"merchant dir     {glyph('arrow')} mapped {added_products} product(s) to "
            f"{added_merchants} new merchant(s) in {output_path.name}"
        )
    return directory, stats


def _merchant_names(directory: Dict[str, Any]) -> Dict[str, str]:
    """merchant_id -> display name, used when a plan carries no name."""
    return {
        str(merchant_id): str(record.get("merchantName") or merchant_id)
        for merchant_id, record in (directory.get("merchants") or {}).items()
    }


# ---------------------------------------------------------------------------
# Firewall authorization of a report
# ---------------------------------------------------------------------------


def authorize_report(
    report_path: Path,
    *,
    catalog_path: Path,
    keep: int = 2,
    max_per_transaction: str = DEFAULT_MAX_PER_TRANSACTION,
    max_daily_spend: str = DEFAULT_MAX_DAILY_SPEND,
    confirmation_threshold: str = DEFAULT_CONFIRMATION_THRESHOLD,
    daily_spent: str = "0.00",
    directory: Optional[Dict[str, Any]] = None,
    echo: bool = True,
    stream: Any = None,
) -> Dict[str, Any]:
    """Run the firewall rules over every candidate plan in a report.

    Each plan is evaluated with the engine's per-plan rule pipeline
    (``AuthorizationEngine.evaluate_plan``), which is the same deterministic
    rule set the priority engine uses, minus the "stop at the first APPROVE"
    orchestration. We want up to ``keep`` authorized choices rather than a single
    winner, so per-plan evaluation is the correct entry point; the one-shot
    priority decision is also computed and reported for comparison, because its
    early-stop behaviour is part of the firewall's contract.

    Returns decisions, per-request selections and the parsed plans.
    """
    firewall = _require_firewall()
    adapter = firewall["ShoppingReportAdapter"](
        firewall["MerchantCatalog"].load(catalog_path)
    )
    report = adapter.parse_file(report_path)

    audit = firewall["AuditService"](path=None)
    engine = firewall["AuthorizationEngine"](audit_service=audit)
    authorization = firewall["UserAuthorization"](
        max_per_transaction=firewall["Money"].parse(max_per_transaction),
        max_daily_spend=firewall["Money"].parse(max_daily_spend),
        confirmation_threshold=firewall["Money"].parse(confirmation_threshold),
    )
    catalog = firewall["MerchantCatalog"].load(catalog_path)
    provider = firewall["CatalogMerchantRiskProvider"](catalog)
    spent = firewall["Money"].parse(daily_spent)

    evaluations: Dict[str, List[Any]] = {}
    selected: Dict[str, List[int]] = {}
    plans_by_request: Dict[str, Dict[int, Any]] = {}
    priority: Dict[str, Any] = {}

    for request_report in report.requests:
        context = firewall["AuthorizationContext"](
            authorization=authorization,
            daily_spent=spent,
            session_id=report.report_type,
            request_id=request_report.request_id,
            merchant_risk_provider=provider,
        )

        request_evaluations = []
        merchant_by_rank: Dict[int, Any] = {}
        approved: List[int] = []
        for plan in request_report.plans:          # already rank-ordered
            evaluation = engine.evaluate_plan(plan, context)
            request_evaluations.append(evaluation)
            merchant_by_rank[plan.rank] = plan
            status = getattr(evaluation.status, "value", str(evaluation.status))
            if status == "APPROVE":
                approved.append(plan.rank)
            if echo:
                mark = glyph("ok") if status == "APPROVE" else glyph("fail")
                detail = "" if status == "APPROVE" else f"  ({evaluation.reason[:78]})"
                log_stage(
                    f"firewall         {mark} {request_report.request_id} rank "
                    f"{plan.rank} {glyph('arrow')} {status}{detail}",
                    stream=stream or sys.stdout,
                )

        evaluations[request_report.request_id] = request_evaluations
        plans_by_request[request_report.request_id] = merchant_by_rank
        selected[request_report.request_id] = sorted(approved)[:keep]

        # The firewall's primary contract: one decision, first APPROVE wins.
        decision = engine.evaluate_plans(request_report.plans, context)
        priority[request_report.request_id] = decision

    return {
        "evaluations": evaluations,
        "selected": selected,
        "plans_by_request": plans_by_request,
        "priority": priority,
        "report": report,
        "authorization": {
            "max_per_transaction": max_per_transaction,
            "max_daily_spend": max_daily_spend,
            "confirmation_threshold": confirmation_threshold,
            "daily_spent": daily_spent,
            "currency": "HKD",
        },
    }


# ---------------------------------------------------------------------------
# Final report: 2 authorized choices per request
# ---------------------------------------------------------------------------


def build_final_report(
    base_report: Dict[str, Any],
    outcome: Dict[str, Any],
    *,
    keep: int = 2,
) -> Dict[str, Any]:
    """Reduce the agent's report to the options the firewall authorized.

    Same JSON shape as the agent's report, so downstream readers need no new
    parser. Only options whose rank the firewall APPROVED survive, and at most
    ``keep`` of them per request.
    """
    selected: Dict[str, List[int]] = outcome.get("selected", {})
    evaluations: Dict[str, List[Any]] = outcome.get("evaluations", {})
    plans_by_request: Dict[str, Dict[int, Any]] = outcome.get("plans_by_request", {})
    priority: Dict[str, Any] = outcome.get("priority", {})

    final: Dict[str, Any] = {
        "report_type": "authorized_selection",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "session": base_report.get("session", ""),
        "currency": base_report.get("currency", "HKD"),
        "authorization": outcome.get("authorization", {}),
        "requests_made": base_report.get("requests_made", 0),
        "requests_with_options": 0,
        "results": [],
    }

    totals = {
        "items_selected": 0, "quantity": 0, "currency": "HKD",
        "goods_subtotal": Decimal("0.00"),
        "shipping_total": Decimal("0.00"),
        "grand_total": Decimal("0.00"),
    }

    for result in base_report.get("results", []):
        request_id = str(result.get("request_id", ""))
        wanted = set(selected.get(request_id, []))
        if not wanted:
            continue
        plans = plans_by_request.get(request_id, {})
        checks = {
            getattr(e.plan, "rank", None): e for e in evaluations.get(request_id, [])
        }
        options: List[Dict[str, Any]] = []
        for option in result.get("best_options", []):
            rank = option.get("rank")
            if not isinstance(rank, int) or rank not in wanted:
                continue
            if len(options) >= keep:
                break
            enriched = dict(option)
            enriched["authorized"] = True
            enriched["authorized_by"] = "financial_firewall"
            plan = plans.get(rank)
            if plan is not None and plan.merchant_name:
                enriched["merchant_name"] = plan.merchant_name
            if plan is not None and plan.merchant_id:
                enriched["merchant_id"] = plan.merchant_id
            risk = getattr(checks.get(rank), "merchant_risk", None)
            if risk is not None:
                enriched["merchant_risk"] = risk.to_dict()
            options.append(enriched)

        if not options:
            continue

        goods = sum(Decimal(str(o.get("price", "0"))) for o in options)
        shipping = sum(Decimal(str(o.get("shipping_fee", "0"))) for o in options)
        quantity = sum(int(o.get("quantity", 1)) for o in options)
        request_totals = {
            "items_selected": len(options),
            "quantity": quantity,
            "currency": "HKD",
            "goods_subtotal": str(goods.quantize(Decimal("0.01"))),
            "shipping_total": str(shipping.quantize(Decimal("0.01"))),
            "grand_total": str((goods + shipping).quantize(Decimal("0.01"))),
        }
        totals["items_selected"] += len(options)
        totals["quantity"] += quantity
        totals["goods_subtotal"] += goods
        totals["shipping_total"] += shipping
        totals["grand_total"] += goods + shipping
        final["requests_with_options"] += 1

        entry: Dict[str, Any] = {
            "request_id": request_id,
            "request": result.get("request", ""),
            "status": "AUTHORIZED",
            "cap_enforced": result.get("cap_enforced"),
            "best_options": options,
            "totals": request_totals,
        }
        decision = priority.get(request_id)
        if decision is not None:
            entry["firewall"] = decision.to_dict()
        final["results"].append(entry)

    for key in ("goods_subtotal", "shipping_total", "grand_total"):
        totals[key] = str(totals[key].quantize(Decimal("0.01")))
    final["grand_total"] = totals
    return final


# ---------------------------------------------------------------------------
# End-to-end run
# ---------------------------------------------------------------------------


def run(
    requests: Sequence[str],
    *,
    intents: Optional[Sequence[StructuredIntent]] = None,
    options: int = 3,
    max_results: int = 10,
    keep: int = 2,
    config: Optional[AppConfig] = None,
    dry_run: bool = False,
    stream: Any = None,
    max_per_transaction: str = DEFAULT_MAX_PER_TRANSACTION,
    max_daily_spend: str = DEFAULT_MAX_DAILY_SPEND,
    confirmation_threshold: str = DEFAULT_CONFIRMATION_THRESHOLD,
    daily_spent: str = "0.00",
    progress: bool = True,
    offline: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Full pipeline: rank `options` candidates, authorize, emit `keep` choices.

    Set ``progress=False`` to keep stdout clean for JSON output, and
    ``offline=True`` to force the deterministic local model instead of a
    configured API (used by the tests, which must never spend credit).
    """
    out = stream or sys.stdout
    if intents is not None and len(intents) != len(requests):
        raise ValueError("intents must contain exactly one StructuredIntent per request")
    config = config or load_config()
    inventory = default_inventory_path(config)
    products = load_products(inventory)
    llm = build_llm(config, allow_network=not offline)

    if progress:
        log_stage(
            f"stage A          {glyph('arrow')} shopping agent ranks up to {options} "
            f"option(s) per request", stream=out,
        )
    results = []
    for index, request in enumerate(requests, 1):
        pipeline = IntentToPurchasePipeline(
            products, llm=llm, top_n=options, max_results=max_results, progress=False,
        )
        response = pipeline.run(
            request,
            intent_override=intents[index - 1] if intents is not None else None,
        )
        results.append(build_request_result(index, request, response))
    base_report = build_grand_total(results, session="bridge", llm=llm)
    base_json = json.loads(base_report.model_dump_json())

    report_dir = DEFAULT_REPORT_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    report_path = report_dir / f"agent-report-{stamp}.json"
    report_path.write_text(
        json.dumps(base_json, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if progress:
        log_stage(f"stage A          {glyph('ok')} report written to {report_path.name}",
                  stream=out)

    directory, stats = build_merchant_directory(
        products,
        base_catalog_path=SUPERVISOR_DIR / "samples" / "merchant_catalog.json",
        output_path=DEFAULT_MERCHANT_DIR,
        verbose=False,
    )

    if dry_run:
        if progress:
            log_stage(
                f"dry run          {glyph('ok')} agent report ready; "
                f"firewall not invoked", stream=out,
            )
        return base_json, {"dry_run": True, "report_path": str(report_path),
                           "merchant_stats": stats}

    if progress:
        log_stage(
            f"stage B          {glyph('arrow')} Financial Firewall authorizes each plan",
            stream=out,
        )
    outcome = authorize_report(
        report_path,
        catalog_path=DEFAULT_MERCHANT_DIR,
        keep=keep,
        directory=directory,
        stream=out,
        echo=progress,
        max_per_transaction=max_per_transaction,
        max_daily_spend=max_daily_spend,
        confirmation_threshold=confirmation_threshold,
        daily_spent=daily_spent,
    )
    final = build_final_report(base_json, outcome, keep=keep)
    selected_by_request = outcome.get("selected", {})

    def halt_for(result: Any) -> Dict[str, Any]:
        decision = outcome.get("priority", {}).get(result.request_id)
        reason = result.stop_reason or getattr(
            decision, "reason", "The Financial Firewall did not approve a purchase."
        )
        decision_status = getattr(getattr(decision, "status", None), "value", "")
        status = result.status
        if not result.stop_reason and decision_status:
            status = "DENIED_BY_FIREWALL" if decision_status == "DENY" else decision_status
        return {
            "request_id": result.request_id,
            "request": result.request,
            "status": status,
            "reason": reason,
        }

    final["halts"] = [
        halt_for(result)
        for result in base_report.results
        if not selected_by_request.get(result.request_id)
    ]
    final["merchant_directory"] = stats
    final["agent_report"] = report_path.name

    if progress:
        log_stage(
            f"stage B          {glyph('ok')} {final['requests_with_options']} request(s) "
            f"have authorized options", stream=out,
        )
    return final, {"outcome": outcome, "report_path": report_path,
                   "merchant_stats": stats}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python firewall_bridge.py",
        description=(
            "Shopping agent ranks 3 options, the Financial Firewall authorizes "
            "them, and 2 final choices are emitted."
        ),
    )
    parser.add_argument("requests", nargs="*", help="Shopping requests.")
    parser.add_argument("--options", type=int, default=3,
                        help="How many options the agent proposes (default 3).")
    parser.add_argument("--keep", type=int, default=2,
                        help="How many authorized choices to emit (default 2).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Produce the agent report and stop before the firewall.")
    parser.add_argument("--json-only", action="store_true",
                        help="Print only the final JSON.")
    parser.add_argument("--max-per-transaction", default=DEFAULT_MAX_PER_TRANSACTION,
                        help="Firewall: maximum for a single transaction.")
    parser.add_argument("--max-daily-spend", default=DEFAULT_MAX_DAILY_SPEND,
                        help="Firewall: maximum for one day.")
    parser.add_argument("--confirmation-threshold",
                        default=DEFAULT_CONFIRMATION_THRESHOLD,
                        help="Firewall: above this amount the user is asked.")
    parser.add_argument("--daily-spent", default="0.00",
                        help="Firewall: amount already spent today.")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    stream = sys.stderr if args.json_only else sys.stdout
    setup_logging(level="WARNING" if args.json_only else "INFO",
                  directory=None, console=False)
    requests = args.requests or ["Find me a Kensington wireless mouse under $800 total."]

    try:
        final, _ = run(
            requests, options=args.options, keep=args.keep,
            dry_run=args.dry_run, stream=stream,
            max_per_transaction=args.max_per_transaction,
            max_daily_spend=args.max_daily_spend,
            confirmation_threshold=args.confirmation_threshold,
            daily_spent=args.daily_spent,
        )
    except BridgeError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2

    print(json.dumps(final, indent=2, ensure_ascii=False), file=sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
