# Guardrail — Agentic Commerce Frontend Prototype

A hackathon-ready React prototype showing how a user can delegate shopping to an AI agent while a deterministic policy layer retains final control over spending.

> **Safety:** all checkout and payment behavior is simulated. This project does not accept card details, banking credentials, or move real money.

## Quick start

Requirements: Node.js 20+ and npm.

```bash
npm install
npm run dev
```

Open the local URL printed by Vite (normally `http://localhost:5173`).

### Validation

```bash
npm run typecheck
npm test
npm run build
```

## Demo flow

Use the dark **Demo mode** bar at the top to load one of five repeatable cases:

1. **Allowed** — HK$219 + HK$20 shipping is authorized and completes.
2. **Over budget** — HK$280 + HK$30 shipping is denied against a HK$300 cap.
3. **Expired** — a low-cost purchase is denied because the mandate is expired.
4. **Revocation** — payment pauses in `PAYMENT_PENDING`; clicking **Revoke authorization** cancels it.
5. **Prompt injection** — malicious product text is treated as untrusted data and cannot override merchant restrictions.

Navigate through the five product areas: Mandate → Agent shop → Authorize → Result → Audit log.

## Project structure

Every source file now has a module header comment explaining its purpose, and key functions/handlers are annotated inline.

```text
src/
├── domain/types.ts          # Shared contracts; coordinate changes with backend team
├── data/
│   ├── catalog.ts           # Controlled dummy product catalog
│   └── scenarios.ts         # Repeatable demo fixtures
├── services/
│   ├── contracts.ts         # Stable frontend/backend interfaces (the integration seam)
│   ├── mockGateway.ts       # Deterministic local adapter + policy engine (dummy data)
│   ├── httpGateway.ts       # Real backend adapter scaffold (fill in your endpoints)
│   ├── index.ts             # Optional composition root (mock vs real via env flag)
│   └── mockGateway.test.ts  # Authorization engine tests
├── App.tsx                  # Flow orchestration + all five screens
├── styles.css               # Responsive visual system
├── main.tsx                 # React entry point
└── vite-env.d.ts            # Vite client types
```

## Where to add your backend data

Short version: **you only ever change `src/services/`.** The UI imports one gateway instance and never touches mock data directly.

1. **Products** → replace `src/data/catalog.ts` by implementing `getCatalog()` (see `httpGateway.ts`).
2. **LLM mandate parsing** → implement `interpretMandate()` → `POST /api/mandates/interpret`.
3. **Authorization** → move `evaluatePolicy()` to your server → `POST /api/authorization/evaluate`.
4. **Payment** → implement `startPayment()` / `completePayment()` endpoints.
5. **Audit** → implement `AuditRepository` against your store.

Then flip the import in `src/App.tsx` from `./services/mockGateway` to `./services/httpGateway` (or set `VITE_USE_MOCKS=false` and import from `./services`).

**Full instructions, JSON shapes, endpoint table, and the LLM / user-decision wiring are in [BACKEND_INTEGRATION.md](./BACKEND_INTEGRATION.md).**

For design rationale and the trust model, see [ARCHITECTURE.md](./ARCHITECTURE.md).

## Current prototype limitations

- State and audit events reset on page refresh.
- The LLM interpretation step is represented by pre-parsed scenario fixtures.
- Product inventory, merchant checkout, and payment are local simulations.
- Authentication and persistent storage are intentionally out of MVP scope.
