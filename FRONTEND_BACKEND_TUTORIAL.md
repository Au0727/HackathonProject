# Frontend-Backend Integration Tutorial
## GET/POST API Connection Guide for Beginners

This guide teaches you **from scratch** how your React frontend communicates with your Python backend using HTTP requests (GET/POST).

---

## Part 1: What is an HTTP GET/POST Request?

### Simple Analogy

Think of HTTP requests like sending a postcard to a friend:

- **GET Request**: Asking "What's your current address?" — You're *requesting* information. No sensitive data in the question.
- **POST Request**: Sending a message with your new contact info — You're *sending* data to the server, often sensitive or complex.

### Real Example

**GET Request:**
```
GET /api/catalog
→ Server returns: "Here is my product list"
```

**POST Request:**
```
POST /api/mandates/interpret
Body: { "instruction": "Buy me a mouse", "priceLimit": 300 }
→ Server returns: "I parsed your instruction; here's your spending mandate"
```

---

## Part 2: The Integration "Seam" (Your Contract)

### Where Everything Connects

Look at [src/services/contracts.ts](/Users/zhuoersheng/RaccoonWork/src/services/contracts.ts):

```typescript
export interface CommerceGateway {
  getCatalog(): Promise<Product[]>;
  interpretMandate(input: MandateInterpretationInput): Promise<Mandate>;
  authorize(mandate: Mandate, transaction: Transaction): Promise<AuthorizationResult>;
  startPayment(transaction: Transaction): Promise<Transaction>;
  completePayment(transaction: Transaction, mandate: Mandate): Promise<Transaction>;
}
```

**This interface is YOUR CONTRACT.** It says:
- "These 5 methods exist"
- "Each method returns a Promise (async operation)"
- "The input and output shapes are defined in `domain/types.ts`"

The UI doesn't care *how* these methods work — mock, HTTP, or anything else. As long as something implements this interface, the app works.

### Two Implementations Available

**Today (Development):** [src/services/mockGateway.ts](/Users/zhuoersheng/RaccoonWork/src/services/mockGateway.ts)
- Returns **fake data** instantly (no network)
- Good for testing UI before backend is ready

**Production (Your Goal):** [src/services/httpGateway.ts](/Users/zhuoersheng/RaccoonWork/src/services/httpGateway.ts)
- Sends **real HTTP requests** to your Python server
- Waits for responses, processes them, returns them to the UI

---

## Part 3: How to Implement `interpretMandate()` - Step by Step

This is the function that takes the user's spoken instruction and converts it to a structured mandate. Let's build it.

### Step 1: Understand What Data Flows

```
User Types in Screen 1:
  "Buy me a quiet mouse under HK$300"   ← instruction
  300                                    ← priceLimit

         ↓ User Clicks "Activate Mandate" ↓

Frontend creates an object:
{
  "instruction": "Buy me a quiet mouse under HK$300",
  "priceLimit": 300
}

         ↓ Sends POST Request ↓

POST /api/mandates/interpret
Content-Type: application/json
{
  "instruction": "Buy me a quiet mouse under HK$300",
  "priceLimit": 300
}

         ↓ Backend Processes ↓

Backend LLM interprets the text and returns:
{
  "id": "mandate-abc123",
  "maxPerTransaction": 300,                    ← from priceLimit
  "allowedCategories": ["Computer Accessories"], ← LLM guessed from "mouse"
  "expiresAt": "2027-12-31T23:59:59.000Z"    ← backend sets default
}

         ↓ Returns to Frontend ↓

UI receives the mandate and stores it (setMandate)
```

### Step 2: Implement the Frontend Sender

In [src/services/httpGateway.ts](/Users/zhuoersheng/RaccoonWork/src/services/httpGateway.ts), the method is **already written**:

```typescript
async interpretMandate(input: MandateInterpretationInput): Promise<Mandate> {
  return postJson<Mandate>('/api/mandates/interpret', input);
}
```

Here's what each part does:

```typescript
async interpretMandate(
  input: MandateInterpretationInput     // Input: { instruction, priceLimit }
): Promise<Mandate> {                    // Output: A Mandate (wrapped in Promise = async)
  return postJson<Mandate>(              // Helper function (see below)
    '/api/mandates/interpret',           // The endpoint on your backend
    input                                // The body to send (automatically converted to JSON)
  );
}
```

### Step 3: Understand the Helper Function `postJson`

```typescript
async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',                           // ← This is a POST request
    headers: { 'Content-Type': 'application/json' },  // ← Tell server: "I'm sending JSON"
    body: JSON.stringify(body),               // ← Convert object to JSON string
  });
  if (!res.ok) throw new Error(`Request failed: ${res.status} ${res.statusText}`);
  return (await res.json()) as T;             // ← Parse response, return as type T
}
```

**Translation:**
1. `fetch()` is the browser's built-in HTTP function
2. We send a POST to `BASE_URL + /api/mandates/interpret`
3. The body is the `input` object, stringified to JSON
4. We wait for the response with `await`
5. If status is 200-299 (success), we parse the JSON
6. If status is 400+ (error), we throw an error (which will be caught in `App.tsx`)

### Step 4: How It's Called from the UI

In [src/App.tsx](/Users/zhuoersheng/RaccoonWork/src/App.tsx), when the user clicks "Activate mandate":

```typescript
const activateMandate = async () => {
  setBusy(true);                                              // Show loading spinner
  setInterpretError(null);
  try {
    const parsed = await commerceGateway.interpretMandate({   // ← Call the gateway
      instruction,                                            // ← From textarea (state)
      priceLimit: mandate.maxPerTransaction                   // ← From number field (state)
    });
    setMandate(parsed);                                       // ← Store the response
    appendAudit(...);                                         // ← Record in audit log
    setStep('shop');                                          // ← Move to next screen
  } catch (err) {
    setInterpretError('The agent could not interpret that instruction...'); // ← Show error
  } finally {
    setBusy(false);                                           // ← Hide spinner
  }
};
```

**The flow:**
1. User fills textarea with "Buy me a quiet mouse under HK$300"
2. User fills number field with 300
3. User clicks "Activate mandate"
4. `activateMandate()` runs
5. It calls `interpretMandate()` with those two pieces of data
6. `interpretMandate()` sends a POST request to your backend
7. Your backend's LLM processes it and returns a `Mandate`
8. The UI stores the mandate and shows the next screen

---

## Part 4: Implementing Your Backend Endpoint (Python Flask Example)

Now, **your Python backend** needs to handle the incoming POST request.

### Python Backend Code (Flask)

```python
from flask import Flask, request, jsonify
from datetime import datetime, timedelta
import json

app = Flask(__name__)

@app.route('/api/mandates/interpret', methods=['POST'])
def interpret_mandate():
    """
    Receives:
      {
        "instruction": "Buy me a quiet mouse under HK$300",
        "priceLimit": 300
      }
    
    Returns:
      {
        "id": "mandate-abc123",
        "maxPerTransaction": 300,
        "allowedCategories": ["Computer Accessories"],
        "allowedMerchants": ["campus-tech"],
        "expiresAt": "2027-12-31T23:59:59.000Z"
      }
    """
    
    # Step 1: Extract the data sent by frontend
    data = request.get_json()  # Parses the JSON body automatically
    instruction = data.get('instruction', '')
    price_limit = data.get('priceLimit')
    
    # Step 2: Validate inputs
    if not instruction:
        return jsonify({'error': 'instruction is required'}), 400
    if price_limit is None or price_limit <= 0:
        return jsonify({'error': 'priceLimit must be a positive number'}), 400
    
    # Step 3: Call your LLM (pseudo-code)
    mandate = call_llm_to_parse_mandate(
        user_instruction=instruction,
        max_price=price_limit
    )
    
    # Step 4: Validate the LLM output
    if not mandate:
        return jsonify({'error': 'Could not parse instruction'}), 422
    
    # Step 5: Build the response (must match Mandate type from types.ts)
    response = {
        "id": generate_mandate_id(),        # e.g. "mandate-abc123"
        "maxPerTransaction": price_limit,   # User's price cap
        "allowedCategories": mandate.get('categories', []),  # LLM extracted
        "allowedMerchants": mandate.get('merchants', []),    # LLM extracted
        "expiresAt": (datetime.now() + timedelta(days=365)).isoformat() + 'Z'
    }
    
    # Step 6: Return JSON response
    return jsonify(response), 200  # 200 = success
```

### What Each Line Does

```python
@app.route('/api/mandates/interpret', methods=['POST'])
# ↑ Listen for POST requests at this exact path
# Frontend URL: http://localhost:3000/api/mandates/interpret
```

```python
data = request.get_json()
# ↑ Flask automatically parses the JSON body into a Python dict
# If frontend sent: { "instruction": "...", "priceLimit": 300 }
# Then data is: {"instruction": "...", "priceLimit": 300}
```

```python
instruction = data.get('instruction', '')
# ↑ Get the 'instruction' key from the dict
# If missing, use empty string as default
```

```python
return jsonify(response), 200
# ↑ Convert Python dict to JSON and send back with status 200 (success)
# Frontend receives this as a JSON object, parses it automatically
```

---

## Part 5: Connecting the Two (Environment Variable)

### Set the API Base URL

The frontend needs to know where your backend is running.

**File:** `.env` (create if not exists)

```bash
VITE_API_BASE_URL=http://localhost:3000
```

Or for production:
```bash
VITE_API_BASE_URL=https://your-backend.com
```

The httpGateway reads this:
```typescript
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:3000';
```

So if you set `VITE_API_BASE_URL` in `.env`, it uses that; otherwise defaults to localhost.

---

## Part 6: Wiring It All Together - The Checklist

### In Your Python Backend

- [ ] Add endpoint `POST /api/mandates/interpret` that accepts JSON
- [ ] Extract `instruction` and `priceLimit` from request body
- [ ] Call your LLM with `instruction` (NOT the description text from products!)
- [ ] Validate LLM output to fit the `Mandate` schema
- [ ] Return JSON in this exact shape:
  ```json
  {
    "id": "mandate-xxx",
    "maxPerTransaction": <the priceLimit>,
    "allowedCategories": <extracted by LLM>,
    "allowedMerchants": <extracted by LLM>,
    "expiresAt": "2027-12-31T23:59:59.000Z"
  }
  ```

### In Your Frontend

- [ ] `.env` file has `VITE_API_BASE_URL=http://localhost:3000`
- [ ] `src/services/httpGateway.ts` is complete (already is!)
- [ ] Change import in `src/App.tsx` from `mockGateway` to `httpGateway`
  ```typescript
  // OLD:
  import { commerceGateway } from './services/mockGateway';
  
  // NEW:
  import { commerceGateway } from './services/httpGateway';
  ```
- [ ] Run `npm run dev` to start frontend
- [ ] Run your Python backend on port 3000 (or update `.env`)

### Test It

1. Open http://localhost:5173 (frontend)
2. Type instruction: "Buy me a quiet mouse under HK$300"
3. Click "Activate mandate"
4. **Expected:** Mandate appears on Screen 1 policy card
5. **If error:** Check Python backend logs

---

## Part 7: The Same Pattern for ALL Endpoints

Every other endpoint follows **exactly the same pattern**:

### `getCatalog()` - GET request

```typescript
// Frontend (httpGateway.ts)
async getCatalog(): Promise<Product[]> {
  const res = await fetch(`${BASE_URL}/api/catalog`);
  if (!res.ok) throw new Error('Catalog request failed');
  return (await res.json()) as Product[];
}
```

```python
# Backend (Flask)
@app.route('/api/catalog', methods=['GET'])
def get_catalog():
    products = [
        {
            "id": "mouse-quiet",
            "name": "QuietClick Wireless Mouse",
            "price": 219,
            "shipping": 20,
            # ... etc
        }
    ]
    return jsonify(products), 200
```

**Difference from POST:**
- No request body (no `get_json()`)
- Just return the list of products

### `authorize()` - POST request

```typescript
// Frontend (httpGateway.ts)
async authorize(mandate: Mandate, transaction: Transaction): Promise<AuthorizationResult> {
  return postJson<AuthorizationResult>('/api/authorization/evaluate', { mandate, transaction });
}
```

```python
# Backend (Flask)
@app.route('/api/authorization/evaluate', methods=['POST'])
def evaluate_authorization():
    data = request.get_json()
    mandate = data['mandate']
    transaction = data['transaction']
    
    # Run your policy rules
    decision = evaluate_policy(mandate, transaction)
    
    return jsonify({
        "decision": decision,
        "reason": "...",
        "failedRules": [...],
        "evaluatedAt": datetime.now().isoformat() + 'Z',
        "mandateId": mandate['id'],
        "ruleChecks": [...]
    }), 200
```

**Same pattern:**
1. Extract data from request body
2. Process it (LLM, policy rules, etc.)
3. Return structured JSON matching the type

---

## Part 8: Debugging - How to See What's Being Sent/Received

### In Browser (Chrome DevTools)

1. Open DevTools (F12)
2. Go to **Network** tab
3. Perform an action (e.g., click "Activate mandate")
4. Look for the POST request in the list
5. Click on it
6. Tab **Request**: see what the frontend is sending
7. Tab **Response**: see what the backend returned
8. Tab **Headers**: see content-type, status code, etc.

**Example:**
```
POST /api/mandates/interpret
Status: 200 OK

Request body:
{
  "instruction": "Buy me a quiet mouse under HK$300",
  "priceLimit": 300
}

Response body:
{
  "id": "mandate-allowed",
  "maxPerTransaction": 300,
  "allowedCategories": ["Computer Accessories"],
  "expiresAt": "2027-12-31T23:59:59.000Z"
}
```

### In Python Backend

Add print statements (or use logging):

```python
@app.route('/api/mandates/interpret', methods=['POST'])
def interpret_mandate():
    data = request.get_json()
    print(f"Frontend sent: {data}")  # ← See the request
    
    result = call_llm(data['instruction'])
    print(f"Returning to frontend: {result}")  # ← See the response
    
    return jsonify(result), 200
```

Then watch your terminal while testing.

---

## Part 9: Common Mistakes & How to Fix Them

### Mistake 1: "The request is being sent but the backend isn't receiving it"

**Cause:** CORS (Cross-Origin Resource Sharing) error. Browser blocks requests to different domains for security.

**Fix:** Add CORS headers in your Python backend:

```python
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Allow all origins (dev only; be more restrictive in production)
```

Install: `pip install flask-cors`

### Mistake 2: "Response received but JSON parsing fails"

**Cause:** Backend returned non-JSON (error HTML, plain text, etc.)

**Fix:** 
- Check the **Response** tab in DevTools — see exactly what came back
- Ensure your backend returns `jsonify(dict)`, not strings

### Mistake 3: "Mandate object has missing fields"

**Cause:** Backend didn't set all required fields in the response.

**Fix:** Check [src/domain/types.ts](/Users/zhuoersheng/RaccoonWork/src/domain/types.ts):
```typescript
export type Mandate = {
  id: string;                    // ← REQUIRED
  maxPerTransaction?: number;    // optional (? means optional)
  allowedCategories?: string[];  // optional
  expiresAt: string;             // ← REQUIRED (ISO date string)
  revokedAt?: string;            // optional
};
```

Mandatory fields: `id` and `expiresAt`. Others are optional.

### Mistake 4: "Frontend shows 'Request failed: 422' error"

**Cause:** Backend rejected the input (validation failed).

**Fix:**
- 400 = client sent bad data (missing fields, invalid types)
- 422 = request was valid JSON but semantically wrong (e.g., negative price)
- 500 = backend error (check backend logs)

Return the correct status and an error message:
```python
if price_limit < 0:
    return jsonify({'error': 'priceLimit must be positive'}), 400
```

---

## Summary

**Concept:**
- GET: Request data from backend (no body)
- POST: Send data to backend (with body)

**Pattern for every endpoint:**
1. Frontend: `httpGateway.ts` method calls `fetch()` with endpoint + body
2. Backend: `@app.route()` receives the JSON, processes it, returns JSON
3. Frontend: receives the JSON, parses it, stores in React state

**To swap from mock to real:**
1. Build the Python endpoint (e.g., `/api/mandates/interpret`)
2. Implement the `httpGateway.ts` method (already done!)
3. Change the import in `App.tsx`
4. Set `.env` with `VITE_API_BASE_URL`

**You now know everything needed.** Follow the Mandate endpoint as your template, apply it to all other endpoints, and you're live! 🚀
