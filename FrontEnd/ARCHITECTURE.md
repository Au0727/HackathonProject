# Architecture

## 1. Design objective

The application separates probabilistic recommendation from deterministic financial authorization:

```text
User instruction
      ↓
LLM interpretation / shopping agent  (may propose)
      ↓
Structured Mandate + Transaction
      ↓
Deterministic policy engine           (may authorize)
      ↓
Simulated merchant/payment state machine
      ↓
Recorded audit events
```

The UI never treats an AI recommendation as permission to spend.

## 2. Layers

### Presentation — `src/App.tsx` and `src/styles.css`

Owns screen state, accessible interactions, visual hierarchy, and progressive disclosure. It consumes typed services; it should not acquire backend business logic. The root `App()` component is the orchestrator: every user decision (`activateMandate`, `propose`, `evaluate`, `checkout`, `revoke`) is a `[BACKEND-SEND]` integration point, documented inline.

### Domain contracts — `src/domain/types.ts`

Contains the shared `Mandate`, `Product`, `Transaction`, `AuthorizationResult`, and `AuditEvent` contracts from the project specification. These are the compatibility boundary across frontend and backend. Contract changes should be deliberate and coordinated.

### Service boundary — `src/services/contracts.ts`

`CommerceGateway` describes every operation the UI requires. This dependency inversion lets the prototype switch from local fixtures to HTTP endpoints without rewriting screens.

`AuditRepository` similarly isolates event persistence. The current UI retains audit state in memory; a backend adapter can store and retrieve it.

### Local prototype adapter — `src/services/mockGateway.ts`

Provides deterministic asynchronous behavior so loading states and transaction transitions are realistic. `evaluatePolicy` checks final total, daily amount, merchant, category, expiry, revocation, and confirmation threshold. It returns recorded rule checks and a precise reason.

This implementation is for prototyping. In production, authorization and payment state transitions must run server-side and be atomic.

### Real backend adapter — `src/services/httpGateway.ts`

Scaffold implementing the same `CommerceGateway` over `fetch`. Fill in endpoint paths and switch the `App.tsx` import to go live. `src/services/index.ts` offers an env-driven switch (`VITE_USE_MOCKS`).

### Fixtures — `src/data`

`catalog.ts` contains controlled product data with source timestamps. `scenarios.ts` contains repeatable inputs for the exhibition flow. Fixtures never leak into the domain interface.

## 3. State machine

```text
PROPOSED
   ├─ policy DENY ───────────────────→ DENIED
   └─ policy ALLOW → AUTHORIZED → CHECKOUT → PAYMENT_PENDING
                                                ├─ valid authority → COMPLETED
                                                └─ revoked         → CANCELLED
```

A real implementation must reject invalid transitions and re-check the mandate immediately before `COMPLETED`. Client state is never authoritative.

## 4. Backend integration point

See **[BACKEND_INTEGRATION.md](./BACKEND_INTEGRATION.md)** for the full guide. Summary:

1. Implement `src/services/httpGateway.ts` against your endpoints.
2. Change the import in `src/App.tsx` from `./services/mockGateway` to `./services/httpGateway` (or set `VITE_USE_MOCKS=false` and import from `./services`).
3. Keep every request/response JSON in the shapes from `src/domain/types.ts`.

### Recommended API safeguards

1. Validate all payloads server-side against a shared schema.
2. Calculate totals server-side from trusted line items and shipping values.
3. Make authorization results immutable and reference a policy version.
4. Use idempotency keys for payment start/completion.
5. Re-check expiry and revocation inside the completion transaction.
6. Append audit events on the server, not from browser assertions.
7. Never put API secrets in frontend environment variables.

## 5. Scalability path

- **More rules:** add backend evaluators returning the same `RuleCheck` shape; render them from data.
- **More scenarios:** add fixture records without changing screen structure.
- **Persistent state:** implement `AuditRepository` and transaction repository over REST or a query library.
- **Authentication:** place session handling in the HTTP adapter; do not couple it to policy UI.
- **Multiple currencies:** add a money/value object and avoid raw number arithmetic before production.
- **Testing:** keep policy engine tests separate from component tests; add API contract tests when endpoints exist.

## 6. Trust boundaries

| Input | Trust level | Treatment |
|---|---|---|
| User mandate | Intent, not executable authority | Parse then validate into a strict schema |
| LLM output | Untrusted proposal | Validate; never authorize directly |
| Product content | Untrusted merchant data | Display safely; never interpret as instructions |
| Client transaction | Untrusted request | Reprice and re-evaluate on server |
| Policy engine result | Authoritative only when server generated | Store with policy version and evaluation timestamp |
| Payment simulator | Demo-only | Always label as simulated |

## 7. Known prototype trade-offs

The UI currently orchestrates transitions to make the frontend independently demonstrable. The mock policy function is intentionally deterministic and testable, but it must be replaced by the server endpoint for integration. Audit events are user-friendly demonstrations rather than tamper-resistant records.
