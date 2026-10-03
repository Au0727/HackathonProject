"""HTTP API for the shopping-agent and Financial Firewall pipeline.

Run from this directory with ``uvicorn server:app --reload --port 8000``.
Configured model APIs are preferred; failed or unavailable API calls fall back
to the deterministic offline implementation.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from threading import RLock
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent
SUPERVISOR_DIR = HERE.parent / "BackEnd-Supervisor"
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(SUPERVISOR_DIR) not in sys.path:
    sys.path.insert(0, str(SUPERVISOR_DIR))

import firewall_bridge
from firewall_bridge import DEFAULT_MERCHANT_DIR
from intent_to_purchase import (
    IntentToPurchasePipeline,
    StructuredIntent,
    default_inventory_path,
    load_config,
    load_products,
)
from logging_setup import setup_logging

LOG_DIR = HERE / "logs"
FRONTEND_AUDIT_PATH = LOG_DIR / "frontend-audit.jsonl"
logger = logging.getLogger("commerce_api")
_daily_spend_day = date.today()
_daily_spent = Decimal("0.00")
_daily_spend_lock = RLock()


def _current_daily_spent() -> Decimal:
    global _daily_spend_day, _daily_spent
    with _daily_spend_lock:
        today = date.today()
        if today != _daily_spend_day:
            _daily_spend_day = today
            _daily_spent = Decimal("0.00")
        return _daily_spent

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    setup_logging(level="INFO", directory=LOG_DIR, console=False, llm_payloads=False)
    yield


app = FastAPI(title="Agentic Commerce API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)

class InterpretRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=12_000)


class SearchRequest(BaseModel):
    intent: StructuredIntent
    max_results: int = Field(default=10, ge=1, le=50)


class AuditInput(BaseModel):
    id: str
    transactionId: str | None = None
    timestamp: str
    eventType: str
    actor: str
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)


class RevocationRequest(BaseModel):
    revokedAt: str


class TransactionRequest(BaseModel):
    mandate: dict[str, Any]
    transaction: dict[str, Any]


def _json_response(data: Any, status_code: int = 200) -> JSONResponse:
    """Serialize every Decimal as a JSON string to preserve cents on the wire."""
    return JSONResponse(
        content=json.loads(json.dumps(data, default=_json_default)),
        status_code=status_code,
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _money_string(values: dict[str, Any], field: str, default: str | None = None) -> Decimal:
    value = values.get(field, default)
    if not isinstance(value, str) or not re.fullmatch(r"-?\d+(?:\.\d{1,2})?", value):
        raise ValueError(f"{field} must be a decimal string with at most two fractional digits")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field} is not a valid decimal amount") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"{field} must be a finite, non-negative amount")
    return amount


def _pipeline() -> IntentToPurchasePipeline:
    config = load_config()
    products = load_products(default_inventory_path(config))
    # Prefer the configured API; the LLM client falls back to offline rules on failure.
    llm = firewall_bridge.build_llm(config, allow_network=True)
    return IntentToPurchasePipeline(products, llm=llm, progress=False)


def _merchant_catalog():
    products = load_products(default_inventory_path(load_config()))
    firewall_bridge.build_merchant_directory(
        products,
        base_catalog_path=SUPERVISOR_DIR / "samples" / "merchant_catalog.json",
        output_path=DEFAULT_MERCHANT_DIR,
        verbose=False,
    )
    from firewall.adapters import MerchantCatalog

    return MerchantCatalog.load(DEFAULT_MERCHANT_DIR)


@app.post("/api/mandates/interpret")
def interpret_mandate(body: InterpretRequest) -> JSONResponse:
    """Extract and return the validated StructuredIntent without altering text."""
    try:
        intent = _pipeline().extract_intent(body.prompt)
    except Exception as exc:
        logger.exception("Mandate interpretation failed")
        raise HTTPException(status_code=502, detail="Mandate interpretation failed") from exc
    return _json_response(intent.model_dump(mode="json"))


@app.post("/api/shopping/search")
def shopping_search(body: SearchRequest) -> JSONResponse:
    """Run search, compliance, rank, firewall authorization and reduction."""
    prompt = body.intent.raw_request
    if not prompt:
        prompt = " ".join(body.intent.product_keywords)
    try:
        report, _ = firewall_bridge.run(
            [prompt],
            intents=[body.intent],
            options=min(body.max_results, 3),
            max_results=body.max_results,
            keep=2,
            config=load_config(),
            progress=False,
            offline=False,
            daily_spent=format(_current_daily_spent(), "f"),
        )
    except firewall_bridge.BridgeError as exc:
        logger.exception("Shopping pipeline unavailable")
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (ValueError, OSError) as exc:
        logger.exception("Shopping pipeline failed")
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Shopping pipeline failed")
        raise HTTPException(status_code=500, detail="Shopping pipeline failed") from exc
    return _json_response(report)


@app.get("/api/catalog")
def get_catalog() -> JSONResponse:
    """Serve the trusted backend inventory in the frontend Product shape."""
    try:
        products = load_products(default_inventory_path(load_config()))
        merchant_ids = {
            product.product_id: f"brand-{product.brand.casefold().replace(' ', '-')}"
            for product in products
        }
        result = [
            {
                "id": product.product_id,
                "name": product.product_name,
                "category": "Computer Accessories",
                "merchantId": merchant_ids[product.product_id],
                "merchantName": f"{product.brand} Direct (auto-mapped)",
                "price": str(product.price),
                "shipping": str(product.shipping_fee),
                "currency": "HKD",
                "rating": 0,
                "description": product.description,
                "source": "BackEnd-AI wireless mouse inventory",
            }
            for product in sorted(products, key=lambda item: item.product_id)
        ]
    except Exception as exc:
        logger.exception("Catalog could not be loaded")
        raise HTTPException(status_code=503, detail="Catalog could not be loaded") from exc
    return _json_response(result)


def _evaluate_authorization_result(payload: TransactionRequest) -> dict[str, Any]:
    from firewall.adapters import CatalogMerchantRiskProvider
    from firewall.audit import AuditService
    from firewall.authorization_engine import AuthorizationEngine
    from firewall.models import AuthorizationContext, PurchasePlan, UserAuthorization
    from firewall.money import Money
    from firewall.types import Currency

    mandate = payload.mandate
    transaction = payload.transaction
    money = Money.parse
    now = datetime.now(timezone.utc)

    expiry = mandate.get("expiresAt")
    mandate_id = str(mandate.get("id", ""))
    revoked = mandate.get("revokedAt") or _revoked_mandates.get(mandate_id)
    checks: list[dict[str, Any]] = []

    def add(rule_id: str, passed: bool, detail: str) -> None:
        checks.append(
            {"id": rule_id, "label": rule_id.replace("_", " ").title(), "passed": passed, "detail": detail}
        )

    active = True
    if expiry:
        try:
            parsed_expiry = datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
            if parsed_expiry.tzinfo is None:
                parsed_expiry = parsed_expiry.replace(tzinfo=timezone.utc)
            active = parsed_expiry > now
        except (TypeError, ValueError):
            active = False
    add("EXPIRY", active, "Mandate is active." if active else "Mandate is expired or has an invalid expiry.")
    not_revoked = not bool(revoked)
    add("REVOCATION", not_revoked, "Mandate has not been revoked." if not_revoked else "Mandate was revoked.")

    products = load_products(default_inventory_path(load_config()))
    product_id = str(transaction.get("productId", ""))
    product = next((item for item in products if item.product_id == product_id), None)
    if product is None:
        add("PRODUCT_DATA", False, "Product is not present in the trusted backend inventory.")
        return {
            "decision": "DENY",
            "reason": checks[-1]["detail"],
            "failedRules": [item["id"] for item in checks if not item["passed"]],
            "evaluatedAt": now.isoformat(),
            "mandateId": mandate_id,
            "ruleChecks": checks,
        }

    expected_subtotal = Decimal(str(product.price))
    expected_shipping = Decimal(str(product.shipping_fee))
    expected_total = expected_subtotal + expected_shipping
    subtotal = _money_string(transaction, "subtotal", "0.00")
    shipping = _money_string(transaction, "shipping", "0.00")
    total = _money_string(transaction, "total", "0.00")
    tax = _money_string(transaction, "tax", "0.00")
    amounts_match = (
        subtotal == expected_subtotal
        and shipping == expected_shipping
        and total == expected_total
        and tax == Decimal("0.00")
    )
    add(
        "PRICE_INTEGRITY",
        amounts_match,
        "Transaction amounts match the trusted inventory."
        if amounts_match
        else "Transaction amounts differ from the trusted inventory price.",
    )
    if not amounts_match:
        return {
            "decision": "DENY",
            "reason": checks[-1]["detail"],
            "failedRules": [item["id"] for item in checks if not item["passed"]],
            "evaluatedAt": now.isoformat(),
            "mandateId": mandate_id,
            "ruleChecks": checks,
        }

    category_allowed = (
        not mandate.get("allowedCategories")
        or "Computer Accessories" in mandate["allowedCategories"]
    )
    add(
        "CATEGORY",
        category_allowed,
        "Product category is permitted."
        if category_allowed
        else "Product category is outside the mandate.",
    )

    catalog = _merchant_catalog()
    trusted_merchant_id = catalog.merchant_id_for_product(product_id)
    approved_merchants = mandate.get("allowedMerchants") or []
    merchant_allowed = (
        trusted_merchant_id is not None
        and (not approved_merchants or trusted_merchant_id in approved_merchants)
    )
    add(
        "MERCHANT",
        merchant_allowed,
        "Trusted merchant is permitted by the mandate."
        if merchant_allowed
        else "Merchant is unmapped or not on the approved list.",
    )

    if not (active and not_revoked and category_allowed and merchant_allowed):
        failed = [item["id"] for item in checks if not item["passed"]]
        reason = next(item["detail"] for item in checks if not item["passed"])
        return {
            "decision": "DENY",
            "reason": reason,
            "failedRules": failed,
            "evaluatedAt": now.isoformat(),
            "mandateId": mandate_id,
            "ruleChecks": checks,
        }

    transaction_id = product_id
    merchant_id = trusted_merchant_id
    daily_spent = _current_daily_spent()
    plan = PurchasePlan(
        rank=1,
        product_id=transaction_id,
        product_name=product.product_name,
        merchant_id=merchant_id,
        subtotal=money(str(product.price)),
        shipping=money(str(product.shipping_fee)),
        tax=money("0.00"),
        total=money(str(expected_total)),
        currency=Currency.HKD,
    )
    default_total = transaction.get("total", "0.00")
    authorization = UserAuthorization(
        max_per_transaction=money(
            str(_money_string(mandate, "maxPerTransaction", default_total))
        ),
        max_daily_spend=money(
            str(
                _money_string(
                    mandate,
                    "maxDailySpend",
                    format(daily_spent + expected_total, "f"),
                )
            )
        ),
        confirmation_threshold=money(
            str(_money_string(mandate, "requiresConfirmationAbove", default_total))
        ),
    )
    context = AuthorizationContext(
        authorization=authorization,
        daily_spent=money(format(daily_spent, "f")),
        session_id="frontend",
        request_id=transaction_id or "transaction",
        merchant_risk_provider=CatalogMerchantRiskProvider(catalog),
    )
    evaluation = AuthorizationEngine(audit_service=AuditService(path=None)).evaluate_plan(
        plan, context
    )
    status = getattr(evaluation.status, "value", str(evaluation.status))
    for rule in evaluation.evaluations:
        checks.append(
            {
                "id": rule.code.value,
                "label": rule.code.value.replace("_", " ").title(),
                "passed": rule.passed,
                "detail": rule.reason,
            }
        )
    failed = [item["id"] for item in checks if not item["passed"]]
    if status == "APPROVE":
        decision = "ALLOW"
    elif status == "ASK":
        decision = "ASK"
    else:
        decision = "DENY"
    return {
        "decision": decision,
        "reason": evaluation.reason,
        "failedRules": failed,
        "evaluatedAt": now.isoformat(),
        "mandateId": mandate_id,
        "ruleChecks": checks,
    }


def _authorization_result(payload: TransactionRequest) -> dict[str, Any]:
    return _evaluate_authorization_result(payload)


@app.post("/api/authorization/evaluate")
def evaluate_authorization(body: TransactionRequest) -> JSONResponse:
    """Compatibility route for the frontend's explicit policy-evaluation step."""
    try:
        return _json_response(_authorization_result(body))
    except (ValueError, KeyError, InvalidOperation) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Authorization failed")
        raise HTTPException(status_code=503, detail="Authorization service unavailable") from exc


_payment_transactions: dict[str, dict[str, Any]] = {}
_revoked_mandates: dict[str, str] = {}


@app.patch("/api/mandates/{mandate_id}/revoke")
def revoke_mandate(mandate_id: str, body: RevocationRequest) -> JSONResponse:
    try:
        revoked_at = datetime.fromisoformat(body.revokedAt.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail="revokedAt must be a valid ISO 8601 timestamp",
        ) from exc
    if revoked_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="revokedAt must include a timezone")
    value = revoked_at.astimezone(timezone.utc).isoformat()
    with _daily_spend_lock:
        recorded = _revoked_mandates.setdefault(mandate_id, value)
    return _json_response({"id": mandate_id, "revokedAt": recorded})


@app.post("/api/transactions/{transaction_id}/payment/start")
def start_payment(transaction_id: str, transaction: dict[str, Any]) -> JSONResponse:
    if str(transaction.get("id", "")) != transaction_id:
        raise HTTPException(status_code=400, detail="Transaction id does not match URL")
    existing = _payment_transactions.get(transaction_id)
    if existing and existing.get("status") in {"COMPLETED", "CANCELLED"}:
        return _json_response(existing)
    pending = {**transaction, "status": "PAYMENT_PENDING"}
    _payment_transactions[transaction_id] = pending
    return _json_response(pending)


@app.post("/api/transactions/{transaction_id}/payment/complete")
def complete_payment(transaction_id: str, body: TransactionRequest) -> JSONResponse:
    pending = _payment_transactions.get(transaction_id)
    if pending is None:
        raise HTTPException(status_code=404, detail="No pending transaction with this id")
    if pending.get("status") in {"COMPLETED", "CANCELLED"}:
        return _json_response(pending)
    if str(body.transaction.get("id", "")) != transaction_id:
        raise HTTPException(status_code=400, detail="Transaction id does not match URL")
    global _daily_spent
    with _daily_spend_lock:
        verdict = _evaluate_authorization_result(body)
        status = "CANCELLED" if verdict["decision"] == "DENY" else "COMPLETED"
        completed = {**pending, "status": status}
        _payment_transactions[transaction_id] = completed
        if status == "COMPLETED":
            _daily_spent += _money_string(body.transaction, "total", "0.00")
    return _json_response(completed)


def _audit_events() -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in sorted(LOG_DIR.glob("pipeline-*.log")):
        for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            match = re.match(
                r"(?P<timestamp>\d{4}-\d\d-\d\dT\S+)\s+(?P<level>[A-Z]+)\s+(?:\[(?P<logger>[^]]+)\]\s+)?(?P<message>.*)",
                line,
            )
            timestamp = match.group("timestamp") if match else ""
            message = match.group("message") if match else line
            events.append(
                {
                    "id": f"{path.name}:{line_number}",
                    "timestamp": timestamp,
                    "eventType": "PIPELINE_LOG",
                    "actor": "AGENT",
                    "summary": message,
                    "data": {"level": match.group("level") if match else "INFO", "source": path.name},
                }
            )
    for path in sorted(LOG_DIR.glob("agent-report-*.json")):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Skipping unreadable agent report %s", path.name)
            continue
        stamp = str(report.get("generated_at", ""))
        for result in report.get("results", []):
            events.append(
                {
                    "id": f"{path.name}:{result.get('request_id', 'result')}",
                    "timestamp": stamp,
                    "eventType": "AGENT_REPORT",
                    "actor": "AGENT",
                    "summary": result.get("stop_reason")
                    or f"{result.get('status', 'UNKNOWN')}: {result.get('request', '')}",
                    "data": result,
                }
            )
    if FRONTEND_AUDIT_PATH.is_file():
        for line in FRONTEND_AUDIT_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("Skipping malformed frontend audit record")
    events.sort(key=lambda item: str(item.get("timestamp", "")), reverse=True)
    return events


@app.get("/api/audit/logs")
def get_audit_logs() -> JSONResponse:
    return _json_response(_audit_events())


@app.post("/api/audit/logs", status_code=201)
def append_audit_log(event: AuditInput) -> JSONResponse:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with FRONTEND_AUDIT_PATH.open("a", encoding="utf-8") as stream:
        stream.write(event.model_dump_json() + "\n")
    return _json_response({"stored": True}, status_code=201)


@app.delete("/api/audit/logs")
def clear_audit_logs() -> JSONResponse:
    if FRONTEND_AUDIT_PATH.exists():
        FRONTEND_AUDIT_PATH.write_text("", encoding="utf-8")
    return _json_response({"cleared": True})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
