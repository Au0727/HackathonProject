# START HERE: Frontend-Backend Integration Tutorial

Welcome! I've created **4 comprehensive guides** to teach you how to connect your React frontend to your Python backend using HTTP GET/POST requests.

---

## 📚 The Four Guides

### 1. **[FRONTEND_BACKEND_TUTORIAL.md](./FRONTEND_BACKEND_TUTORIAL.md)** ← START HERE
**A complete, beginner-friendly walkthrough**

- What is HTTP GET/POST?
- The integration "seam" (contracts.ts)
- How `interpretMandate()` works step-by-step
- Complete Flask backend example with explanations
- Environment setup
- Common mistakes and fixes

**Time to read:** 20 minutes
**Best for:** Understanding the full picture

---

### 2. **[QUICK_REFERENCE.md](./QUICK_REFERENCE.md)**
**Copy-paste templates for all 5 endpoints**

- One-page cheat sheet
- Template for each endpoint (frontend + backend)
- The `postJson` helper explained
- Setup checklist
- Error status codes
- Example flow diagram

**Time to read:** 5 minutes
**Best for:** Quick lookup while coding

---

### 3. **[backend_example.py](./backend_example.py)**
**A complete, working Flask backend**

- All 5 endpoints fully implemented
- Deterministic policy engine (the core business logic)
- Mock LLM parser (replace with real OpenAI/Claude)
- Audit logging
- Error handling
- Ready to run: `python backend_example.py`

**Time to read:** 10 minutes (skim first, then code line-by-line)
**Best for:** Learning by example, copy-paste starting point

---

### 4. **[TESTING_GUIDE.md](./TESTING_GUIDE.md)**
**How to test everything end-to-end**

- Backend setup and startup
- Frontend setup (change import, create .env)
- Test each endpoint individually (curl + DevTools)
- Full flow test (all 5 endpoints together)
- Error case testing
- Common issues and fixes
- DevTools debugging tips

**Time to read:** 15 minutes
**Best for:** Validating your implementation

---

## 🚀 Quick Start (5 Minutes)

### Step 1: Run Backend
```bash
pip install flask flask-cors
python backend_example.py
```

### Step 2: Configure Frontend
Create `.env` file:
```bash
VITE_API_BASE_URL=http://localhost:3000
```

Change `src/App.tsx`:
```typescript
// OLD:
import { commerceGateway } from './services/mockGateway';

// NEW:
import { commerceGateway } from './services/httpGateway';
```

### Step 3: Run Frontend
```bash
npm run dev
```

### Step 4: Test
1. Open `http://localhost:5173`
2. Type: "Buy me a quiet mouse under HK$300"
3. Click: "Activate mandate"
4. **Expected:** Mandate appears on the screen ✅

---

## 🎯 Key Concepts

### 1. The Interface Contract
[contracts.ts](./src/services/contracts.ts) defines ONE interface that BOTH the mock and real backend implement. The UI doesn't care which one — it just works.

```typescript
export interface CommerceGateway {
  getCatalog(): Promise<Product[]>;
  interpretMandate(input: MandateInterpretationInput): Promise<Mandate>;
  authorize(mandate: Mandate, transaction: Transaction): Promise<AuthorizationResult>;
  startPayment(transaction: Transaction): Promise<Transaction>;
  completePayment(transaction: Transaction, mandate: Mandate): Promise<Transaction>;
}
```

### 2. HTTP Verbs
- **GET**: Request data (no body) → `GET /api/catalog`
- **POST**: Send data (with body) → `POST /api/mandates/interpret` + `{ instruction, priceLimit }`

### 3. The Flow
```
Browser sends JSON → Backend receives → Processes → Returns JSON → Browser parses
```

### 4. One Import to Rule Them All
To swap from mock to real backend, change ONE line in App.tsx:

```typescript
// Development (mock):
import { commerceGateway } from './services/mockGateway';

// Production (real backend):
import { commerceGateway } from './services/httpGateway';
```

---

## 📖 Reading Order

**Option A: I'm completely new to HTTP**
1. Read [FRONTEND_BACKEND_TUTORIAL.md](./FRONTEND_BACKEND_TUTORIAL.md) (Parts 1-3)
2. Skim [backend_example.py](./backend_example.py)
3. Do [TESTING_GUIDE.md](./TESTING_GUIDE.md) hands-on

**Option B: I understand HTTP, just need to connect this app**
1. Read [QUICK_REFERENCE.md](./QUICK_REFERENCE.md)
2. Copy endpoints from [backend_example.py](./backend_example.py)
3. Follow [TESTING_GUIDE.md](./TESTING_GUIDE.md) to validate

**Option C: Show me working code now**
1. Run [backend_example.py](./backend_example.py)
2. Follow [TESTING_GUIDE.md](./TESTING_GUIDE.md) "Setup" section
3. Read [FRONTEND_BACKEND_TUTORIAL.md](./FRONTEND_BACKEND_TUTORIAL.md) while testing

---

## 🧠 The Core Lesson: `interpretMandate()`

This is the example you asked for. Here's the full cycle:

### 1️⃣ Frontend sends data
```typescript
// src/App.tsx
const activateMandate = async () => {
  const result = await commerceGateway.interpretMandate({
    instruction: "Buy me a quiet mouse under HK$300",
    priceLimit: 300
  });
};
```

### 2️⃣ HTTP request travels
```
POST /api/mandates/interpret
Content-Type: application/json
Body: {
  "instruction": "Buy me a quiet mouse under HK$300",
  "priceLimit": 300
}
```

### 3️⃣ Backend receives and processes
```python
# backend.py
@app.route('/api/mandates/interpret', methods=['POST'])
def interpret_mandate():
    data = request.get_json()  # Parse JSON from request
    instruction = data['instruction']
    price_limit = data['priceLimit']
    
    # Call LLM to interpret
    result = llm_parse(instruction, price_limit)
    
    return jsonify({
        "id": "mandate-abc",
        "maxPerTransaction": price_limit,
        "allowedCategories": result['categories'],
        "expiresAt": "2027-12-31T23:59:59.000Z"
    }), 200
```

### 4️⃣ HTTP response returns
```json
{
  "id": "mandate-abc",
  "maxPerTransaction": 300,
  "allowedCategories": ["Computer Accessories"],
  "expiresAt": "2027-12-31T23:59:59.000Z"
}
```

### 5️⃣ Frontend receives and displays
```typescript
const parsed = await commerceGateway.interpretMandate({...});
setMandate(parsed);  // Update React state
// Screen 1 re-renders with the new mandate ✅
```

**That's it!** Apply this same pattern to all 5 endpoints. 🎉

---

## 🔧 The 5 Endpoints You'll Build

| # | Method | Path | Frontend Calls | Backend Returns |
|---|--------|------|---|---|
| 1 | GET | `/api/catalog` | `getCatalog()` | `Product[]` |
| 2 | POST | `/api/mandates/interpret` | `interpretMandate(input)` | `Mandate` |
| 3 | POST | `/api/authorization/evaluate` | `authorize(mandate, txn)` | `AuthorizationResult` |
| 4 | POST | `/api/transactions/:id/payment/start` | `startPayment(txn)` | `Transaction` |
| 5 | POST | `/api/transactions/:id/payment/complete` | `completePayment(txn, mandate)` | `Transaction` |

All templates are in [QUICK_REFERENCE.md](./QUICK_REFERENCE.md) and [backend_example.py](./backend_example.py).

---

## 📱 Debugging with DevTools

### See Every Request
1. Open `http://localhost:5173`
2. Press **F12** (DevTools)
3. Go to **Network** tab
4. Click an action (e.g., "Activate mandate")
5. Look for the POST request
6. Click it
7. Tab **Request**: See what was sent
8. Tab **Response**: See what came back

### See Backend Logs
Keep your backend terminal visible:
```bash
[POST] /api/mandates/interpret
  Interpreting: 'Buy me a quiet mouse under HK$300' with limit HK$300
  ✓ Created mandate mandate-abc123
```

---

## ❓ FAQ

**Q: Do I need to understand TypeScript?**
A: No. The frontend is already written. You only write Python for the backend.

**Q: Can I test endpoints without the frontend?**
A: Yes! Use `curl`:
```bash
curl -X POST http://localhost:3000/api/mandates/interpret \
  -H "Content-Type: application/json" \
  -d '{"instruction": "Buy a mouse", "priceLimit": 300}'
```

**Q: What if my LLM API is slow?**
A: That's fine. The frontend will wait (there's a loading spinner).

**Q: Can I use a different Python framework instead of Flask?**
A: Yes. Adapt the endpoint code to your framework (FastAPI, Django, etc). The request/response JSON shapes stay the same.

**Q: What if I'm calling an external LLM API?**
A: See the end of [TESTING_GUIDE.md](./TESTING_GUIDE.md) for OpenAI example.

**Q: How do I store data persistently?**
A: [backend_example.py](./backend_example.py) uses in-memory dicts. Replace with database queries (PostgreSQL, MongoDB, etc).

---

## ✅ Success Criteria

You've succeeded when:

- [ ] Backend starts without errors
- [ ] Frontend starts without errors
- [ ] Type instruction, click "Activate mandate"
- [ ] DevTools shows POST request to `/api/mandates/interpret` with status 200
- [ ] Mandate appears on Screen 1
- [ ] Backend terminal shows `[POST] /api/mandates/interpret`

**You've now connected frontend to backend!** 🚀

---

## 📞 Still Stuck?

1. Check [TESTING_GUIDE.md](./TESTING_GUIDE.md) "Common Issues" section
2. Look at your DevTools Network tab (see exact error)
3. Check backend terminal logs
4. Verify `.env` has `VITE_API_BASE_URL=http://localhost:3000`
5. Verify `src/App.tsx` imports from `httpGateway` (not `mockGateway`)

---

## 🎓 What You'll Learn

After following these guides, you'll understand:

- ✅ How HTTP GET/POST requests work
- ✅ How frontend and backend communicate via JSON
- ✅ How to implement an HTTP API in Python
- ✅ How to test APIs with DevTools and curl
- ✅ How to debug connection issues
- ✅ How to build scalable frontend-backend systems

**You're not just connecting this app — you're learning a skill that works for ANY frontend-backend system.** 💪

---

**Happy coding! Start with [FRONTEND_BACKEND_TUTORIAL.md](./FRONTEND_BACKEND_TUTORIAL.md)** 🚀
