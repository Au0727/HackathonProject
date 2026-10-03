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
  authorize(mandate: Mandate, transaction: Transaction): Promise<AuthorizationResult>;
  startPayment(transaction: Transaction): Promise<Transaction>;
  completePayment(transaction: Transaction, mandate: Mandate): Promise<Transaction>;
}
```

`HttpCommerceGateway` also exposes `search()` and `revokeMandate()` for the
pipeline search and server-recorded revocation steps.

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
| `search()` | `POST /api/shopping/search` | `{ "intent": StructuredIntent, "max_results": number }` | Authorized selection report; `halts[]` carries stop reasons |
| `authorize(mandate, transaction)` | `POST /api/authorization/evaluate` | `{ "mandate": Mandate, "transaction": Transaction }` | `AuthorizationResult` |
| `startPayment(transaction)` | `POST /api/transactions/:id/payment/start` | `Transaction` | `Transaction` (`status: "PAYMENT_PENDING"`) |
| `revokeMandate(mandate)` | `PATCH /api/mandates/:id/revoke` | `{ "revokedAt": string }` | `{ "id": string, "revokedAt": string }` |
| `completePayment(transaction, mandate)` | `POST /api/transactions/:id/payment/complete` | `{ "transaction": Transaction, "mandate": Mandate }` | `Transaction` (`COMPLETED` or `CANCELLED`) |
| Audit read/write/clear | `GET/POST/DELETE /api/audit/logs` | `AuditEvent` for POST | `AuditEvent[]` for GET |

The natural-language prompt is sent unchanged. The separate UI spending limit
is merged into the structured intent; it is not appended to or used to rewrite
the prompt. Monetary values are transported as decimal strings. UI-facing
shapes are defined in **`src/domain/types.ts`**.

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

**Now:** `src/data/catalog.ts` exports a hard-coded array.
**To connect real data:** implement `getCatalog()` in `httpGateway.ts` and return your DB rows mapped to `Product[]`. Nothing else changes; the UI already renders whatever `getCatalog()` returns.

```ts
// src/services/httpGateway.ts
async getCatalog() {
  const res = await fetch(`${this.baseUrl}/api/catalog`);
  if (!res.ok) throw new Error('Catalog request failed');
  return (await res.json()) as Product[];
}
```

`App.tsx` loads this catalog into state using `commerceGateway.getCatalog()`.

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

The LLM's job is **interpretation only**. It converts free text into a `Mandate`. It never authorizes money.

### The exact data sent on button click

The LLM module needs exactly two things from the user. Both live in `App.tsx` state on **Screen 1**:

- `instruction` — the text from the natural-language textarea
- `priceLimit` — the "Maximum per purchase" number field

When the user clicks **"Activate mandate"**, the handler sends the instruction
unchanged as `prompt`. The separate spending limit is applied to the returned
structured intent without modifying the user prompt.

```ts
// src/App.tsx — runs when "Activate mandate" is clicked
const activateMandate = async () => {
  setBusy(true);
  setInterpretError(null);
  try {
    const parsed = await commerceGateway.interpretMandate({
      instruction,                          // from the textarea
      priceLimit: mandate.maxPerTransaction // from the price field
    });
    setMandate(parsed);          // the returned structured mandate fills the policy card
    appendAudit('MANDATE_INTERPRETED', 'AGENT', 'The agent interpreted your instruction into a spending mandate.', { input, mandate: parsed });
    setStep('shop');             // advance to the agent workspace
  } catch (err) {
    setInterpretError('The agent could not interpret that instruction. Please try rephrasing it.');
  } finally {
    setBusy(false);
  }
};
```

### Request / response

```
User types instruction + price limit, clicks "Activate mandate"
        │
        ▼
POST /api/mandates/interpret
  body: { "prompt": "Buy me a mouse under HK$300" }
        │   (server returns a validated StructuredIntent)
        ▼
Gateway maps the StructuredIntent to Mandate, then calls /api/shopping/search
        │
        ▼
Frontend stores it (setMandate) and shows the structured policy
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

Every user action in the demo already routes through a handler in `App.tsx`. These are your integration points. Each one is marked `[BACKEND-SEND]` in the code.

| User action | UI location | Handler in `App.tsx` | What to send to backend |
|---|---|---|---|
| Types an instruction | Screen 1 textarea | `setInstruction` | (kept in state until Activate) |
| **Activates mandate** | "Activate mandate" button | `activateMandate` | `POST /api/mandates/interpret` → save the `Mandate` |
| **Proposes purchase** | "Propose purchase" button | `propose` | Builds a transaction proposal; the server re-prices during authorization |
| **Runs authorization** | "Run authorization" button | `evaluate` | `POST /api/authorization/evaluate` |
| **Proceeds to payment** | "Proceed to simulated payment" | `checkout` | `POST /api/transactions/:id/payment/start` |
| **Revokes authority** | "Revoke authorization" button | `revoke` | Re-authorizes and completes with the revoked mandate; server cancels |
| Replays a scenario | "Replay scenario" button | `loadScenario` | (local reset; no backend needed) |
| Opens audit log | "View audit trail" button | `setStep('audit')` | `GET /api/audit/logs` |

### The critical ordering rule (revocation)

Revocation must be recorded **server-side before** payment can complete. Sequence:

```
1. User clicks "Revoke authorization"
2. Frontend/back: PATCH /api/mandates/:id/revoke   → sets revokedAt
3. Backend:       re-evaluate the pending transaction
4. Backend:       transition to CANCELLED (never COMPLETED)
```

The HTTP gateway calls the revoke route before re-authorizing and completing the
pending payment. The demo server records revoked mandate IDs in process memory
and checks that registry again at completion. A production deployment must
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
- [x] Transactions are re-priced from the trusted inventory and re-authorized
  before simulated payment completion.
- [x] Validate changes with `npm run typecheck && npm test && npm run build`.

The API prefers DeepSeek for intent extraction and optional product trust
audits, with deterministic offline fallback when the API is unavailable. Search,
ranking, spending caps, and Financial Firewall authorization are deterministic.
Payment and daily-spend state are process-local demo state, not suitable for
real transactions.
