# Quick Reference: Frontend-Backend GET/POST Requests

## One-Page Cheat Sheet

### The HTTP Verbs

| Verb | Purpose | Example |
|------|---------|---------|
| **GET** | Request data, no body | `GET /api/catalog` |
| **POST** | Send data, with body | `POST /api/mandates/interpret` + `{ instruction, priceLimit }` |

---

## Your 5 Endpoints (Copy-Paste Template)

### 1. Get Product Catalog

```typescript
// Frontend: httpGateway.ts
async getCatalog(): Promise<Product[]> {
  const res = await fetch(`${BASE_URL}/api/catalog`);
  if (!res.ok) throw new Error('Failed');
  return (await res.json()) as Product[];
}
```

```python
# Backend: Flask route
@app.route('/api/catalog', methods=['GET'])
def get_catalog():
    return jsonify([
        {
            "id": "mouse-quiet",
            "name": "QuietClick Mouse",
            "price": 219,
            "shipping": 20,
            "merchantId": "campus-tech",
            # ... more fields
        }
    ]), 200
```

---

### 2. Interpret Mandate (User's Natural Language → Structured Rules)

```typescript
// Frontend: httpGateway.ts
async interpretMandate(input: MandateInterpretationInput): Promise<Mandate> {
  return postJson<Mandate>('/api/mandates/interpret', input);
}
```

```python
# Backend: Flask route
@app.route('/api/mandates/interpret', methods=['POST'])
def interpret_mandate():
    data = request.get_json()  # { instruction, priceLimit }
    
    # Call LLM to parse the instruction
    mandate = llm_parse(data['instruction'], data['priceLimit'])
    
    return jsonify({
        "id": "mandate-123",
        "maxPerTransaction": data['priceLimit'],
        "allowedCategories": mandate['categories'],
        "expiresAt": "2027-12-31T23:59:59.000Z"
    }), 200
```

---

### 3. Evaluate Authorization (Policy Engine Decision)

```typescript
// Frontend: httpGateway.ts
async authorize(mandate: Mandate, transaction: Transaction): Promise<AuthorizationResult> {
  return postJson<AuthorizationResult>('/api/authorization/evaluate', 
    { mandate, transaction }
  );
}
```

```python
# Backend: Flask route
@app.route('/api/authorization/evaluate', methods=['POST'])
def authorize():
    data = request.get_json()  # { mandate, transaction }
    
    # Deterministic policy check
    passed_max_price = data['transaction']['total'] <= data['mandate']['maxPerTransaction']
    
    return jsonify({
        "decision": "ALLOW" if passed_max_price else "DENY",
        "reason": "...",
        "failedRules": [] if passed_max_price else ["MAX_PER_TRANSACTION"],
        "evaluatedAt": datetime.now().isoformat() + 'Z',
        "mandateId": data['mandate']['id'],
        "ruleChecks": [
            {
                "id": "MAX_PER_TRANSACTION",
                "label": "Final total",
                "passed": passed_max_price,
                "detail": f"Total {data['transaction']['total']} vs limit {data['mandate']['maxPerTransaction']}"
            }
        ]
    }), 200
```

---

### 4. Start Payment

```typescript
// Frontend: httpGateway.ts
async startPayment(transaction: Transaction): Promise<Transaction> {
  return postJson<Transaction>(`/api/transactions/${transaction.id}/payment/start`, transaction);
}
```

```python
# Backend: Flask route
@app.route('/api/transactions/<txn_id>/payment/start', methods=['POST'])
def start_payment(txn_id):
    data = request.get_json()
    
    # Mark as PAYMENT_PENDING in DB
    transaction = db.update_transaction(txn_id, status='PAYMENT_PENDING')
    
    return jsonify({
        "id": transaction.id,
        "status": "PAYMENT_PENDING",
        # ... other fields
    }), 200
```

---

### 5. Complete Payment

```typescript
// Frontend: httpGateway.ts
async completePayment(transaction: Transaction, mandate: Mandate): Promise<Transaction> {
  return postJson<Transaction>(`/api/transactions/${transaction.id}/payment/complete`, 
    { transaction, mandate }
  );
}
```

```python
# Backend: Flask route
@app.route('/api/transactions/<txn_id>/payment/complete', methods=['POST'])
def complete_payment(txn_id):
    data = request.get_json()  # { transaction, mandate }
    
    # CRITICAL: Re-check mandate (expiry + revocation) atomically
    mandate = data['mandate']
    if mandate.get('revokedAt') or mandate_expired(mandate):
        db.update_transaction(txn_id, status='CANCELLED')
        return jsonify({"id": txn_id, "status": "CANCELLED"}), 200
    
    # OK to complete
    db.update_transaction(txn_id, status='COMPLETED')
    return jsonify({"id": txn_id, "status": "COMPLETED"}), 200
```

---

## The postJson Helper (Already in httpGateway.ts)

```typescript
async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Request failed: ${res.status} ${res.statusText}`);
  return (await res.json()) as T;
}
```

**This handles:**
- ✅ Stringifying the object to JSON
- ✅ Sending Content-Type header
- ✅ Checking for errors (non-2xx status)
- ✅ Parsing the response

---

## Setup Checklist

- [ ] Backend listens on http://localhost:3000
- [ ] Frontend `.env` has `VITE_API_BASE_URL=http://localhost:3000`
- [ ] Backend has CORS enabled: `from flask_cors import CORS; CORS(app)`
- [ ] Backend returns JSON (use `return jsonify(dict), 200`)
- [ ] Frontend imports from `httpGateway` (not `mockGateway`)

---

## Testing a Single Endpoint

### Using `curl` (command line)

```bash
# Test GET /api/catalog
curl http://localhost:3000/api/catalog

# Test POST /api/mandates/interpret
curl -X POST http://localhost:3000/api/mandates/interpret \
  -H "Content-Type: application/json" \
  -d '{"instruction": "Buy me a mouse", "priceLimit": 300}'
```

### Using DevTools Network Tab

1. Open `http://localhost:5173`
2. Open DevTools (F12)
3. Go to **Network** tab
4. Perform an action
5. Click the request in the list
6. View **Request** tab (what was sent) and **Response** tab (what came back)

---

## Error Status Codes

| Code | Meaning | Fix |
|------|---------|-----|
| 200 | ✅ Success | Good! |
| 400 | Client error (bad input) | Check request body shape |
| 404 | Endpoint not found | Check Flask route path |
| 422 | Validation failed | Check backend validation logic |
| 500 | Server error | Check backend logs (print statements) |
| CORS error | Browser blocked request | Add `CORS(app)` in Flask |

---

## Example Flow: "Buy a mouse" Scenario

```
┌─────────────────────────────────────────────────────┐
│ User fills Screen 1:                                │
│   Instruction: "Buy me a quiet mouse under HK$300"  │
│   Price limit: 300                                  │
│   Clicks "Activate mandate"                         │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
         Frontend: activateMandate()
                     │
                     ▼
    interpretMandate({
      "instruction": "Buy me a quiet mouse...",
      "priceLimit": 300
    })
                     │
                     ▼
   POST /api/mandates/interpret (HTTP)
                     │
                     ▼
┌────────────────────────────────────────────────────┐
│ Backend receives JSON body                          │
│ {                                                  │
│   "instruction": "Buy me a quiet mouse...",        │
│   "priceLimit": 300                                │
│ }                                                  │
│                                                    │
│ LLM processes: → categories, merchants, etc.      │
│ Returns: mandate JSON                              │
└────────┬───────────────────────────────────────────┘
         │
         ▼
   Response 200 OK:
   {
     "id": "mandate-abc",
     "maxPerTransaction": 300,
     "allowedCategories": ["Computer Accessories"],
     "expiresAt": "2027-12-31T23:59:59.000Z"
   }
         │
         ▼
    Frontend: setMandate(parsed)
         │
         ▼
┌────────────────────────────────────┐
│ Screen 1 updates with new mandate  │
│ (shows max price, categories, etc) │
└────────────────────────────────────┘
```

---

## Key Insights

1. **Interface is a Contract**: Your UI agrees to work with anything that implements `CommerceGateway`. Mock or HTTP, it doesn't matter.

2. **One Import to Rule Them All**: Change one line in `App.tsx` to swap from mock to real backend.

3. **JSON is the Language**: Browser and Python talk JSON. Objects ↔ dicts. Always match the shape.

4. **POST = Two-Way**: You send something, you get something back (usually depends on what you sent).

5. **GET = One-Way**: You ask "please give me data", backend sends it.

6. **Error Handling**: Always check `if (!res.ok)` or let the catch block handle it.

7. **Async/Await**: All network requests are async (`Promise`). Use `await` to wait for responses.

---

## Next Steps

1. Implement your Flask endpoints (use templates above)
2. Test each with `curl` 
3. Add to `.env`: `VITE_API_BASE_URL=http://localhost:3000`
4. Change import in `App.tsx`
5. Open DevTools, test the flow
6. Watch backend logs to see requests come in
