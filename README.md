# Agentic Commerce + Financial Firewall

A full-stack demo of delegated shopping with a separate, deterministic financial
authorization layer. A user describes what they want in the React app; the
shopping agent finds and ranks candidates; the Financial Firewall checks whether
a proposed purchase is allowed. The agent can recommend products, but it cannot
authorize a transaction.

> **Demo only:** checkout and payment are simulated. The project does not accept
> payment credentials or move real money.

## Repository layout

```text
.
├── FrontEnd/                 React + TypeScript + Vite user interface
├── BackEnd-AI/               Python shopping pipeline and FastAPI service
└── BackEnd-Supervisor/       Deterministic Financial Firewall library and tests
```

The frontend connects to the API implemented in
[`BackEnd-AI/server.py`](./BackEnd-AI/server.py). The detailed component,
algorithm, and API documentation is in the
[backend README](./BackEnd-AI/README.md),
[firewall README](./BackEnd-Supervisor/README.md), and
[frontend integration guide](./FrontEnd/BACKEND_INTEGRATION.md).
The single cross-module reference for data flow, demonstration-data replacement
points, and diagnostics is [INTEGRATION.md](./INTEGRATION.md).

## Run the whole application

After completing the one-time setup below, you can launch both servers and open
the app in your browser with one command from the repository root:

```powershell
python .\main.py
```

The launcher uses the backend virtual environment, starts the API and Vite,
waits for both to respond, and opens `http://127.0.0.1:5173`. Press **Ctrl+C**
in the launcher terminal to stop both servers. It does not install dependencies
automatically; install them once as described below.

You need **Python 3.10 or newer**, **Node.js 20 or newer**, and npm. Run the API
and Vite development server in separate terminals only if you prefer not to use
the launcher.

### 1. Start the Python API

In PowerShell, from the repository root:

```powershell
cd .\BackEnd-AI
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn server:app --reload --host 127.0.0.1 --port 8000
```

The API is now available at `http://localhost:8000`. Interactive API
documentation is at `http://localhost:8000/docs`.

The server allows the Vite origins `http://localhost:5173` and
`http://127.0.0.1:5173`. Keep Vite on its default port unless you also update
the API's CORS configuration.

### 2. Start the React frontend

Open a second PowerShell terminal at the repository root:

```powershell
cd .\FrontEnd
npm install
npm run dev
```

Open the Vite URL printed in the terminal (normally
`http://localhost:5173`). The frontend uses the Python API at
`http://localhost:8000` by default. To use a different API address, set
`VITE_API_BASE_URL` in `FrontEnd/.env.local`, for example:

```dotenv
VITE_API_BASE_URL=http://localhost:8000
```

Restart Vite after changing environment variables. Do not put API keys or other
secrets in `VITE_*` variables; these values are visible to browser users.

## How it works

```text
User request
    │
    ▼
React frontend ── POST /api/mandates/interpret ──► Validated StructuredIntent
    │                                                  │
    │                 POST /api/shopping/search        │
    └──────────────────────────────────────────────────┘
                                                       ▼
                                      Search + compliance + ranking
                                                       │
                                                       ▼
                                      Financial Firewall authorization
                                                       │
                            authorized options or structured halt reason
                                                       ▼
                    User selects a proposal → re-price and re-authorize
                                                       │
                                                       ▼
                                  Simulated payment + audit trail
```

1. **Interpret the mandate.** The frontend sends the user's natural-language
   instruction unchanged to `POST /api/mandates/interpret`. Any separate UI
   spending limit is passed as structured policy data rather than inserted into
   or used to rewrite the prompt. The **Advanced Controls** panel is collapsed
   and blank by default; only values the user explicitly enters become extra
   mandate constraints.
2. **Search and rank.** The validated intent is submitted to
   `POST /api/shopping/search`. The agent searches the backend inventory,
   enforces the request's financial cap, and ranks candidates deterministically:
   relevance descending, total cost ascending, then `product_id` ascending.
3. **Authorize independently.** The Financial Firewall evaluates candidate
   purchase plans using deterministic rules and trusted merchant-risk data. It
   returns authorized selections or structured halt details; a shopping
   recommendation alone is not an authorization.
4. **Re-check the chosen transaction.** The backend obtains price and shipping
   from its own inventory and re-evaluates the authorization rather than
   trusting browser-supplied totals.
5. **Simulate payment and record events.** Checkout remains simulated. If the
   user revokes authority while payment is pending, the backend records the
   revocation before completing the flow, which results in cancellation. Audit
   events can be viewed in the app or fetched from the API.

Money amounts are serialized as decimal strings across the HTTP API to preserve
cents. Product descriptions and user-provided text are untrusted data, not
instructions to the authorization layer.

## API endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/catalog` | Read the backend product inventory |
| `POST /api/mandates/interpret` | Extract a structured intent from a prompt |
| `POST /api/shopping/search` | Search, rank, apply compliance checks, and authorize candidates |
| `POST /api/authorization/evaluate` | Evaluate a proposed transaction against policy |
| `POST /api/transactions/{id}/payment/start` | Start simulated payment |
| `POST /api/transactions/{id}/payment/complete` | Re-check and complete or cancel simulated payment |
| `PATCH /api/mandates/{id}/revoke` | Record mandate revocation |
| `GET /api/audit/logs` | Read the audit trail |

The API also provides `POST` and `DELETE /api/audit/logs` for audit event
write/clear operations used by the demo UI. See
[`FrontEnd/BACKEND_INTEGRATION.md`](./FrontEnd/BACKEND_INTEGRATION.md) for
request/response shapes and gateway details.

## Offline behavior and local configuration

The HTTP API uses the configured DeepSeek API for mandate interpretation and
optional candidate trust audits when credentials and service availability
permit. If no usable key is configured, or an API request fails, it logs the
failure and falls back to the deterministic offline parser/auditor. Product
search/ranking, financial hard stops, and Firewall authorization are
deterministic in either mode.

The optional `BackEnd-AI/config.local.json` is private local configuration and
must never be committed, pasted into documentation, or shared. It is not needed
to run the HTTP demo. The standalone Python CLI can use a configured model, so
use `--offline` for local demos and tests unless you intentionally want a live
model call:

```powershell
cd .\BackEnd-AI
.\.venv\Scripts\python.exe main.py --offline "Find me a wireless mouse under HK$800 total."
```

The API's payment, revocation, and daily-spend demo state is held in memory and
resets when the API process restarts. Authentication and durable transaction
storage are not part of this prototype.

## Run tests and checks

Run the frontend checks from `FrontEnd`:

```powershell
npm run typecheck
npm test
npm run build
```

Run the shopping-agent and API bridge tests from `BackEnd-AI`:

```powershell
.\.venv\Scripts\python.exe test_intent_to_purchase.py
.\.venv\Scripts\python.exe test_firewall_bridge.py
```

Run the Financial Firewall tests from the repository root:

```powershell
.\BackEnd-AI\.venv\Scripts\python.exe -m unittest discover -s .\BackEnd-Supervisor\tests -t .\BackEnd-Supervisor
```

## Troubleshooting

- **Frontend cannot reach the API:** confirm the API is running on port `8000`
  and `VITE_API_BASE_URL` has no trailing path beyond the server origin.
- **CORS error in the browser:** use the Vite origin `localhost:5173` or
  `127.0.0.1:5173`; the API only allows those development origins by default.
- **Vite selected another port:** stop any other Vite process or add that
  origin to `BackEnd-AI/server.py`'s CORS allowlist.
- **Python module or dependency error:** create the virtual environment and
  install `BackEnd-AI/requirements.txt` using the commands above.
- **No authorized product appears:** inspect the returned halt reason and the
  request's spending limit; a budget breach is a deliberate hard stop, not a
  server crash.
