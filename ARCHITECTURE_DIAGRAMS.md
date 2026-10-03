# Architecture Diagram: Frontend ↔ Backend Communication

This document provides visual explanations of how everything connects.

---

## Diagram 1: The Big Picture (Complete Flow)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER'S BROWSER                                 │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │                    React App (Frontend)                            │    │
│  │                                                                    │    │
│  │  App.tsx (UI Layer)                                              │    │
│  │  ├─ Screen 1: Mandate (textarea + number field)                 │    │
│  │  ├─ Screen 2: Agent shop (product list)                         │    │
│  │  ├─ Screen 3: Authorize (policy decision)                       │    │
│  │  ├─ Screen 4: Result (payment status)                           │    │
│  │  └─ Screen 5: Audit log (event trail)                           │    │
│  │                                                                    │    │
│  └──────────────────────────────┬─────────────────────────────────────┘    │
│                                 │                                           │
│                          imports from                                       │
│                                 │                                           │
│                                 ▼                                           │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │              services/contracts.ts (The Interface)                 │    │
│  │                                                                    │    │
│  │  export interface CommerceGateway {                               │    │
│  │    getCatalog(): Promise<Product[]>                              │    │
│  │    interpretMandate(input): Promise<Mandate>                     │    │
│  │    authorize(mandate, txn): Promise<AuthorizationResult>         │    │
│  │    startPayment(txn): Promise<Transaction>                       │    │
│  │    completePayment(txn, mandate): Promise<Transaction>           │    │
│  │  }                                                                 │    │
│  │                                                                    │    │
│  │  (App doesn't care if this is mock or HTTP — same interface!)   │    │
│  │                                                                    │    │
│  └──────────────────────────────┬─────────────────────────────────────┘    │
│                                 │                                           │
│        (choose one implementation by changing ONE import)                   │
│                                 │                                           │
│           ┌─────────────────────┴─────────────────────┐                    │
│           │                                           │                    │
│           ▼                                           ▼                    │
│  ┌──────────────────────┐              ┌──────────────────────────┐        │
│  │ services/mockGateway │              │ services/httpGateway     │        │
│  │ (DEV)                │              │ (PRODUCTION)             │        │
│  │                      │              │                          │        │
│  │ Returns hardcoded    │              │ Uses fetch() to call     │        │
│  │ JSON instantly (no   │              │ real HTTP endpoints      │        │
│  │ network)             │              │ (BASE_URL + /api/...)    │        │
│  │                      │              │                          │        │
│  │ Good for testing     │              │ ┌──────────────────────┐ │        │
│  │ UI before backend    │              │ │ async getCatalog()   │ │        │
│  │ is ready             │              │ │ async interpret...() │ │        │
│  │                      │              │ │ async authorize()    │ │        │
│  └──────────────────────┘              │ │ async startPayment() │ │        │
│                                        │ │ async complete...()  │ │        │
│                                        │ └──────────────────────┘ │        │
│                                        └──────────────────────────┘        │
│                                                │                           │
│                                                │ HTTP Fetch Requests       │
└────────────────────────────────────────────────┼───────────────────────────┘
                                                 │
                         ┌───────────────────────┘
                         │
                         │  POST /api/mandates/interpret
                         │  POST /api/authorization/evaluate
                         │  GET /api/catalog
                         │  POST /api/transactions/.../payment/start
                         │  POST /api/transactions/.../payment/complete
                         │
                         ▼
        ┌────────────────────────────────────────┐
        │      YOUR PYTHON BACKEND               │
        │      (Flask / Django / FastAPI)        │
        │                                        │
        │  @app.route('/api/catalog')            │
        │  def get_catalog():                    │
        │    return jsonify([products])          │
        │                                        │
        │  @app.route('/api/mandates/interpret') │
        │  def interpret_mandate():              │
        │    data = request.get_json()           │
        │    result = llm_parse(data)            │
        │    return jsonify(result)              │
        │                                        │
        │  @app.route('/api/authorization/...')  │
        │  def authorize():                      │
        │    ... policy engine logic ...         │
        │                                        │
        │  ... 2 more payment endpoints ...      │
        │                                        │
        └────────────────────────────────────────┘
```

---

## Diagram 2: Request/Response Cycle (Detailed)

Let's zoom in on ONE request: `interpretMandate()`

```
STEP 1: User Interaction (Browser)
┌─────────────────────────────────────────┐
│ User in Screen 1:                       │
│  - Types: "Buy me a mouse under HK$300" │
│  - Types: 300 (price limit)             │
│  - Clicks: "Activate mandate"           │
└────────────────────┬────────────────────┘
                     │
                     ▼
STEP 2: Frontend Code Runs (JavaScript)
┌────────────────────────────────────────────────────────┐
│ // src/App.tsx                                         │
│ const activateMandate = async () => {                  │
│   const result = await commerceGateway.interpretMandate({
│     instruction: "Buy me a mouse under HK$300",        │
│     priceLimit: 300                                    │
│   });                                                  │
│   setMandate(result);  // Update UI                    │
│ }                                                       │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
STEP 3: HTTP Fetch Request (Browser → Network)
┌────────────────────────────────────────────────────────┐
│ // src/services/httpGateway.ts                         │
│ async interpretMandate(input) {                        │
│   return postJson<Mandate>(                            │
│     '/api/mandates/interpret',                         │
│     input                                              │
│   );                                                   │
│ }                                                       │
│                                                        │
│ async function postJson<T>(path, body) {               │
│   const res = await fetch(                             │
│     'http://localhost:3000' + path,                    │
│     {                                                  │
│       method: 'POST',                                  │
│       headers: { 'Content-Type': 'application/json' }, │
│       body: JSON.stringify(body)                       │
│     }                                                  │
│   );                                                   │
│   return res.json();                                   │
│ }                                                       │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼ (Network)
┌────────────────────────────────────────────────────────┐
│ HTTP POST Request (what travels over the internet)     │
│                                                        │
│ POST http://localhost:3000/api/mandates/interpret      │
│                                                        │
│ Headers:                                               │
│   Content-Type: application/json                       │
│                                                        │
│ Body (JSON):                                           │
│ {                                                      │
│   "instruction": "Buy me a mouse under HK$300",        │
│   "priceLimit": 300                                    │
│ }                                                      │
│                                                        │
│ ▼▼▼ Network travels to backend ▼▼▼                    │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
STEP 4: Backend Receives (Python)
┌────────────────────────────────────────────────────────┐
│ # backend.py                                           │
│ @app.route('/api/mandates/interpret', methods=['POST'])│
│ def interpret_mandate():                               │
│   # Flask automatically parses JSON for us             │
│   data = request.get_json()                            │
│   # data = {                                           │
│   #   "instruction": "Buy me a mouse...",              │
│   #   "priceLimit": 300                                │
│   # }                                                  │
│                                                        │
│   instruction = data['instruction']                    │
│   price_limit = data['priceLimit']                     │
│                                                        │
│   # Process (call LLM, validate, etc.)                │
│   mandate = call_llm(instruction, price_limit)        │
│   response = {                                         │
│     "id": "mandate-abc123",                            │
│     "maxPerTransaction": 300,                          │
│     "allowedCategories": ["Computer Accessories"],     │
│     "expiresAt": "2027-12-31T23:59:59.000Z"           │
│   }                                                    │
│                                                        │
│   return jsonify(response), 200                        │
│ }                                                       │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼ (Network, response)
┌────────────────────────────────────────────────────────┐
│ HTTP Response (what comes back from server)            │
│                                                        │
│ Status: 200 OK                                         │
│                                                        │
│ Headers:                                               │
│   Content-Type: application/json                       │
│                                                        │
│ Body (JSON):                                           │
│ {                                                      │
│   "id": "mandate-abc123",                              │
│   "maxPerTransaction": 300,                            │
│   "allowedCategories": ["Computer Accessories"],       │
│   "expiresAt": "2027-12-31T23:59:59.000Z"             │
│ }                                                      │
│                                                        │
│ ◄◄◄ Network travels back to browser ◄◄◄              │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
STEP 5: Frontend Receives (JavaScript)
┌────────────────────────────────────────────────────────┐
│ // in postJson(), after fetch completes:              │
│ const res = await fetch(...)                           │
│ if (!res.ok) throw new Error(...)  // Error handling   │
│ return res.json()  // Parse JSON                       │
│                                                        │
│ // parsed = {                                          │
│ //   "id": "mandate-abc123",                           │
│ //   "maxPerTransaction": 300,                         │
│ //   ...                                               │
│ // }                                                   │
│                                                        │
│ // Back in activateMandate():                          │
│ const parsed = await interpretMandate({...});          │
│ setMandate(parsed);  // Store in React state           │
│                                                        │
│ // React re-renders Screen 1 with the new mandate ✅  │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
STEP 6: UI Updates (React)
┌────────────────────────────────────────────────────────┐
│ Screen 1 now shows:                                    │
│ ┌──────────────────────────────────────────┐          │
│ │ 💳 Spending Mandate                      │          │
│ │                                          │          │
│ │ Limit: HK$ 300 per purchase              │          │
│ │ Categories: Computer Accessories         │          │
│ │ Merchants: campus-tech, student-store    │          │
│ │ Expires: 2027-12-31                      │          │
│ │                                          │          │
│ │ [Next →]                                 │          │
│ └──────────────────────────────────────────┘          │
│                                                        │
│ ✅ Success! The mandate is now displayed             │
└────────────────────────────────────────────────────────┘
```

---

## Diagram 3: The Five Endpoints

```
┌─────────────────┐                 ┌──────────────────────────┐
│   Frontend UI   │                 │   Python Backend         │
│   (React)       │                 │   (Flask)                │
└────────┬────────┘                 └──────────────┬───────────┘
         │                                         │
         │ 1️⃣ Load Catalog                        │
         │ ──────────────────→ GET /api/catalog ──→ Product[]
         │                                         │
         │ 2️⃣ Interpret Instruction               │
         │ { instruction, priceLimit } ──→        │
         │ POST /api/mandates/interpret           │
         │ ──────────────────────────────→ Mandate │
         │◄─────────────────────────────────────────│
         │                                         │
         │ 3️⃣ Check Authorization                 │
         │ { mandate, transaction } ──→           │
         │ POST /api/authorization/evaluate       │
         │ ──────────────────────────────→ Authorization
         │◄─────────────────────────────────────────│ Result
         │                                         │
         │ 4️⃣ Start Payment                       │
         │ POST /api/transactions/:id/payment/start→ Transaction
         │ ──────────────────────────────→ (status: PAYMENT_PENDING)
         │◄─────────────────────────────────────────│
         │                                         │
         │ 5️⃣ Complete Payment                    │
         │ { transaction, mandate } ──→           │
         │ POST /api/transactions/:id/payment/complete
         │ ──────────────────────────────→ Transaction
         │◄─────────────────────────────────────────│ (status: COMPLETED
         │                                         │  or CANCELLED)
         │
         │ [Bonus] View Audit Log
         │ GET /api/audit ─────────────→ AuditEvent[]
         │◄─────────────────────────────────────────│
```

---

## Diagram 4: The Integration Seam (Swappable)

```
Same Interface, Two Implementations:

┌─────────────────────────────────────────────────────┐
│  src/services/contracts.ts                          │
│  ─────────────────────────────────────              │
│  export interface CommerceGateway { ... }           │
│                                                     │
│  (Both implementations conform to this interface)  │
└──────────────────┬────────────────────────────────┬─┘
                   │                                │
        ┌──────────┴──────────┐        ┌────────────┴─────────┐
        │                     │        │                      │
        ▼                     ▼        ▼                      ▼
┌──────────────────┐  ┌──────────────────┐  ┌─────────────────────┐
│ mockGateway.ts   │  │ httpGateway.ts   │  │ import/export path  │
│ ──────────────   │  │ ───────────────  │  │ ───────────────────  │
│ Development      │  │ Production       │  │ in App.tsx:         │
│                  │  │                  │  │                     │
│ Returns fake     │  │ Uses fetch() to  │  │ OLD (dev):          │
│ data instantly   │  │ call real HTTP   │  │ import { ... }      │
│ (in-memory)      │  │ endpoints on     │  │ from './services/   │
│                  │  │ your Python      │  │ mockGateway'        │
│ Good for:        │  │ backend          │  │                     │
│ - Testing UI     │  │                  │  │ NEW (prod):         │
│ - Development    │  │ Good for:        │  │ import { ... }      │
│ - No backend yet │  │ - Real data      │  │ from './services/   │
│                  │  │ - Real LLM       │  │ httpGateway'        │
│                  │  │ - Production     │  │                     │
└──────────────────┘  └──────────────────┘  └─────────────────────┘

                  ONE CHANGE = SWAP BACKEND ✅
```

---

## Diagram 5: Data Flow for One Complete Scenario

```
SCENARIO: User buys a mouse under HK$300

User Action #1: Fill mandate
┌─────────────────────────────────────────────────┐
│ Screen 1: Mandate Setup                         │
│ Instruction: "Buy me a quiet mouse under 300"   │
│ Price limit: 300                                │
│ [Activate mandate →]                            │
└─────────────┬───────────────────────────────────┘
              │
              ▼
Frontend calls:
  interpretMandate({
    instruction: "Buy me a quiet mouse under 300",
    priceLimit: 300
  })
              │
              ▼
Backend endpoint:
  POST /api/mandates/interpret
  ├─ Extract instruction & priceLimit from request
  ├─ Call LLM with instruction
  └─ Return structured mandate
              │
              ▼
Frontend updates:
  setMandate({
    id: "mandate-abc",
    maxPerTransaction: 300,
    allowedCategories: ["Computer Accessories"],
    expiresAt: "2027-12-31T..."
  })
              │
              ▼
┌─────────────────────────────────────────────────┐
│ Screen 1: Mandate Shown                         │
│ ✓ Limit: HK$300 per purchase                    │
│ ✓ Categories: Computer Accessories              │
│ [Shop →]                                        │
└─────────────┬───────────────────────────────────┘
              │
              ▼

User Action #2: Choose product
┌─────────────────────────────────────────────────┐
│ Screen 2: Agent Shop                            │
│ Product: QuietClick Mouse                       │
│ Price: HK$219                                   │
│ Shipping: HK$20                                 │
│ Total: HK$239                                   │
│ [Propose purchase →]                            │
└─────────────┬───────────────────────────────────┘
              │
              ▼
Frontend creates Transaction (local):
  {
    id: "txn-def",
    productId: "mouse-quiet",
    subtotal: 219,
    shipping: 20,
    total: 239,
    status: "PROPOSED"
  }
              │
              ▼
┌─────────────────────────────────────────────────┐
│ Screen 3: Authorize                             │
│ [Run authorization →]                           │
└─────────────┬───────────────────────────────────┘
              │
              ▼
Frontend calls:
  authorize(mandate, transaction)
              │
              ▼
Backend endpoint:
  POST /api/authorization/evaluate
  ├─ Check: Transaction total (239) ≤ mandate limit (300)? YES ✓
  ├─ Check: Expired? NO ✓
  ├─ Check: Revoked? NO ✓
  ├─ Check: Category allowed? YES ✓
  └─ Return: ALLOW
              │
              ▼
Frontend updates:
  decision: "ALLOW"
  reason: "All checks passed"
  ruleChecks: [
    { id: "MAX_PER_TRANSACTION", passed: true },
    { id: "EXPIRED", passed: true },
    ...
  ]
              │
              ▼
┌─────────────────────────────────────────────────┐
│ Screen 4: Result                                │
│ ✓ AUTHORIZED                                    │
│ ✓ HK$239 ≤ HK$300 limit                         │
│ [Proceed to payment →]                          │
└─────────────┬───────────────────────────────────┘
              │
              ▼
Frontend calls:
  startPayment(transaction)
              │
              ▼
Backend endpoint:
  POST /api/transactions/:id/payment/start
  └─ Update transaction status to PAYMENT_PENDING
              │
              ▼
Frontend updates:
  status: "PAYMENT_PENDING"
  (shows a "processing..." message with revoke option)
              │
              ▼
┌─────────────────────────────────────────────────┐
│ Screen 4: Payment Processing                    │
│ ⏳ Payment pending...                           │
│ [Confirm payment] [Revoke authorization]        │
└─────────────┬───────────────────────────────────┘
              │
User Action #3: Click "Confirm payment"
              │
              ▼
Frontend calls:
  completePayment(transaction, mandate)
              │
              ▼
Backend endpoint:
  POST /api/transactions/:id/payment/complete
  ├─ Re-check: Is mandate still valid?
  ├─  - Expired? NO ✓
  ├─  - Revoked? NO ✓
  └─ Status: COMPLETED
              │
              ▼
Frontend updates:
  status: "COMPLETED"
              │
              ▼
┌─────────────────────────────────────────────────┐
│ Screen 5: Audit Log                             │
│ ✓ MANDATE_INTERPRETED                           │
│ ✓ POLICY_EVALUATED                              │
│ ✓ PAYMENT_INITIATED                             │
│ ✓ PAYMENT_COMPLETED                             │
└─────────────────────────────────────────────────┘

🎉 SUCCESS! Transaction complete!
```

---

## Diagram 6: Where Each Technology Lives

```
Browser (JavaScript/TypeScript)
├─ React (UI)
│  └─ src/App.tsx
├─ Fetch API (HTTP)
│  └─ src/services/httpGateway.ts ← Makes the HTTP calls
├─ DevTools Network Tab ← See requests/responses
└─ Vite (dev server) ← http://localhost:5173

Network (Internet/TCP)
└─ JSON over HTTP
   └─ GET /api/... (no body)
   └─ POST /api/... (with JSON body)

Python Server
├─ Flask (web framework)
│  ├─ Receive HTTP requests
│  ├─ Parse JSON from request body
│  ├─ Process logic
│  └─ Return JSON response
├─ Your LLM (OpenAI, Claude, etc.)
│  └─ Called from /api/mandates/interpret endpoint
├─ Policy Engine (deterministic)
│  └─ Called from /api/authorization/evaluate endpoint
└─ Port 3000 ← http://localhost:3000
```

---

## Diagram 7: Error Handling Flow

```
Frontend sends request:
        │
        ▼
┌───────────────────────────────────┐
│ fetch() makes HTTP call           │
└───────────────┬───────────────────┘
                │
                ├─→ Network error (no internet)?
                │   └─→ catch block catches error
                │
                ├─→ 200-299 (Success)?
                │   └─→ Parse JSON, return data
                │
                ├─→ 400-499 (Client error)?
                │   └─→ res.ok = false
                │   └─→ throw Error
                │   └─→ catch block: show error message
                │
                └─→ 500+ (Server error)?
                    └─→ res.ok = false
                    └─→ throw Error
                    └─→ catch block: check backend logs
```

---

## Diagram 8: State Timeline (What Changes Over Time)

```
Timeline of React State in App.tsx:

┌─ Initial ─────────────────────────────────────────────────────┐
│ instruction: ""                                               │
│ mandate: { maxPerTransaction: 0 }                             │
│ step: "mandate"                                               │
│ busy: false                                                   │
└─────────────────────────────────────────────────────────────┬─┘
                                                               │
User types instruction: "Buy me a mouse"
setInstruction("Buy me a mouse")
                                                               │
│ instruction: "Buy me a mouse"                                │
│ mandate: { maxPerTransaction: 0 }                            │
│ step: "mandate"                                              │
│ busy: false                                                  │
└─────────────────────────────────────────────────────────────┬─┘
                                                               │
User types priceLimit: 300
setMandate({ maxPerTransaction: 300 })
                                                               │
│ instruction: "Buy me a mouse"                                │
│ mandate: { maxPerTransaction: 300 }                          │
│ step: "mandate"                                              │
│ busy: false                                                  │
└─────────────────────────────────────────────────────────────┬─┘
                                                               │
User clicks "Activate mandate"
activateMandate() called → setBusy(true)
                                                               │
│ instruction: "Buy me a mouse"                                │
│ mandate: { maxPerTransaction: 300 }                          │
│ step: "mandate"                                              │
│ busy: true  ← ⏳ Loading spinner shown                      │
└─────────────────────────────────────────────────────────────┬─┘
                                                               │
Backend returns Mandate
setMandate(parsed) → React state updated
setStep("shop") → Move to next screen
setBusy(false) → Hide spinner
                                                               │
│ instruction: "Buy me a mouse"                                │
│ mandate: {                                                   │
│   id: "mandate-abc123",                                      │
│   maxPerTransaction: 300,                                    │
│   allowedCategories: ["Computer Accessories"],               │
│   expiresAt: "2027-12-31T..."  ← ✅ From backend           │
│ }                                                            │
│ step: "shop"  ← Screen changed!                             │
│ busy: false                                                  │
└─────────────────────────────────────────────────────────────┬─┘
                                                               │
... continue through all screens ...
```

---

## Key Takeaways

1. **One Interface, Two Implementations**: Mock for dev, HTTP for prod
2. **JSON is the Language**: Objects ↔ Dictionaries
3. **Async/Await**: All network requests take time
4. **State Management**: React state updates when responses arrive
5. **The Seam**: `contracts.ts` is the contract both sides must keep
6. **Error Handling**: Always check `res.ok` and catch exceptions
7. **Deterministic Policy**: No LLM in the authorization decision
8. **Revocation Critical**: Must re-check before completing payment

**You now understand the full architecture!** 🚀
