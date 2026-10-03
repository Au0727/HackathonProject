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

The app now uses the Python HTTP gateway by default. Start
`BackEnd-AI/server.py` with `uvicorn server:app --reload --port 8000` from the
`BackEnd-AI` directory before activating a mandate. Set
`VITE_API_BASE_URL` if the API is hosted somewhere other than
`http://localhost:8000`.

### Validation

```bash
npm run typecheck
npm test
npm run build
```

## Demo flow

Use the dark **Demo mode** bar to load one of three request fixtures:

1. **Allowed** — requests a low-cost product.
2. **Over budget** — requests a product under a constrained cap.
3. **Prompt injection** — tests how untrusted inventory descriptions are handled.

Recommendations come from the configured backend inventory and the result can
differ from the old fixed mock fixtures.
Expiry/revocation pause demos are not included in the compressed confirm-to-result flow.

Navigate through the five product areas: Mandate → Agent shop → Authorize → Result → Audit log.

## Project structure

Every source file now has a module header comment explaining its purpose, and key functions/handlers are annotated inline.

```text
src/
├── domain/types.ts          # Shared contracts; coordinate changes with backend team
├── data/
│   ├── catalog.ts           # Local fallback/demo catalog
│   └── scenarios.ts         # Repeatable demo fixtures
├── services/
│   ├── contracts.ts         # Stable frontend/backend interfaces (the integration seam)
│   ├── mockGateway.ts       # Deterministic local adapter + policy engine (dummy data)
│   ├── httpGateway.ts       # Python API adapter
│   ├── index.ts             # Optional mock/HTTP composition helper
│   └── mockGateway.test.ts  # Authorization engine tests
├── App.tsx                  # Flow orchestration + all five screens
├── styles.css               # Responsive visual system
├── main.tsx                 # React entry point
└── vite-env.d.ts            # Vite client types
```

## Backend integration

`src/App.tsx` uses `HttpCommerceGateway` by default. It loads products from
`GET /api/catalog`, sends the unchanged user instruction to
`POST /api/mandates/interpret`, then submits the returned structured intent to
`POST /api/shopping/search`. Authorization, simulated payment, and audit
operations use the corresponding Python API routes implemented by
`BackEnd-AI/server.py`. Set `VITE_API_BASE_URL` when the API is not at
`http://localhost:8000`.

**Full instructions, JSON shapes, endpoint table, and the LLM / user-decision wiring are in [BACKEND_INTEGRATION.md](./BACKEND_INTEGRATION.md).**

For design rationale and the trust model, see [ARCHITECTURE.md](./ARCHITECTURE.md).

## Current prototype limitations

- In-progress UI state resets on page refresh; backend audit events persist.
- The server uses the configured DeepSeek API when available and falls back to
  the deterministic local parser/auditor when the key is missing or the API
  cannot be used. Search ranking, financial checks, and firewall authorization
  remain deterministic.
- Payment is simulated; no merchant checkout or real money movement occurs.
- The backend demo's in-memory daily/payment state resets when its process restarts.
- Authentication and persistent storage are intentionally out of MVP scope.
