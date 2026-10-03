# Testing Guide: From Backend to Frontend

This guide walks you through testing the full flow locally.

---

## Setup: Backend

### 1. Install Flask Dependencies

```bash
pip install flask flask-cors
```

### 2. Run the Backend Server

```bash
python backend_example.py
```

You should see:
```
╔═══════════════════════════════════════════════════════════════╗
║          GUARDRAIL BACKEND — Flask Development Server         ║
╚═══════════════════════════════════════════════════════════════╝

Endpoints:
  GET  /api/catalog
  POST /api/mandates/interpret
  POST /api/authorization/evaluate
  ...

Starting server...
 * Serving Flask app 'backend_example'
 * Debug mode: on
 * Running on http://0.0.0.0:3000
```

**Leave this terminal running.** It's your backend API.

---

## Setup: Frontend

### 1. Create `.env` File

In the project root (same directory as `package.json`), create `.env`:

```bash
VITE_API_BASE_URL=http://localhost:3000
```

### 2. Switch to Real Backend

**Before:**
```typescript
// src/App.tsx (line ~35)
import { commerceGateway } from './services/mockGateway';
```

**After:**
```typescript
// src/App.tsx (line ~35)
import { commerceGateway } from './services/httpGateway';
```

### 3. Start Frontend Dev Server

Open a **new terminal** and run:

```bash
npm run dev
```

You should see:
```
VITE v5.0.0  ready in 123 ms

➜  local:   http://localhost:5173/
➜  press h + enter to show help
```

---

## Test 1: GET /api/catalog

### Via Browser DevTools

1. Open `http://localhost:5173`
2. Press F12 (DevTools)
3. Go to **Network** tab
4. Reload the page (Cmd+R)
5. Look for `catalog` request

**Expected:**
- Status: **200**
- Response contains 2 products (mouse-quiet, keyboard-pro)

**If status 404:**
- Backend server not running
- Check backend terminal for errors

**If CORS error:**
- Backend is running but CORS not enabled
- Check `CORS(app)` line in backend

### Via curl

```bash
curl http://localhost:3000/api/catalog | jq
```

**Expected output:**
```json
[
  {
    "id": "mouse-quiet",
    "name": "QuietClick Wireless Mouse",
    "price": 219,
    "shipping": 20,
    ...
  },
  {
    "id": "keyboard-pro",
    "name": "MechanicalPro Keyboard",
    "price": 580,
    "shipping": 30,
    ...
  }
]
```

---

## Test 2: POST /api/mandates/interpret (The Main One!)

### Step 1: Trigger the Endpoint from UI

1. Frontend is open at `http://localhost:5173`
2. **Screen 1** (Mandate) is displayed
3. In the textarea, type: `Buy me a quiet mouse under HK$300`
4. In the "Maximum per purchase" field, type: `300`
5. Click **"Activate mandate"**

### Step 2: Watch the Request

DevTools **Network** tab:
1. Click the `interpret` POST request
2. Tab **Headers**: Shows the request
3. Tab **Request**: Shows the body sent
   ```json
   {
     "instruction": "Buy me a quiet mouse under HK$300",
     "priceLimit": 300
   }
   ```
4. Tab **Response**: Shows what came back
   ```json
   {
     "id": "mandate-abc123",
     "maxPerTransaction": 300,
     "allowedCategories": ["Computer Accessories"],
     "allowedMerchants": ["campus-tech", "student-store"],
     "expiresAt": "2027-09-30T..."
   }
   ```

### Step 3: Watch the Backend

Your backend terminal should show:
```
[POST] /api/mandates/interpret
  Interpreting: 'Buy me a quiet mouse under HK$300' with limit HK$300
  ✓ Created mandate mandate-abcd1234
[AUDIT] AGENT: Interpreted user instruction into mandate mandate-abcd1234
```

### Via curl

```bash
curl -X POST http://localhost:3000/api/mandates/interpret \
  -H "Content-Type: application/json" \
  -d '{"instruction": "Buy me a quiet mouse under HK$300", "priceLimit": 300}' \
  | jq
```

**Expected output:**
```json
{
  "id": "mandate-abc123",
  "maxPerTransaction": 300,
  "maxDailySpend": 600,
  "allowedCategories": ["Computer Accessories"],
  "allowedMerchants": ["campus-tech", "student-store"],
  "expiresAt": "2027-09-30T02:29:21.000000Z"
}
```

---

## Test 3: Full Flow (All 5 Endpoints)

### Step-by-Step UI Flow

1. **Screen 1: Mandate**
   - Type: `Buy me a quiet mouse under HK$300`
   - Click: **Activate mandate**
   - ✅ Expect: Mandate appears on the policy card
   - 📡 Backend called: `/api/mandates/interpret`

2. **Screen 2: Agent shop**
   - Click: **Propose purchase** on the Mouse (HK$219 + HK$20 shipping)
   - ✅ Expect: Transaction card shows total HK$239
   - 📡 Backend called: (Frontend creates Transaction locally, not sent yet)

3. **Screen 3: Authorize**
   - Click: **Run authorization**
   - ✅ Expect: "ALLOW" decision appears with rule checks
   - 📡 Backend called: `/api/authorization/evaluate`

4. **Screen 4: Result**
   - Click: **Proceed to simulated payment**
   - ✅ Expect: Status changes to "PAYMENT_PENDING"
   - 📡 Backend called: `/api/transactions/{id}/payment/start`

5. **Screen 5: Audit log**
   - Click: **Confirm payment**
   - ✅ Expect: Status changes to "COMPLETED"
   - 📡 Backend called: `/api/transactions/{id}/payment/complete`
   - Click: **View audit trail** (bottom left)
   - ✅ Expect: List of all recorded events

### Watching All Requests in DevTools

Open DevTools, Network tab, filter by Fetch/XHR:

| Step | Request | Status | Body | Response |
|------|---------|--------|------|----------|
| Activate | POST /api/mandates/interpret | 200 | instruction, priceLimit | Mandate |
| Run auth | POST /api/authorization/evaluate | 200 | mandate, transaction | AuthorizationResult |
| Start payment | POST /api/transactions/.../payment/start | 200 | transaction | Transaction (PAYMENT_PENDING) |
| Complete | POST /api/transactions/.../payment/complete | 200 | transaction, mandate | Transaction (COMPLETED) |

---

## Test 4: Error Cases

### 4.1 Empty Instruction

```bash
curl -X POST http://localhost:3000/api/mandates/interpret \
  -H "Content-Type: application/json" \
  -d '{"instruction": "", "priceLimit": 300}'
```

**Expected response:** Status 400
```json
{
  "error": "instruction is required"
}
```

### 4.2 Negative Price Limit

```bash
curl -X POST http://localhost:3000/api/mandates/interpret \
  -H "Content-Type: application/json" \
  -d '{"instruction": "Buy a mouse", "priceLimit": -100}'
```

**Expected response:** Status 400
```json
{
  "error": "priceLimit must be a positive number"
}
```

### 4.3 Authorization DENY

1. Frontend: Propose a **Keyboard** (HK$580 + HK$30 shipping = HK$610 total)
2. Mandate limit: HK$300
3. Click **Run authorization**
4. **Expected:** Decision = "DENY", reason mentions "exceeds... limit"

---

## Test 5: Revocation Flow

### Step 1: Authorize a Transaction

1. Mandate limit: HK$300
2. Product: Mouse (HK$219 + HK$20 = HK$239)
3. Run authorization: Should be **ALLOW**
4. Click **Proceed to simulated payment** → status becomes PAYMENT_PENDING

### Step 2: Revoke the Mandate

While the payment is pending:
1. Click **Revoke authorization** button (if visible on Screen 4)
2. Backend sets `revokedAt` on the mandate

### Step 3: Complete Payment

1. Click **Confirm payment**
2. Backend checks mandate:
   - Is it revoked? **YES**
   - Decision: Move to **CANCELLED** (NOT COMPLETED!)
3. Verify in DevTools that the response transaction has `status: "CANCELLED"`

---

## Common Test Issues & Fixes

### Issue 1: "CORS error" when clicking Activate

**Cause:** CORS not enabled in backend

**Fix:**
```python
from flask_cors import CORS
app = Flask(__name__)
CORS(app)  # Add this line
```

Restart backend.

### Issue 2: "Request failed: 404" when clicking Activate

**Cause:** Backend server not running on port 3000

**Fix:**
```bash
# Check if backend is running
lsof -i :3000

# If not, start it
python backend_example.py
```

### Issue 3: "Invalid mandateId" or similar error

**Cause:** Frontend env var not set, or still importing mockGateway

**Fix:**
1. Create `.env` file with `VITE_API_BASE_URL=http://localhost:3000`
2. Change import in `App.tsx` from `mockGateway` to `httpGateway`
3. Restart frontend dev server (`npm run dev`)

### Issue 4: Backend shows "TypeError: NoneType..."

**Cause:** Frontend sent incomplete JSON

**Fix:**
- Check DevTools Network → Request body
- Ensure both `instruction` and `priceLimit` are present and valid
- Add validation in backend (already done in example)

---

## Performance Considerations

### Normal Latency

Each endpoint should respond in < 100ms (unless calling LLM):

```
GET /api/catalog      → ~10ms (just return mock data)
POST /api/mandates    → ~1000ms (if calling real LLM like OpenAI)
POST /api/authorize   → ~5ms (deterministic rules)
POST /api/payment/*   → ~10ms (update status)
```

If your responses are slow:
1. Backend might be calling a slow LLM
2. DB queries might be slow (add indexes)
3. Network latency (move backend geographically closer)

### DevTools Tips

- **Network** tab: See exact response times
- **Console** tab: JavaScript errors from frontend
- **Application** → **Local Storage**: Check `VITE_API_BASE_URL` is set
- Filter by "Fetch/XHR" to see API calls only (not CSS, JS, etc)

---

## Debugging: Print Statements

### Backend

Already has `print()` statements. You'll see:

```
[POST] /api/mandates/interpret
  Interpreting: '...' with limit HK$300
  ✓ Created mandate mandate-abc123
[AUDIT] AGENT: Interpreted user instruction...
```

Add more if needed:

```python
@app.route('/api/mandates/interpret', methods=['POST'])
def interpret_mandate():
    data = request.get_json()
    print(f"[DEBUG] Received data: {data}")  # ← Add this
    # ... rest of code
```

### Frontend

Open DevTools **Console** tab. Look for:
- JavaScript errors (red)
- Network errors (if any)

Add debug logs in `App.tsx`:

```typescript
const activateMandate = async () => {
  console.log("User clicked Activate Mandate");
  console.log("Sending:", { instruction, priceLimit: mandate.maxPerTransaction });
  try {
    const parsed = await commerceGateway.interpretMandate({
      instruction,
      priceLimit: mandate.maxPerTransaction
    });
    console.log("Received:", parsed);  // ← Add this
    setMandate(parsed);
    // ... rest
  } catch (err) {
    console.error("Error:", err);  // ← Already there
  }
};
```

---

## Final Validation Checklist

- [ ] Backend running on `localhost:3000` (see startup message)
- [ ] Frontend running on `localhost:5173` (or displayed URL)
- [ ] `.env` file created with `VITE_API_BASE_URL=http://localhost:3000`
- [ ] `src/App.tsx` imports from `httpGateway` (not `mockGateway`)
- [ ] DevTools Network tab shows successful POST requests (status 200)
- [ ] Backend terminal shows `[POST]` logs for each request
- [ ] Frontend screens advance as expected after each action
- [ ] Audit log shows recorded events

**All green?** You're connected! 🚀

---

## Next: Swap in Your Real LLM

The `backend_example.py` includes a mock LLM:

```python
def mock_llm_interpret(instruction: str, price_limit: float) -> Dict[str, Any]:
    # Naive keyword matching
    # Replace this with real OpenAI, Claude, etc.
```

To use real OpenAI:

```bash
pip install openai
```

```python
from openai import OpenAI

def real_llm_interpret(instruction: str, price_limit: float) -> Dict[str, Any]:
    client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
    
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{
            "role": "user",
            "content": f"Parse this shopping instruction: '{instruction}' with budget HK${price_limit}. Return JSON..."
        }],
        response_format={"type": "json_object"}  # Force JSON output
    )
    
    return json.loads(response.choices[0].message.content)
```

Store your API key in `.env`:
```bash
OPENAI_API_KEY=sk-...
```

Load it in Python:
```python
from dotenv import load_dotenv
import os

load_dotenv()
api_key = os.getenv('OPENAI_API_KEY')
```

That's it! Your frontend automatically picks up the change. 🎉
