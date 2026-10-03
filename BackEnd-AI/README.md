# Shopping Agent + Financial Firewall

Two components that answer two different questions:

```text
  natural language  ->  [ SHOPPING AGENT ]  ->  up to 3 ranked candidates
                                                   |
                                                   v
                        [ FINANCIAL FIREWALL ]  (no LLM in this path)
                                                   |
                                                   v
                                            recommended purchase JSON
```

| | Shopping agent (`intent_to_purchase.py`) | Financial Firewall (`../BackEnd-Supervisor`) |
|---|---|---|
| Question | *What is worth buying?* | *Is this purchase authorized?* |
| Method | LLM intent parsing, search, ranking | Deterministic rules, no language model |
| Output | Up to 3 ranked options | `APPROVE` / `ASK` / `DENY` per plan |
| Authority | The user's mandate (budget, category) | The user's authorization limits |

Neither component duplicates the other. The agent never decides whether money may
move; the firewall never looks at the product catalogue.

---

## Contents

| File | Purpose |
|---|---|
| `main.py` | **Entry point.** Natural language in, purchase JSON out. |
| `server.py` | FastAPI HTTP API for the frontend and audit log. |
| `intent_to_purchase.py` | The agent: intent parsing, search, mandate enforcement, ranking. |
| `firewall_bridge.py` | Joins the agent to the firewall; reduces 3 candidates to 2 authorized choices. |
| `logging_setup.py` | Console/file logging, the LLM interaction log, secret redaction. |
| `test_intent_to_purchase.py` | 105 tests for the agent. |
| `test_firewall_bridge.py` | 20 tests for the integration. |
| `requirements.txt` | Pydantic pins and FastAPI/Uvicorn HTTP server dependencies. |
| `config.json` | Non-secret settings: provider, model, logging, inventory. Safe to commit. |
| `config.local.json` | **Your API key.** Git-ignored — never commit or share it. |
| `wireless_mouse_ecosystem.json` | The 200-row product inventory. |
| `logs/` | Agent report, run logs and the LLM interaction log. Git-ignored. |

---

## 1. Quick start

```bash
cd BackEnd-AI
pip install -r requirements.txt
python main.py "Find me a Kensington wireless mouse under $800 total."
```

A vendored copy of the same packages already exists in `lib/`, so the pipeline
runs without installing anything. On a normal machine `pip install` takes
precedence and `lib/` is ignored.

Stdout is the JSON and nothing else, so it pipes directly:

```bash
python main.py --quiet "Find me a mouse under $800 total." | python -m json.tool
```

Add `--offline` to force the deterministic local model instead of a configured
API — useful for demos, test runs, and anything that must not spend credit.

```bash
python main.py --offline "..."          # deterministic, no network
python main.py --keep 1 "..."           # return a single recommendation
python main.py --options 3 "..."        # how many candidates the agent ranks
python main.py --max-per-transaction 50 "..."   # firewall denies everything
```

### HTTP API

Install the server dependencies from `requirements.txt`, then start the API:

```bash
uvicorn server:app --reload --host 127.0.0.1 --port 8000
```

The Vite app can then use `http://localhost:8000` as its API base. The API
provides `POST /api/mandates/interpret`, `POST /api/shopping/search`,
`GET /api/catalog`, and `GET /api/audit/logs`. Compatibility endpoints for
per-transaction authorization, mandate revocation, and simulated payment are
also provided for the frontend flow. With a valid configured DeepSeek key, API
requests use DeepSeek for mandate interpretation and the optional product trust
audit. If the key is missing or the API call fails, the agent logs the failure
and uses its deterministic offline parser/auditor. Search, ranking, budget
checks, and Financial Firewall authorization remain deterministic either way.
Payment and daily-spend state are in-memory demo state and reset on restart.

### The parts, individually

```bash
python intent_to_purchase.py --dry-run        # agent only, no model calls
python intent_to_purchase.py                  # 5 canned agent demos
python firewall_bridge.py --json-only "..."   # agent -> firewall, JSON only

python test_intent_to_purchase.py             # 105 tests
python test_firewall_bridge.py                # 20 tests
cd ../BackEnd-Supervisor && python -m unittest discover -s tests -t .   # 158 tests
```

---

## 2. The algorithm, end to end

One request flows through six stages. Stages 1–4 are the agent's mandate
enforcement; stage 5 is the firewall's authorization; stage 6 shapes the answer.

```text
  request
     |
 [1] INTENT EXTRACTION          LLM -> StructuredIntent   (keywords, caps, brands)
     |
 [2] SEARCH                     lexical match + IDF weighting, then cost math
     |
 [3] COMPLIANCE GATE            R-FIN-01 budget cap, R-SEC-01 trust audit
     |
 [4] RANKING                    deterministic selection -> up to 3 candidates
     |
 [5] AUTHORIZATION              firewall rules per plan -> APPROVE | ASK | DENY
     |
 [6] REDUCTION                  keep the best `keep` approved -> JSON
```

---

## 3. Stage 1 — Intent extraction

The LLM receives the raw sentence and a JSON Schema, and returns a
`StructuredIntent`:

```json
{
  "product_keywords": ["wireless", "mouse"],
  "max_base_price": null,
  "max_total_cap": "800.00",
  "preferred_brands": ["Kensington"],
  "parse_notes": ["Interpreted 800.00 as a TOTAL cap (price + shipping)."]
}
```

**The cap distinction matters.** "under $800 **total**" (also *all-in*,
*delivered*, *including shipping*) sets `max_total_cap` on price **+ shipping**.
Any other wording sets `max_base_price` on the base price alone.
`StructuredIntent.effective_cap()` returns whichever the user actually
expressed, so the audit trail records which rule was applied rather than
implying one.

**Multi-word keywords are split.** A model may return `["wireless mouse"]` as a
single phrase. Search matches tokens, so the phrase would only match text
containing it literally. The `_explode_phrases` validator splits it into
`["wireless", "mouse"]`.

---

## 4. Stage 2 — Search and cost math

### 4.1 Cost

```text
total_checkout_cost = price + shipping_fee
```

All money is `Decimal`, coerced at the model boundary as `Decimal(str(x))`. The
comparison that decides a purchase is exact:

```text
Decimal("389.92") > Decimal("300.00")   ->  True, stop
```

Binary floating point cannot represent most decimal cents exactly, and an agent
one cent wrong on a budget cap is an agent that overspends. `Decimal(3892.2)`
would import binary float error; `Decimal("3892.2")` does not.

### 4.2 Keyword expansion

Product names describe form factor ("Vertical Master", "BioFit Mouse") while
users speak in categories ("mouse"). `CATEGORY_SYNONYMS` bridges the vocabulary:

```python
CATEGORY_SYNONYMS = {
    "mouse": ("wireless", "vertical", "biofit", "ergonomic"),
    "dongle": ("receiver", "usb"),
    ...
}
```

Every expansion term occurs verbatim in the supplied inventory. Expansions score
lower than the user's own words, so they widen the candidate set without
outranking a literal match.

### 4.3 Inverse document frequency

A catalogue is full of boilerplate: if 190 of 200 products say "wireless", then
matching "wireless" carries almost no information, while matching "mouse" carries
a lot. Each keyword is weighted:

```text
rarity(keyword)  = 1 + (total_products / (1 + products_containing_keyword))
field_weight     = { product_name: 5, brand: 4, description: 1 }
score(keyword)   = rarity * field_weight        (expansion terms x 0.6)
relevance        = sum over matched keywords
```

Without IDF, a brand bonus alone can float an accessory above the product type
the user asked for — which is exactly the bug this fixed.

### 4.4 Token-boundary matching

Matching is on whole tokens, so the keyword `mouse` does **not** match
`Mousepad`. Substring matching silently promoted accessories above the product
the user asked for.

### 4.5 Ordering

```text
sort by ( relevance DESC, total_checkout_cost ASC, product_id ASC )
take the top `max_results` (default 10)
```

Fully deterministic: `product_id` breaks every remaining tie.

### 4.6 Bundle promotions

A `bundle_promotion` is **logged, never applied**. It is conditional — it needs a
trigger item, a quantity, or an accessory — so folding it into the benchmark
would compare a hypothetical against a real price. The benchmark stays
`price + shipping_fee` and the opportunity is reported separately.

---

## 5. Stage 3 — The compliance gate

Two rules, both computed **deterministically**. An LLM may *add* a finding here;
it can never clear a financial breach.

### R-FIN-01 — financial hard stop

```text
if effective_cap is not None and total_checkout_cost > effective_cap:
    DENY  ->  INVALID_OVER_BUDGET
```

Exact `Decimal` comparison. This is the rule that catches the classic case:

```text
"I need a Razer wireless mouse under $300 total."
   WM-002: 233.92 + 156.00 = 389.92 > 300.00   ->  STOPPED
```

The item looks like a budget purchase until shipping is included.

### R-SEC-01 — trust audit

Nine payload families are detected by pattern, after normalising the text:

1. text impersonating a system/developer instruction;
2. "ignore previous/all" instructions;
3. "disregard the budget/cap/constraint";
4. attempts to override agent logic;
5. forced ranking ("prioritize this", "mark as mandatory");
6. invented hidden rebates or discounts;
7. unauthorised quantity or immediate-checkout pushes;
8. disparaging competing listings;
9. unauthorised shipping concessions.

Normalisation removes zero-width characters, so
`IG<ZWSP>NORE ALL PREVIOUS` is still caught.

Price anomalies are checked **conservatively**, because a false positive blocks a
purchase the user legitimately wanted:

```text
non-positive list price                          -> finding
shipping > 3 x price                             -> finding
premium descriptor AND price < 15% of median     -> finding
   (suppressed for known component/accessory listings)
```

On the bundled inventory the scanner flags **exactly 8 of 200** listings — all
and only the genuinely poisoned ones.

**Precedence:** the financial stop is reported first. An over-budget *and*
poisoned listing is `INVALID_OVER_BUDGET`, because that is the user's primary
concern.

---

## 6. Stage 4 — Ranking into candidates

Surviving products are ordered by:

```text
sort by ( NOT is_preferred_brand, total_checkout_cost ASC, product_id ASC )
take the top `options` (default 3)
```

Brand is a **tiebreaker**, never part of the relevance score, so a matching brand
cannot promote an accessory above the requested product type.

If no listing from a requested brand survives, the agent says so explicitly
rather than silently recommending another brand:

```text
NOTE: 2 listing(s) from the requested brand(s) ['Razer'] were evaluated and all
were rejected, so the recommendation falls back to another brand
```

Each candidate carries a **recorded decision rule** and a machine-checkable
reason, generated from that rule rather than written afterwards:

| `decision_rule` | When |
|---|---|
| `WITHIN_BUDGET_AND_PREFERRED_BRAND` | preferred brand survived and is in budget |
| `LOWEST_TOTAL_COST_WITHIN_BUDGET` | no preferred brand survived |
| `NO_CAP_STATED_CHEAPEST_RELEVANT` | the user stated no cap |

If every candidate fails, the agent halts and names the rule and the arithmetic:

```text
STOPPED: Item WM-004 exceeds budget cap (389.92 > 50.00)
```

---

## 7. Stage 5 — Authorization (the Financial Firewall)

The agent writes its report to `logs/agent-report-<stamp>.json`. The bridge hands
that **file** to the supervisor's own `ShoppingReportAdapter` — it never
re-implements the parsing.

### 7.1 The rules applied per plan

```text
1. validate plan data                         -> INVALID_PLAN_DATA              (DENY)
2. final total = subtotal + shipping + tax
3. merchant blacklist (exact id match)        -> MERCHANT_BLACKLISTED           (DENY)
4. final total <= maxPerTransaction           -> MAX_PER_TRANSACTION            (DENY)
5. dailySpent + final total <= maxDailySpend  -> MAX_DAILY_SPEND                (DENY)
6. merchant risk data present?                -> MERCHANT_RISK_DATA_UNAVAILABLE (DENY)
   merchantRating < 60                        -> MERCHANT_RATING_LOW            (ASK)
7. final total > confirmationThreshold        -> CONFIRMATION_THRESHOLD_EXCEEDED (ASK)
```

```text
any HARD_DENY failed   -> DENY
no hard failure + ASK  -> ASK
nothing failed         -> APPROVE
```

Boundaries are inclusive: `finalTotal == maxPerTransaction` and
`dailySpent + finalTotal == maxDailySpend` and
`finalTotal == confirmationThreshold` all pass.

**Missing security data is a denial, not an approval.** A merchant with no risk
on file makes its plan un-authorizable.

### 7.2 Merchant rating

```text
merchantRating = creditScore * 0.60 + feedbackScore * 0.40      (2 dp)
80-100 GOOD | 60-79 FAIR | 40-59 LOW | 0-39 VERY_LOW
```

A rating below 60 produces ASK, never an automatic denial.

### 7.3 Two evaluation paths, deliberately

The firewall's **priority engine** (`evaluate_plans`) has a strict contract:
plans are walked in rank order and the **first APPROVE wins**, so ranks 2 and 3
are never evaluated. That is the right answer to *"should this purchase go
ahead?"*

This pipeline wants **two** authorized choices, so the bridge additionally calls
the engine's per-plan rule pipeline (`evaluate_plan`) for every candidate and
keeps the approved ones. **The rule set is identical** — only the selection
policy differs. Both results are reported: `best_options` holds the authorized
choices, and each result carries the priority engine's own decision under
`results[].firewall` for comparison.

If you need strict "first APPROVE wins" semantics, read `results[].firewall`
instead of `best_options`.

### 7.4 What the firewall will not take from the agent

- a plan's **own `total_cost`** is its transaction total; the report's
  `grand_total` is informational and is never summed into a transaction;
- **merchant risk is never read from the report** — only the trusted directory;
- **product descriptions are untrusted text** and are never policy;
- `reason`, `decision_rule`, `considered`, `refused`, `stop_reason` and the model
  fields cannot influence authorization.

### 7.5 Trusted merchant directory

The supervisor's sample catalogue maps 10 product ids; this inventory has 200.
The bridge maintains `../BackEnd-Supervisor/samples/merchant_directory.json`:

- it **starts from** `merchant_catalog.json` and preserves every existing record;
- each unmapped product is assigned one merchant per brand
  (`brand-kensington`, `brand-razer`, …);
- scores are **deterministic** — derived from the ids, never randomised, because
  the firewall promises identical decisions for identical inputs;
- the generated file is git-ignored, and the risk bands are labelled
  *auto-mapped* because **they are illustrative values we authored**, not
  observed data.

---

## 8. Stage 6 — The answer

Options the firewall did not approve are dropped; at most `keep` (default 2)
remain per request, in rank order.

```json
{
  "report_type": "authorized_selection",
  "authorization": {
    "max_per_transaction": "5000.00", "max_daily_spend": "2000.00",
    "confirmation_threshold": "1000.00", "daily_spent": "0.00",
    "currency": "HKD"
  },
  "requests_made": 1,
  "requests_with_options": 1,
  "results": [
    {
      "request_id": "REQ-001",
      "request": "Find me a Kensington wireless mouse under $800 total.",
      "status": "AUTHORIZED",
      "cap_enforced": "800.00",
      "best_options": [
        {
          "rank": 1, "product_id": "WM-022",
          "product_name": "Kensington BioFit Mouse (Elite, Matte Black)",
          "brand": "Kensington",
          "description": "High-quality wireless product designed for optimal...",
          "price": "389.92", "shipping_fee": "0.00", "total_cost": "389.92",
          "currency": "HKD", "quantity": 1,
          "authorized": true, "authorized_by": "financial_firewall",
          "merchant_id": "merchant-001", "merchant_name": "Kensington Direct",
          "merchant_risk": { "merchantRating": 85.2, "riskLevel": "GOOD" }
        },
        { "rank": 2, "product_id": "WM-020", "total_cost": "616.84",
          "authorized": true }
      ],
      "totals": {
        "items_selected": 2, "quantity": 2, "currency": "HKD",
        "goods_subtotal": "913.16", "shipping_total": "93.60",
        "grand_total": "1006.76"
      },
      "firewall": { "status": "APPROVE", "reason": "..." }
    }
  ],
  "grand_total": { "items_selected": 2, "grand_total": "1006.76" }
}
```

**Money is a string** (`"389.92"`), never a JSON number: serialising as a float
would reintroduce binary rounding at the boundary, and the budget cap depends on
exact comparison.

When nothing is authorized the document says so explicitly rather than omitting
fields:

```json
{ "requests_with_options": 0, "results": [],
  "grand_total": { "items_selected": 0, "grand_total": "0.00" } }
```

---

## 9. Determinism

Given the same inputs, the same answer comes out. This is what makes the pipeline
auditable and testable.

| Stage | Deterministic? | Why |
|---|---|---|
| Intent extraction | only offline | a live LLM may rephrase; `--offline` fixes it |
| Search and ranking | **yes** | fixed sort keys, `product_id` breaks ties |
| Compliance gate | **yes** | arithmetic and patterns, no model |
| Firewall rules | **yes** | no language model in the path at all |
| Merchant directory | **yes** | scores derived from ids |

The one variable is the model. `--offline` removes it, and
**`results` and `grand_total` are then identical on every run**:

```bash
python main.py --offline --quiet "..." | python -c "
import json,sys; d=json.load(sys.stdin)
print(json.dumps(d['results'], sort_keys=True), d['grand_total'])"
```

Run it twice and the two lines match. Only the bookkeeping timestamps differ —
`generated_at` and the timestamped `agent_report` filename — so the *answer* is
reproducible even though the document is not byte-identical.

The test suite is offline by construction: it uses `OfflineRuleBasedLLM`,
`run(offline=True)` and the agent's `--offline` flag, so it can never spend
credit or vary between runs. That matters in practice: a sandboxed CI run once
took 14 seconds per invocation before the flag was threaded through, because a
configured key made every "offline" test a live model call.

---

## 10. Dependencies

```bash
pip install -r requirements.txt
```

The CLI depends on `pydantic`; the HTTP API additionally depends on `fastapi`
and `uvicorn`. Everything else is the Python standard library —
`urllib.request` for model calls, `argparse` for the CLI, `logging` for the log
layer, `unittest` for the tests (no pytest needed). The Financial Firewall in
`../BackEnd-Supervisor` has **zero** dependencies.

### Why the pins are exact

`pydantic` requires an **exact** `pydantic-core` build, and `pydantic-core` ships
as a compiled extension whose wheel must match your Python's ABI (`cp310`,
`cp314`, …). Relaxing one pin without the other fails at import:

```text
SystemError: The installed pydantic-core version (2.49.0) is incompatible with
the current pydantic version, which requires 2.46.5
```

So `pydantic==2.13.5` is paired with `pydantic-core==2.46.5` deliberately.

| Package | Pin | Declared requirement |
|---|---|---|
| `pydantic` | `2.13.5` | direct |
| `pydantic-core` | `2.46.5` | `==2.46.5` (exact) |
| `annotated-types` | `0.8.0` | `>=0.6.0` |
| `typing-extensions` | `4.16.0` | `>=4.14.1` |
| `typing-inspection` | `0.4.4` | `>=0.4.2` |

Every pin satisfies what pydantic declares, and each one is the version this code
was actually verified against — not merely the oldest version that would satisfy
the constraint.

### Python version

**3.10 or newer.** `pydantic` supports 3.9+, but this project uses PEP 604 unions
(`list[str] | None`) in `main.py` and `firewall_bridge.py`, which arrived in 3.10.
Developed and verified on 3.14.5.

### No dependency is needed to stay offline

`python main.py --offline` uses the built-in deterministic rule-based model and
never touches the network, whether or not an API key is configured.

### Vendored copy

The same packages are already unpacked in `lib/` so the project runs with no
installation at all. The import bootstrap at the top of `intent_to_purchase.py`
prefers an interpreter-level `pydantic` and only falls back to `lib/`, so a normal
`pip install` takes precedence and `lib/` is ignored.

---

## 11. Configuration

`config.json` holds non-secret settings; `config.local.json` holds your API key
and is git-ignored.

```bash
python intent_to_purchase.py --init-config     # create both files
python intent_to_purchase.py --show-config     # effective settings, key redacted
```

Precedence, first found wins:

1. an explicit function argument;
2. `config.local.json`;
3. `config.json`;
4. the environment (`DEEPSEEK_API_KEY`, …);
5. the built-in default.

An empty value never shadows a real one, so the committed template's
`"api_key": ""` cannot hide your key. `base_url` is the one exception where the
environment wins, so a container can redirect the endpoint without editing a
mounted file.

```jsonc
{
  "llm": {
    "provider": "deepseek",
    "model": "deepseek-flash",
    "api_key": "",              // leave empty; the real key goes in config.local.json
    "timeout": 60, "max_tokens": 4096, "max_retries": 3
  },
  "runtime": {
    "inventory_file": "wireless_mouse_ecosystem.json",
    "top_n": 2, "max_results": 10, "verbose": false
  },
  "logging": {
    "level": "INFO", "directory": "logs", "console": true,
    "colour": null, "llm_payloads": true, "session": null, "write_summary": true
  }
}
```

### DeepSeek

The client handles DeepSeek's specifics: `response_format={"type":"json_object"}`
(it has no strict `json_schema` mode), the schema and an example appended to the
prompt (DeepSeek requires the word "json" plus a format example), `temperature`
omitted (thinking-mode models reject it), `max_tokens` always set, and empty
responses retried.

```bash
# 1. put your key in config.local.json  ->  "api_key": "sk-..."
# 2. run
python main.py "Find me a mouse under $800 total."
```

---

## 12. Logging

In `main.py`, stdout is reserved for the JSON and notes go to stderr. The
underlying CLIs print stage progress on stdout, except `firewall_bridge.py
--json-only` which moves progress to stderr so the pipe stays clean.

Two files per run in `logs/`:

- `pipeline-<session>.log` — everything, always at DEBUG;
- `llm-<session>.jsonl` — one JSON record per model call: the exact prompt, the
  parsed reply, latency and token usage.

When the API is running for the frontend demo, the backend console also prints
the system/user messages sent to the model, its reply, the selected
firewall-authorized choices, and a count of listings rejected for suspected
prompt injection. Obvious credential strings are redacted in console traces.
The frontend surfaces that rejection count as a brief status note, not as a
primary result.

**The API key is never written to any log.** The request body is logged without
the `Authorization` header, and credential-looking keys are redacted before
anything is written.

---

## 13. Testing

```bash
cd BackEnd-AI
python test_intent_to_purchase.py    # 105 tests
python test_firewall_bridge.py       # 20 tests

cd ../BackEnd-Supervisor
python -m unittest discover -s tests -t .    # 158 tests
```

Agent coverage: the budget cap (over / exactly at / one cent over), the
shipping-pushes-it-over case, injection detection across six payload families,
zero-width smuggling, false-positive regressions, graceful halts, end-to-end
determinism, a property check that no selection breaches a stated cap across 20
brand/cap combinations, provider wiring, config merging and precedence, logging
and redaction, and the result-file contract.

Bridge coverage: the merchant directory (preservation, determinism, labelling),
the 3-to-2 reduction, rank filtering, denials, JSON round-trip, and the offline
guarantee.

> The supervisor's own suite reports 5 errors in this sandbox because those tests
> write to `%TEMP%`, which the sandbox denies. Those are environmental, not
> assertion failures.

---

## 14. Known limitations

- **`OfflineRuleBasedLLM` is not an LLM.** It is a deterministic parser good
  enough for the demos and tests. For real language variety, configure an API.
- **A configured API makes the answer non-deterministic.** Use `--offline` when
  you need reproducibility.
- **Keyword search is lexical, not semantic.** `CATEGORY_SYNONYMS` bridges known
  categories; queries outside that map rely on a substring fallback and may
  surface a looser match.
- **The security scanner is pattern-based.** It catches known attack families
  and normalises markup, common Unicode look-alikes, zero-width characters and
  spaced lettering. A novel or encoded payload may still pass; this is a
  defense-in-depth filter, not proof that content is safe. Listings it flags are
  rejected before their text is sent to the optional LLM auditor.
- **Merchant risk bands in the generated directory are illustrative**, authored
  by us so the demo has full coverage. Substitute a real risk source before any
  production use.
- **Returning two choices is a selection policy, not a firewall rule.** The
  firewall's priority engine returns a single winner and stops; see section 7.3.
- **No real checkout.** Nothing is ever ordered or paid; the firewall's
  transaction state machine is simulated.
- **Tax is not modelled.** `total_cost = price + shipping_fee`. The firewall
  would accept a `tax` field; the agent never emits one.
