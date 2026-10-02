# Backend Integration Guide

This guide tells you **exactly where** to plug in your own backend data, **what shape** it must take, and **how** to connect the other modules (LLM mandate parsing, user decisions, audit logging).

---

## 0. The one-file integration seam

Everything the frontend needs from "the backend" is declared in one interface:

```ts
// src/services/contracts.ts
export interface CommerceGateway {
  getCatalog(): Promise<Product[]>;
  interpretMandate(instruction: string): Promise<Mandate>;
  authorize(mandate: Mandate, transaction: Transaction): Promise<AuthorizationResult>;
  startPayment(transaction: Transaction): Promise<Transaction>;
  completePayment(transaction: Transaction, mandate: Mandate): Promise<Transaction>;
}
```

The UI never imports mock data directly — it only imports an **instance**:

```ts
// src/App.tsx  (line ~35)
import { commerceGateway } from './services/mockGateway';
```

**To go live you change this single import** to your HTTP implementation. No screen or component changes.

```ts
import { commerceGateway } from './services/httpGateway';
```

A ready-to-fill scaffold already exists at **`src/services/httpGateway.ts`**.

---

## 1. Endpoint map (what to build on the backend)

| Gateway method | Suggested endpoint | Request body | Response body |
|---|---|---|---|
| `getCatalog()` | `GET /api/catalog` | — | `Product[]` |
| `interpretMandate(instruction)` | `POST /api/mandates/interpret` | `{ "instruction": string }` | `Mandate` |
| `authorize(mandate, transaction)` | `POST /api/authorization/evaluate` | `{ "mandate": Mandate, "transaction": Transaction }` | `AuthorizationResult` |
| `startPayment(transaction)` | `POST /api/transactions/:id/payment/start` | `Transaction` | `Transaction` (`status: "PAYMENT_PENDING"`) |
| `completePayment(transaction, mandate)` | `POST /api/transactions/:id/payment/complete` | `Transaction` | `Transaction` (`COMPLETED` or `CANCELLED`) |
| Audit read (optional) | `GET /api/audit` | — | `AuditEvent[]` |

All shapes are defined in **`src/domain/types.ts`**. Your JSON keys must match exactly.

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

> Note: the demo currently renders candidates via a direct `catalog` import in `App.tsx` (for instant rendering). When you go live, lift that list into `App` state and populate it from `commerceGateway.getCatalog()` in a `useEffect`.

### 3.2 Replace the pre-parsed mandate with real LLM output

**Now:** each entry in `src/data/scenarios.ts` hard-codes a `mandate` object.
**To connect the LLM:** implement `interpretMandate()` — see §4.

### 3.3 Move authorization to the server

**Now:** `evaluatePolicy()` in `src/services/mockGateway.ts`.
**To go live:** port that function to your backend and expose `POST /api/authorization/evaluate`. The frontend then just displays the returned `AuthorizationResult`.

### 3.4 Persist the audit log

**Now:** `MemoryAuditRepository` keeps events in memory (lost on refresh).
**To go live:** implement `AuditRepository` against your store, and have the backend append events itself so they are tamper-evident.

---

## 4. Integrating the LLM module (instruction → mandate)

The LLM's job is **interpretation only**. It converts free text into a `Mandate`. It never authorizes money.

### Flow

```
User types: "Buy me a mouse under HK$300, only approved merchants"
        │
        ▼
POST /api/mandates/interpret   { "instruction": "..." }
        │   (your server calls the LLM with a tool/JSON schema
        │    constrained to the Mandate type, then validates the output)
        ▼
Returns a validated Mandate object
        │
        ▼
Frontend stores it and shows the editable structured policy
```

### Wiring it in the UI

The textarea in **Screen 1 (`MandateSetup`)** already holds the text in `instruction` state. The handler is `activateMandate()` in `App.tsx` — a `[BACKEND-SEND]` site. Replace the current ("use the scenario's pre-parsed mandate") logic with:

```ts
const activateMandate = async () => {
  setBusy(true);
  try {
    const parsed = await commerceGateway.interpretMandate(instruction);
    setMandate(parsed);                         // show the structured policy
    appendAudit('MANDATE_INTERPRETED', 'AGENT', 'Agent interpreted your instruction into a spending mandate.', { parsed, instruction });
  } catch (err) {
    // show a friendly error, keep the user's text
  } finally {
    setBusy(false);
    setStep('shop');
  }
};
```

### Server-side requirements (important)

1. **Constrain the model output** to the `Mandate` schema (tool/function calling or JSON schema). Reject free-form text.
2. **Validate** the parsed mandate (types, positive numbers, valid ISO date) before returning it.
3. **Never** let the model set `revokedAt`, invent merchants, or widen limits beyond what the user stated.
4. Keep a `promptVersion` in the response/audit so you can explain how a mandate was produced.
5. The LLM proposes; the **deterministic engine** (§5) still decides ALLOW/DENY per transaction.

---

## 5. Sending user decisions to the backend

Every user action in the demo already routes through a handler in `App.tsx`. These are your integration points. Each one is marked `[BACKEND-SEND]` in the code.

| User action | UI location | Handler in `App.tsx` | What to send to backend |
|---|---|---|---|
| Types an instruction | Screen 1 textarea | `setInstruction` | (kept in state until Activate) |
| **Activates mandate** | "Activate mandate" button | `activateMandate` | `POST /api/mandates/interpret` → save the `Mandate` |
| **Proposes purchase** | "Propose purchase" button | `propose` | `POST /api/transactions` (server re-prices from trusted data) |
| **Runs authorization** | "Run authorization" button | `evaluate` | `POST /api/authorization/evaluate` |
| **Proceeds to payment** | "Proceed to simulated payment" | `checkout` | `POST /api/transactions/:id/payment/start` |
| **Revokes authority** | "Revoke authorization" button | `revoke` | `PATCH /api/mandates/:id/revoke`, then re-authorize + cancel |
| Replays a scenario | "Replay scenario" button | `loadScenario` | (local reset; no backend needed) |
| Opens audit log | "View audit trail" button | `setStep('audit')` | `GET /api/audit` (when you persist events) |

### The critical ordering rule (revocation)

Revocation must be recorded **server-side before** payment can complete. Sequence:

```
1. User clicks "Revoke authorization"
2. Frontend/back: PATCH /api/mandates/:id/revoke   → sets revokedAt
3. Backend:       re-evaluate the pending transaction
4. Backend:       transition to CANCELLED (never COMPLETED)
```

The mock reproduces this by re-running `authorize()` with the revoked mandate before `completePayment()`. Your server must do the same atomically (same DB transaction), so a mid-checkout revocation cannot be raced.

---

## 6. Environment & security

- Use Vite env vars for the API base URL: `VITE_API_BASE_URL`. See `.env.example`.
- **Never** put secrets (LLM API keys, payment keys) in `VITE_*` variables — they are bundled into the browser and public.
- Keep LLM keys on the server; the browser should only ever talk to **your** endpoints.
- The real server must **re-price and re-authorize** every transaction; never trust totals sent by the client.
- Payment must remain clearly labelled **SIMULATED** in all states.

---

## 7. Quick checklist to swap in your backend

- [ ] Implement `src/services/httpGateway.ts` (scaffold provided).
- [ ] Change the import in `src/App.tsx` from `mockGateway` to `httpGateway`.
- [ ] Move `evaluatePolicy()` logic to the server; keep the identical rule ids.
- [ ] Add `POST /api/mandates/interpret` with a schema-constrained LLM call.
- [ ] Add payment start/complete endpoints with idempotency keys and a server-side revocation re-check.
- [ ] Persist audit events server-side; expose `GET /api/audit`.
- [ ] Load catalog via `getCatalog()` instead of the direct `catalog` import.
- [ ] Re-run `npm run typecheck && npm test && npm run build`.
