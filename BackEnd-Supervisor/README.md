# Financial Firewall

Deterministic financial authorization for an AI shopping flow.

> The AI proposes a purchase. The Financial Firewall decides whether that purchase is
> authorized. The user makes the final choice when ASK is required.

The shopping agent upstream understands the request, searches products and ranks candidate
plans. This component does none of that. It receives up to three **already-ranked** purchase
plans plus trusted merchant risk data and answers one question per plan:

```text
APPROVE  -> return this plan immediately and stop
ASK      -> the user must confirm before this plan can be authorized
DENY     -> this plan violates a hard limit; try the next-ranked plan
```

No language model is in the authorization path. Given the same authorization settings, daily
spending state, plans and merchant data, the firewall always produces the same decision.

## Quick start

```powershell
# 1. Set the three authorization values (interactive, English prompts)
python -m firewall configure

# 2. Non-interactive equivalent
python -m firewall configure --max-per-transaction 300 --max-daily-spend 1000 `
    --confirmation-threshold 200 --daily-spent 400

# 3. Evaluate one shopping request from an upstream report
python -m firewall evaluate --report samples/optimal_selection_sample.json --request-id REQ-002

# 4. Run the built-in sample scenarios (no input required)
python -m firewall demo

# 5. Run the test-suite (stdlib unittest, no dependencies)
python -m unittest discover -s tests -t .
```

`evaluate` exit codes: `0` APPROVE, `1` DENY, `2` invalid input, `3` ASK still awaiting the user.

## Layout

```text
firewall/
  types.py                  enums: Currency, DecisionStatus, RuleCode, severity, risk levels
  money.py                  exact integer minor-unit money (HKD cents)
  models.py                 PurchasePlan, MerchantRisk, UserAuthorization, decisions, audit event
  rating.py                 merchantRating = credit*0.60 + feedback*0.40 (2 dp)
  messages.py               every user-facing English string
  validation.py             fail-closed input validation
  rules/
    base.py                 rule result helper
    invalid_plan.py         INVALID_PLAN_DATA
    merchant_blacklist.py   MERCHANT_BLACKLISTED
    max_per_transaction.py  MAX_PER_TRANSACTION
    max_daily_spend.py      MAX_DAILY_SPEND
    merchant_risk.py        MERCHANT_RATING_LOW / MERCHANT_RISK_DATA_UNAVAILABLE
    confirmation_threshold.py  CONFIRMATION_THRESHOLD_EXCEEDED
  rule_engine.py            single-plan pipeline + decision aggregation
  authorization_engine.py   three-plan priority engine, ASK suspension, FinancialFirewall facade
  blacklist.py              structured merchant blacklist (+ optional JSON persistence)
  audit/service.py          audit trail (JSONL optional)
  transaction/state_machine.py   PROPOSED -> AUTHORIZED -> CHECKOUT -> PAYMENT_PENDING -> COMPLETED
  adapters/shopping_report.py    upstream report JSON -> PurchasePlan[]
  adapters/merchant_catalog.py   trusted merchant risk catalogue
  ui.py                     English rendering (progressive disclosure)
  cli.py                    configure / evaluate / demo
samples/                    upstream-shaped report + trusted merchant catalogue
tests/                      158 deterministic unit tests
```

## Authorization model

Three user values define the policy and only the user sets them. The shopping agent and the
purchase plans can never modify them.

- `maxPerTransaction` — Maximum amount the AI may spend in a single transaction (`> 0`)
- `maxDailySpend` — Maximum amount the AI may spend in one day (`> 0`)
- `confirmationThreshold` — Above what amount the AI must ask for confirmation
  (`>= 0` and `<= maxPerTransaction`)

```python
UserAuthorization(
    max_per_transaction=Money.parse("300.00"),
    max_daily_spend=Money.parse("1000.00"),
    confirmation_threshold=Money.parse("200.00"),
)
```

## Rule pipeline (one plan)

```text
1. validate plan data                  -> INVALID_PLAN_DATA (hard deny)
2. final total = subtotal + shipping + tax
3. merchant blacklist (exact id match) -> MERCHANT_BLACKLISTED (hard deny)
4. final total <= maxPerTransaction    -> MAX_PER_TRANSACTION (hard deny)
5. dailySpent + final total <= maxDailySpend -> MAX_DAILY_SPEND (hard deny)
6. merchant risk data present?         -> MERCHANT_RISK_DATA_UNAVAILABLE (hard deny)
   merchantRating < 60                 -> MERCHANT_RATING_LOW (ASK)
7. final total > confirmationThreshold -> CONFIRMATION_THRESHOLD_EXCEEDED (ASK)
```

Hard failures always take precedence over ASK conditions: a plan costing HKD 500 with a
merchant rating of 30 is **DENY**, never "low risk warning first".

Rule result:

```text
any HARD_DENY rule failed            -> DENY
no hard failure + any ASK rule fired -> ASK
nothing failed                       -> APPROVE
```

Boundaries are inclusive: `finalTotal == maxPerTransaction` and
`dailySpent + finalTotal == maxDailySpend` and `finalTotal == confirmationThreshold` all pass.

## Priority engine

Plans are evaluated strictly in the rank order supplied by the shopping agent (`1 -> 2 -> 3`).
Ranks are preserved; the engine never sorts by price or rating, never picks a cheaper
lower-ranked plan, and never inspects the product catalogue.

```text
Plan 1 APPROVE                        -> return Plan 1 (Plans 2 and 3 never evaluated)
Plan 1 DENY                           -> evaluate Plan 2
Plan 1 ASK, user confirms             -> return Plan 1 (stop)
Plan 1 ASK, user rejects              -> evaluate Plan 2
all plans denied/rejected             -> DENY
    "No suitable purchase plan is available under your current authorization settings."
```

## ASK handling

Two ways to answer an ASK:

```python
# 1. Inline provider (sync or async callable)
def confirm(evaluation) -> UserConfirmationResponse: ...
decision = firewall.evaluate_purchase_plans(
    FirewallRequest(plans=plans, context=context, confirmation_provider=confirm)
)

# 2. Suspend and resolve later
decision = firewall.evaluate_purchase_plans(FirewallRequest(plans=plans, context=context))
assert decision.status is DecisionStatus.ASK
decision = firewall.resolve_ask(decision.ask_id, UserConfirmationResponse(approved=True))
```

`UserConfirmationResponse(approved=True, blacklist_merchant=True)` authorizes the current
purchase **and** blacklists the merchant for future requests.

## Upstream report adapter

```text
Raw shopping report -> RequestReport per request_id -> PurchasePlan[] -> Firewall -> Decision
```

Enforced interpretation rules:

- different `request_id` values are separate authorization contexts and are never mixed;
- `best_options[].rank` is preserved; options without a valid rank are ignored; at most the
  three highest ranked options are considered; duplicate ranks keep the first option;
- a plan's own `total_cost` is its transaction total — report-level
  `totals.grand_total` is never used, and plans are never summed into one transaction;
- informational fields (`decision_rule`, `reason`, `considered`, `refused`, `stop_reason`,
  `model_backend`, `model_name`, `generated_at`) cannot influence authorization;
- product descriptions are untrusted text and are never policy;
- merchant risk scores are never read from the report — only the trusted catalogue or an
  internal service supplies them.

Missing merchant risk data is a hard denial (`MERCHANT_RISK_DATA_UNAVAILABLE`): missing
security-relevant data never silently becomes approval.

Catalogue format (`samples/merchant_catalog.json`):

```json
{
  "merchants": {
    "merchant-001": { "merchantName": "Kensington Direct",
                      "merchantCreditScore": 90, "buyerFeedbackScore": 78 }
  },
  "productMerchants": { "WM-022": "merchant-001" }
}
```

## Merchant safety rating

```text
merchantRating = merchantCreditScore * 0.60 + buyerFeedbackScore * 0.40   (rounded, 2 dp)

80-100 GOOD | 60-79 FAIR | 40-59 LOW | 0-39 VERY_LOW
```

`LOW` / `VERY_LOW` means a **low** safety rating and therefore higher risk. A rating below 60
produces ASK (never an automatic denial); the UI calls this the "Merchant Safety Rating".

## Audit trail

Every plan evaluation records: timestamp, session/request id, plan rank, product id, merchant
id, final total, daily spend before, projected daily spend, evaluated/passed/failed rules,
decision, reason, merchant credit score, buyer feedback score, merchant rating, risk level,
the user's confirmation result when an ASK occurred, and blacklist actions. Reasons are
derived from the recorded rule data — never regenerated by a model afterwards.

```python
audit = AuditService(path="audit.jsonl")     # optional JSONL persistence
engine = AuthorizationEngine(audit_service=audit)
```

## Simulated payment

Authorization ends at the transaction boundary. If checkout is exercised, it is simulated:

```text
PROPOSED -> AUTHORIZED -> CHECKOUT -> PAYMENT_PENDING -> COMPLETED
                ^                     (SIMULATED PAYMENT)
           only an APPROVE decision may authorize
```

`Transaction.authorize()` rejects ASK and DENY decisions with
`UnauthorizedTransactionError`, and `COMPLETED` is unreachable without passing through
`AUTHORIZED`. The core invariant holds: **no unauthorized purchase can become COMPLETED.**

## API reference

```python
FinancialFirewall(engine: AuthorizationEngine)
    .evaluate_purchase_plans(request: FirewallRequest) -> FirewallDecision
    .evaluate_purchase_plans_async(request: FirewallRequest) -> FirewallDecision
    .resolve_ask(ask_id: str, response: UserConfirmationResponse) -> FirewallDecision

AuthorizationEngine
    .evaluate_plan(plan, context) -> PlanEvaluation
    .order_plans(plans) -> tuple[PurchasePlan, ...]
    .evaluate_plans(plans, context, confirmation_provider=None) -> FirewallDecision
```

`FirewallDecision.to_dict()` produces the JSON contract, e.g.

```json
{ "status": "DENY",
  "reason": "No suitable purchase plan is available under your current authorization settings.",
  "failedRules": ["MERCHANT_BLACKLISTED", "MAX_PER_TRANSACTION", "MAX_DAILY_SPEND"],
  "planResults": [ { "rank": 1, "status": "DENY",
                     "failedRules": ["MAX_PER_TRANSACTION"],
                     "askReasons": [], "reason": "Final transaction total HKD 500.00 exceeds ..." } ] }
```

## Tests

```powershell
python -m unittest discover -s tests -t .        # 158 tests
python -m unittest discover -s tests -t . -v     # verbose
python -m compileall -q firewall tests           # syntax/build check
```

Coverage includes: transaction/daily/threshold boundaries at exactly the limit and one cent
above; shipping and tax pushing a plan over the limit; the full merchant rating band table;
missing and invalid risk data; blacklist hard denial, exact matching and blacklisting during
an ASK; combined ASK reasons; hard denial overriding ASK; the eight three-plan priority
scenarios; request-boundary and rank-preservation adapter rules; prompt-injection text in
descriptions; determinism (100 repeated runs, identical decisions and audit sequence); the
transaction invariant; and English-only rendering.

## Assumptions and deviations from the brief

1. **Python instead of TypeScript** — the request for this turn was "use python to
   programme", so the firewall is a dependency-free Python 3 package. The module layout
   mirrors the file structure suggested in the specification.
2. **`unittest`, not `pytest`** — the environment has no network access and no pytest
   installed, so the suite uses the standard library and runs anywhere Python 3.11+ does.
3. **CLI instead of a web UI** — there is no existing frontend in this workspace. The UI
   requirement (English only, progressive disclosure, the three ASK choices) is implemented
   in `firewall/ui.py` and the interactive CLI; a web layer can call the same API.
4. **Deterministic ask ids and audit ids** — `ask-0001`, `audit-000001` counters instead of
   random ids, so repeated runs are byte-identical apart from timestamps (which use an
   injectable clock).
5. **Extra audit fields** — `eventType`, `passedRules`, `riskLevel`, `askId` were added to the
   suggested audit event so the trail can explain an ASK and a blacklist action.
6. **`INVALID_PLAN_DATA` short-circuits** — when a plan is structurally invalid, downstream
   rules are not evaluated (nothing from untrustworthy data is used) and the plan is denied on
   data grounds alone.
7. **`evaluate` requires the three settings** — flags, a `firewall_state.json` written by
   `configure`, or an interactive console. Without any of them it fails fast with a clear
   message rather than blocking on stdin.
