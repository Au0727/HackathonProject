# 🎓 Frontend-Backend Integration Tutorials

**Complete beginner-friendly guide to connecting your React frontend to your Python backend using HTTP GET/POST requests.**

> This was created specifically to teach you how to integrate your backend with the example of `interpretMandate()` function as the main use case.

---

## ⚡ 5-Minute Quick Start

```bash
# Terminal 1: Backend
pip install flask flask-cors
python backend_example.py

# Terminal 2: Frontend
echo "VITE_API_BASE_URL=http://localhost:3000" > .env
# Then edit src/App.tsx: change mockGateway → httpGateway
npm run dev

# Browser
# Open http://localhost:5173
# Type: "Buy me a quiet mouse under HK$300"
# Click: "Activate mandate"
# ✅ See mandate appear on screen
```

---

## 📚 Tutorial Files (10 New Files Created)

| File | Time | Purpose |
|------|------|---------|
| [QUICKSTART.md](./QUICKSTART.md) | 5 min | Copy-paste commands, get working immediately |
| [START_HERE.md](./START_HERE.md) | 10 min | Overview, choose your learning path |
| [FRONTEND_BACKEND_TUTORIAL.md](./FRONTEND_BACKEND_TUTORIAL.md) | 20 min | Complete beginner guide with 9 parts |
| [QUICK_REFERENCE.md](./QUICK_REFERENCE.md) | 5 min | One-page cheat sheet, templates |
| [ARCHITECTURE_DIAGRAMS.md](./ARCHITECTURE_DIAGRAMS.md) | 10 min | 8 visual diagrams explaining everything |
| [TESTING_GUIDE.md](./TESTING_GUIDE.md) | 15 min | How to test everything end-to-end |
| [backend_example.py](./backend_example.py) | — | Working Flask backend, all 5 endpoints |
| [TUTORIAL_INDEX.md](./TUTORIAL_INDEX.md) | — | Master index of all guides |
| [COMPLETE_SOLUTION_SUMMARY.md](./COMPLETE_SOLUTION_SUMMARY.md) | — | Summary of everything |

---

## 🎯 Choose Your Learning Path

### 🏃 Path 1: Super Busy (5 min)
**Just want it working NOW?**
1. [QUICKSTART.md](./QUICKSTART.md)
2. Run the commands
3. Done! ✅

### 🤔 Path 2: Complete Beginner (1 hour)
**Completely new to HTTP?**
1. [QUICKSTART.md](./QUICKSTART.md) (5 min) — Get it working
2. [FRONTEND_BACKEND_TUTORIAL.md](./FRONTEND_BACKEND_TUTORIAL.md) (20 min) — Learn concepts
3. [ARCHITECTURE_DIAGRAMS.md](./ARCHITECTURE_DIAGRAMS.md) (10 min) — See visuals
4. [TESTING_GUIDE.md](./TESTING_GUIDE.md) (15 min) — Test everything

### 👨‍💻 Path 3: Experienced Dev (30 min)
**Know HTTP, need this specific app?**
1. [QUICKSTART.md](./QUICKSTART.md) (5 min)
2. [QUICK_REFERENCE.md](./QUICK_REFERENCE.md) (5 min)
3. Study [backend_example.py](./backend_example.py) (10 min)
4. [TESTING_GUIDE.md](./TESTING_GUIDE.md) (10 min)

### 🚀 Path 4: Show Me Code (15 min)
**Just run it and learn later?**
1. [backend_example.py](./backend_example.py) — Run it
2. [TESTING_GUIDE.md](./TESTING_GUIDE.md) — Test it
3. Come back for theory later

---

## 📖 What's In Each File

### [QUICKSTART.md](./QUICKSTART.md)
**The absolute fastest way to get running (5 minutes)**
- Install Flask
- Run backend
- Change one line in frontend
- Create .env file
- Test it ✅

### [START_HERE.md](./START_HERE.md)
**Master overview of all guides**
- Which file for what question
- Quick 5-minute setup
- Key concepts at a glance
- Success checklist
- FAQ

### [FRONTEND_BACKEND_TUTORIAL.md](./FRONTEND_BACKEND_TUTORIAL.md)
**The Complete Beginner's Guide (20 minutes)**
- Part 1: What is HTTP GET/POST? (with analogies)
- Part 2: The integration seam (contracts.ts)
- Part 3: How `interpretMandate()` works (step-by-step)
- Part 4: Complete Python Flask backend code
- Part 5: Environment setup (.env file)
- Part 6: Wiring it together (checklist)
- Part 7: Same pattern for all 5 endpoints
- Part 8: Debugging with DevTools
- Part 9: Common mistakes & fixes

### [QUICK_REFERENCE.md](./QUICK_REFERENCE.md)
**One-page cheat sheet (5 minutes)**
- HTTP verbs explained
- Copy-paste template for each endpoint
- The `postJson()` helper
- Setup checklist
- Error status codes
- Example request/response flow

### [backend_example.py](./backend_example.py)
**Complete working Flask backend**
- All 5 endpoints fully implemented
- Deterministic policy engine
- Mock LLM (easy to replace)
- Audit logging
- Error handling
- Run with: `python backend_example.py`

### [TESTING_GUIDE.md](./TESTING_GUIDE.md)
**How to test everything (15 minutes)**
- Backend setup
- Frontend setup
- Test each endpoint individually
- Full flow test (all 5 together)
- Error case testing
- Common issues & fixes
- DevTools debugging tips

### [ARCHITECTURE_DIAGRAMS.md](./ARCHITECTURE_DIAGRAMS.md)
**Visual explanations (10 minutes)**
- Diagram 1: Big picture (entire system)
- Diagram 2: Request/response cycle (detailed)
- Diagram 3: The 5 endpoints
- Diagram 4: Integration seam (swappable)
- Diagram 5: Complete flow example
- Diagram 6: Technology stack
- Diagram 7: Error handling
- Diagram 8: State timeline

### [TUTORIAL_INDEX.md](./TUTORIAL_INDEX.md)
**Master index of everything**
- All learning paths
- Complete file descriptions
- Quick verification checklist
- Pro tips

---

## 🔑 The Core Concept

Everything connects through ONE interface in [src/services/contracts.ts](/Users/zhuoersheng/RaccoonWork/src/services/contracts.ts):

```typescript
export interface CommerceGateway {
  getCatalog(): Promise<Product[]>;
  interpretMandate(input: MandateInterpretationInput): Promise<Mandate>;
  authorize(mandate: Mandate, transaction: Transaction): Promise<AuthorizationResult>;
  startPayment(transaction: Transaction): Promise<Transaction>;
  completePayment(transaction: Transaction, mandate: Mandate): Promise<Transaction>;
}
```

**Two implementations:**
- **mockGateway** (development) — Fast, local, no network
- **httpGateway** (production) — Real HTTP requests to backend

**To swap:** Change ONE line in [src/App.tsx](/Users/zhuoersheng/RaccoonWork/src/App.tsx):

```typescript
// Development:
import { commerceGateway } from './services/mockGateway';

// Production:
import { commerceGateway } from './services/httpGateway';
```

**That's it!** The UI doesn't care which one it's using. ✨

---

## 🎯 The 5 Endpoints

```
1. GET  /api/catalog
   └─ Frontend calls: getCatalog()
   └─ Backend returns: Product[]

2. POST /api/mandates/interpret ← YOUR MAIN EXAMPLE
   └─ Frontend calls: interpretMandate({ instruction, priceLimit })
   └─ Backend returns: Mandate (user's structured policy)

3. POST /api/authorization/evaluate
   └─ Frontend calls: authorize(mandate, transaction)
   └─ Backend returns: AuthorizationResult (ALLOW/DENY decision)

4. POST /api/transactions/:id/payment/start
   └─ Frontend calls: startPayment(transaction)
   └─ Backend returns: Transaction (status: PAYMENT_PENDING)

5. POST /api/transactions/:id/payment/complete
   └─ Frontend calls: completePayment(transaction, mandate)
   └─ Backend returns: Transaction (COMPLETED or CANCELLED)
```

All templates in [QUICK_REFERENCE.md](./QUICK_REFERENCE.md) and [backend_example.py](./backend_example.py)

---

## ✅ Learning Outcomes

After following these tutorials, you'll understand:

- ✅ How HTTP GET/POST requests work
- ✅ Request/response cycle and JSON format
- ✅ How to build a Flask REST API
- ✅ How to send data from frontend to backend
- ✅ How to receive and display data on frontend
- ✅ How to test with curl and browser DevTools
- ✅ How to debug network issues
- ✅ How the 5 endpoints fit together
- ✅ How to swap mock ↔ HTTP backends
- ✅ How to call LLMs from the backend
- ✅ How to implement policy rules

**These skills apply to 99% of web applications!** 💪

---

## 🚀 Getting Started Right Now

### Option 1: Just Run It
```bash
# Terminal 1
pip install flask flask-cors
python backend_example.py

# Terminal 2
echo "VITE_API_BASE_URL=http://localhost:3000" > .env
# Edit src/App.tsx: mockGateway → httpGateway
npm run dev

# Browser: http://localhost:5173
```

### Option 2: Understand It First
→ Open [QUICKSTART.md](./QUICKSTART.md) for detailed steps

### Option 3: Learn Everything
→ Start with [START_HERE.md](./START_HERE.md) and choose your path

---

## 📱 DevTools: Your Debugging Superpower

When something doesn't work:

1. Open DevTools (F12)
2. Go to **Network** tab
3. Try the action again
4. Find the request in the list
5. Click it
6. Tab **Request**: See what was sent
7. Tab **Response**: See what came back

**90% of issues are visible here!** This one skill solves most problems.

---

## 🐛 Most Common Issues (Quick Fixes)

| Issue | Fix |
|-------|-----|
| CORS error | Add `CORS(app)` in Flask, restart backend |
| 404 Not Found | Check endpoint path matches exactly |
| JSON parsing error | Ensure `return jsonify()` in Flask |
| Request hangs | Backend crashed or slow, check logs |
| "undefined" in UI | Response missing a field, check shape |

For more: See [TESTING_GUIDE.md](./TESTING_GUIDE.md) "Common Issues" section

---

## 💡 Pro Tips

1. **Keep two terminals open** — One for backend, one for frontend
2. **Watch the logs** — Backend prints what it's doing
3. **Use curl first** — Test endpoints before testing in UI
4. **DevTools is your friend** — Network tab shows everything
5. **Start with mock** — Verify UI works before adding backend

---

## 📖 File Organization

```
Your Project Root:
├── 📚 TUTORIALS (read these)
│   ├── QUICKSTART.md
│   ├── START_HERE.md
│   ├── FRONTEND_BACKEND_TUTORIAL.md
│   ├── QUICK_REFERENCE.md
│   ├── ARCHITECTURE_DIAGRAMS.md
│   ├── TESTING_GUIDE.md
│   ├── TUTORIAL_INDEX.md
│   └── README_TUTORIALS.md (this file)
│
├── 🐍 BACKEND CODE (write yours)
│   └── backend_example.py (copy & adapt)
│
├── ⚙️ FRONTEND CODE (already working)
│   ├── src/services/contracts.ts (the interface)
│   ├── src/services/httpGateway.ts (HTTP implementation)
│   ├── src/services/mockGateway.ts (mock for testing)
│   └── src/App.tsx (import from httpGateway here)
│
├── 📝 CONFIG
│   └── .env (create this: VITE_API_BASE_URL=http://localhost:3000)
│
└── 📖 REFERENCE
    ├── BACKEND_INTEGRATION.md (original spec)
    ├── ARCHITECTURE.md (design rationale)
    └── README.md (project overview)
```

---

## 🎓 What Makes This Tutorial Different

✅ **From Absolute Scratch** — No assumed knowledge of HTTP
✅ **Concrete Example** — Uses `interpretMandate()` as the main case
✅ **Working Code** — [backend_example.py](./backend_example.py) is copy-paste ready
✅ **Multiple Paths** — Choose based on your background
✅ **Visual Diagrams** — 8 diagrams explaining the architecture
✅ **Hands-On** — Test at every step
✅ **Debugging Guide** — How to fix when things break
✅ **Multiple Formats** — Quick reference, deep dive, visual, video-like

---

## ❓ FAQ

**Q: Do I need to understand TypeScript?**
A: No! You only write Python for the backend. The frontend is already done.

**Q: Can I test without running the full UI?**
A: Yes! Use `curl` to test endpoints individually. See [TESTING_GUIDE.md](./TESTING_GUIDE.md).

**Q: What if my LLM API is slow?**
A: That's fine. The frontend shows a loading spinner while waiting.

**Q: Can I use FastAPI instead of Flask?**
A: Yes! Adapt the code to your framework. The request/response shapes stay the same.

**Q: How do I go from this to production?**
A: Follow all tutorials, then add a database, authentication, https, monitoring.

For more: See [START_HERE.md](./START_HERE.md) FAQ section

---

## 🎉 You're Ready!

Everything you need is here. Start with:

1. **[QUICKSTART.md](./QUICKSTART.md)** if you're in a hurry
2. **[START_HERE.md](./START_HERE.md)** to choose your path
3. **[FRONTEND_BACKEND_TUTORIAL.md](./FRONTEND_BACKEND_TUTORIAL.md)** to understand the concepts

**Good luck! Your frontend-backend integration awaits.** 🚀

---

*Created with ❤️ to teach you how to connect frontend and backend systems.*
