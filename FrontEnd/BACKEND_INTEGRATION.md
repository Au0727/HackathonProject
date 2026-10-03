# Backend Integration Guide

The frontend is connected to `BackEnd-AI/server.py` through
`src/services/httpGateway.ts`. This document retains the original adapter
contracts and records the implemented Python API routes.

---

## 0. The one-file integration seam

Everything the frontend needs from "the backend" is declared in one interface:

```ts
// src/services/contracts.ts
export interface CommerceGateway {
  getCatalog(): Promise<Product[]>;
  interpretMandate(input: MandateInterpretationInput): Promise<Mandate>;
  search(mandate: Mandate, maxResults?: number): Promise<Product[]>;
  authorize(mandate: Mandate, transaction: Transaction): Promise<AuthorizationResult>;
  startPayment(transaction: Transaction): Promise<Transaction>;
  completePayment(transaction: Transaction, mandate: Mandate): Promise<Transaction>;
}
```

`HttpCommerceGateway` also exposes `revokeMandate()` for the API route; the
current UI does not expose a revoke control.

The app currently instantiates its HTTP gateway:

```ts
import { HttpCommerceGateway } from './services/httpGateway';
```

The mock adapter remains available for isolated local tests.

---

## 1. Implemented endpoint map

| Gateway operation | Python endpoint | Request body | Response body |
|---|---|---|---|
| `getCatalog()` | `GET /api/catalog` | — | `Product[]` (money fields are decimal strings on the wire) |
| `interpretMandate(input)` | `POST /api/mandates/interpret` | `{ "prompt": string }` | `StructuredIntent`; gateway maps it to `Mandate` |
| `search()` | `POST /api/shopping/search` | `{ "intent": StructuredIntent, "mandate": Mandate, "max_results": number }` | Authorized selection report; `halts[]` carries stop reasons |
| `authorize(mandate, transaction)` | `POST /api/authorization/evaluate` | `{ "mandate": Mandate, "transaction": Transaction }` | `AuthorizationResult` |
| `startPayment(transaction)` | `POST /api/transactions/:id/payment/start` | `Transaction` | `Transaction` (`status: "PAYMENT_PENDING"`) |
| `revokeMandate(mandate)` | `PATCH /api/mandates/:id/revoke` | `{ "revokedAt": string }` | `{ "id": string, "revokedAt": string }` |
| `completePayment(transaction, mandate)` | `POST /api/transactions/:id/payment/complete` | `{ "transaction": Transaction, "mandate": Mandate }` | `Transaction` (`COMPLETED` or `CANCELLED`); server uses its stored ALLOW mandate snapshot |
| Audit read/write/clear | `GET/POST/DELETE /api/audit/logs` | `AuditEvent` for POST | `AuditEvent[]` for GET |

The natural-language prompt is sent unchanged. A UI total limit is merged into
the intent's total cap without changing a separate base-price cap. The complete
structured mandate is also sent to search so its transaction/day limits,
category, merchant, and expiry restrictions apply before recommendations are
returned. Monetary values are transported as decimal strings. UI-facing shapes
are defined in **`src/domain/types.ts`**.

---

## 2. Data shapes you must return (with examples)

### 2.1 `Product` — catalog items

```json
{
  "id": "mouse-quiet",
  "name": "QuietClick Wireless Mouse",
  "category": "Computer Accessories",
  "merchantId": "campus-tech",
  "merchantName": "Campus Tech",
  "price": 219,
  "shipping": 20,
  "currency": "HKD",
  "rating": 4.8,
  "description": "Silent clicks, Bluetooth and USB receiver.",
  "source": "Observed 2026-09-15",
  "observedAt": "2026-09-15T09:00:00.000Z"
}
```

Rules:
- `merchantId` is what the policy engine checks against `mandate.allowedMerchants` — the display name is separate.
- `price` + `shipping` = the final total that gets authorized. Never fold shipping into `price`.
- `description` is **untrusted merchant text**. Never feed it to the LLM as instructions.
- `source` / `observedAt` are optional but recommended for hackathon transparency.

### 2.2 `Mandate` — structured spending authority

```json
{
  "id": "mandate-abc123",
  "maxPerTransaction": 300,
  "maxDailySpend": 600,
  "allowedCategories": ["Computer Accessories"],
  "allowedMerchants": ["campus-tech", "student-store"],
  "requiresConfirmationAbove": 250,
  "expiresAt": "2027-12-31T23:59:59.000Z"
}
```

- All fields except `id` and `expiresAt` are optional.
- `revokedAt` is added later when the user revokes.

### 2.3 `AuthorizationResult` — the deterministic verdict

```json
{
  "decision": "DENY",
  "reason": "Final transaction total HK$310 exceeds the authorized per-transaction limit of HK$300.",
  "failedRules": ["MAX_PER_TRANSACTION"],
  "evaluatedAt": "2026-10-02T09:41:21.742Z",
  "mandateId": "mandate-over-budget",
  "ruleChecks": [
    { "id": "MAX_PER_TRANSACTION", "label": "Final total", "passed": false, "detail": "HK$310 exceeds the HK$300 limit." },
    { "id": "MERCHANT", "label": "Approved merchant", "passed": true, "detail": "Merchant is on your approved list." }
  ]
}
```

- `ruleChecks` drives the ✓ / ✕ list shown to the user.
- `reason` is shown prominently on denial, word-for-word. Make it precise.

### 2.4 `Transaction` — proposed/executed purchase

```json
{
  "id": "txn-abc123",
  "productId": "mouse-pro",
  "merchantId": "campus-tech",
  "subtotal": 280,
  "shipping": 30,
  "total": 310,
  "currency": "HKD",
  "status": "PROPOSED",
  "createdAt": "2026-10-02T09:40:30.605Z"
}
```

Allowed `status` values: `PROPOSED`, `AUTHORIZED`, `CHECKOUT`, `PAYMENT_PENDING`, `COMPLETED`, `DENIED`, `CANCELLED`.

### 2.5 `AuditEvent` — recorded decision trail

```json
{
  "id": "audit-abc123",
  "transactionId": "txn-abc123",
  "timestamp": "2026-10-02T09:41:21.742Z",
  "eventType": "POLICY_EVALUATED",
  "actor": "POLICY_ENGINE",
  "summary": "Final transaction total HK$310 exceeds the authorized per-transaction limit of HK$300.",
  "data": { "decision": "DENY", "failedRules": ["MAX_PER_TRANSACTION"], "policyVersion": "2026.1" }
}
```

`actor` must be one of `USER`, `AGENT`, `POLICY_ENGINE`, `MERCHANT`, `PAYMENT_SIMULATOR`.

---

## 3. Where to add your own backend data (concrete steps)

### 3.1 Replace the product catalog

**Now:** `GET /api/catalog` maps the configured BackEnd-AI inventory and the
supervisor's trusted merchant mapping into `Product[]`. The frontend fixture at
`src/data/catalog.ts` remains demo/test data.
**To connect a real catalogue:** replace the inventory source selected by
`BackEnd-AI/config.json` and supply trustworthy product category, merchant,
price, shipping, and observation values through `BackEnd-AI/server.py`'s
`get_catalog()` mapper. The UI-facing contract remains `Product[]`.

`App.tsx` loads the catalog using `commerceGateway.getCatalog()`.

### 3.2 Replace the pre-parsed mandate with real LLM output

Scenario mandates seed the editable policy fields. Activating a mandate now
calls the Python interpreter and the returned structure is used for search.

### 3.3 Move authorization to the server

The live gateway sends evaluation to `POST /api/authorization/evaluate`. The
server uses the supervisor Firewall and reprices against its trusted inventory.

### 3.4 Persist the audit log

Frontend audit events are appended to `POST /api/audit/logs`; `GET
/api/audit/logs` also includes parsed pipeline logs and agent reports.

---

## 4. Integrating the LLM module (instruction → mandate)

The LLM's job is **interpretation only**. It returns a validated
`StructuredIntent`, not spending authority; deterministic server code and the
supervisor make authorization decisions.

### The exact data sent on button click

The interpretation endpoint receives the natural-language instruction. The
optional UI per-purchase total limit is retained by the gateway and combined
with a parsed total cap after interpretation:

- `instruction` — the text from the natural-language textarea
- `priceLimit` — the "Maximum per purchase" number field

When the user clicks **"Activate mandate"**, the instruction is sent unchanged
as `prompt`. The UI total limit does not rewrite it. A natural-language base
price cap remains a base-price cap; only a total cap or explicit UI total limit
becomes the mandate's final-total limit.

```ts
// src/App.tsx — runs when "Activate mandate" is clicked
const activateMandate = async () => {
  setBusy(true);
  setInterpretError(null);
  try {
    const parsed = await commerceGateway.interpretMandate({ instruction, priceLimit });
    const nextMandate = { ...parsed, ...explicitOverrides };
    setMandate(nextMandate);
    const recommendations = await commerceGateway.search(nextMandate);
    setProducts(recommendations);
  } catch (err) {
    setInterpretError('The agent could not interpret that instruction. Please try rephrasing it.');
  } finally {
    setBusy(false);
  }
};
```

### Request / response

```
User enters instruction and optional policy overrides
        │
        ▼
POST /api/mandates/interpret
  body: { "prompt": "Buy me a mouse under HK$300" }
        │   (server returns a validated StructuredIntent)
        ▼
Gateway combines the intent and mandate, then sends
{ intent, mandate, max_results } to /api/shopping/search
        │
        ▼
Server filters inventory and applies transaction/day limits before returning
supervisor-approved candidates
```

### Two interchangeable implementations (same interface)

The gateway interface is `interpretMandate(input: MandateInterpretationInput): Promise<Mandate>`. Two adapters implement it:

- **Current app:** `HttpCommerceGateway.interpretMandate` calls
  `POST /api/mandates/interpret`; the server uses the configured DeepSeek API
  when available and falls back to the offline deterministic parser on failure.
- **Mock tests:** `MockCommerceGateway` remains available to unit tests.

The app uses the HTTP gateway by default.

### Server-side requirements (important)

1. The server validates extracted intent against `StructuredIntent`.
2. The HTTP API prefers DeepSeek when configured; API errors trigger an
   explicitly logged switch to deterministic offline interpretation/auditing.
3. The returned intent is a proposal; the deterministic Firewall still
   authorizes individual purchases.

---

## 5. Sending user decisions to the backend

The currently implemented UI actions route through `App.tsx`. The revoke API
exists but is not presented as a user action in this compressed flow.

| User action | UI location | Handler in `App.tsx` | What to send to backend |
|---|---|---|---|
| Types an instruction | Screen 1 textarea | `setInstruction` | (kept in state until Activate) |
| **Activates mandate** | "Activate mandate" button | `activateMandate` | `POST /api/mandates/interpret` → save the `Mandate` |
| **Confirms a purchase** | Confirm purchase control | `confirmPurchase` | Builds a proposal and calls `POST /api/authorization/evaluate` |
| **Starts simulated payment** | Same confirm flow after ALLOW | `confirmPurchase` | `POST /api/transactions/:id/payment/start` |
| **Completes simulated payment** | Same confirm flow | `confirmPurchase` | `POST /api/transactions/:id/payment/complete` |
| Replays a scenario | "Replay scenario" button | `loadScenario` | (local reset; no backend needed) |
| Opens audit log | "View audit trail" button | `setStep('audit')` | `GET /api/audit/logs` |

The demo server records revoked mandate IDs in process memory and checks that
registry during search and final authorization. A production deployment must
persist revocations and transaction state atomically.

---

## 6. Environment & security

- Use Vite env vars for the API base URL: `VITE_API_BASE_URL`. See `.env.example`.
- **Never** put secrets (LLM API keys, payment keys) in `VITE_*` variables — they are bundled into the browser and public.
- Keep LLM keys on the server; the browser should only ever talk to **your** endpoints.
- The real server must **re-price and re-authorize** every transaction; never trust totals sent by the client.
- Payment must remain clearly labelled **SIMULATED** in all states.

---

## 7. Integration status

- [x] HTTP gateway is the active adapter in `src/App.tsx`.
- [x] Catalog, mandate interpretation, search, authorization, simulated payment,
  mandate revocation, and audit routes are implemented by `BackEnd-AI/server.py`.
- [x] Search receives the complete mandate and applies filters and spending
  limits before recommendations are returned.
- [x] The unsupported supervisor `ASK` outcome is mapped to DENY; it cannot
  become a successful simulated payment.
- [x] Payment start/completion require the server-side authorization snapshot
  and reject changed transaction amounts or product identity.
- [x] Transactions are re-priced from the trusted inventory and re-authorized
  before simulated payment completion.
- [x] Validate changes with `npm run typecheck && npm test && npm run build`.

The API prefers DeepSeek for intent extraction and optional product trust
audits, with deterministic offline fallback when the API is unavailable. Search,
ranking, spending caps, and Financial Firewall authorization are deterministic.
Payment and daily-spend state are process-local demo state, not suitable for
real transactions.
