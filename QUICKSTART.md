# 🚀 Quick Start: 5 Minutes to Working Integration

**TLDR:** Run backend, change one line in frontend, create .env file. Done!

---

## Step 1: Install Backend Dependencies (1 min)

```bash
cd /Users/zhuoersheng/RaccoonWork
pip install flask flask-cors
```

---

## Step 2: Run Backend (Terminal 1)

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
 * Running on http://0.0.0.0:3000
```

**✅ Backend is running!** Leave this terminal open.

---

## Step 3: Configure Frontend (1 min)

### 3a. Create `.env` file

In the project root folder, create a file named `.env`:

```bash
VITE_API_BASE_URL=http://localhost:3000
```

(That's it! Just one line.)

### 3b. Change One Import

Open [src/App.tsx](/Users/zhuoersheng/RaccoonWork/src/App.tsx) and find this line (around line 35):

**BEFORE:**
```typescript
import { commerceGateway } from './services/mockGateway';
```

**CHANGE TO:**
```typescript
import { commerceGateway } from './services/httpGateway';
```

(That's it! Just change `mockGateway` → `httpGateway`.)

---

## Step 4: Run Frontend (Terminal 2)

```bash
npm run dev
```

You should see:
```
VITE v5.0.0  ready in 123 ms

➜  local:   http://localhost:5173/
➜  press h + enter to show help
```

**✅ Frontend is running!**

---

## Step 5: Test It (1 min)

1. Open http://localhost:5173 in your browser
2. Look at **Screen 1: Mandate**
3. In the textarea, type: `Buy me a quiet mouse under HK$300`
4. In the "Maximum per purchase" field, type: `300`
5. Click the **"Activate mandate"** button

**Expected Result:**
- ✅ The mandate appears below the input fields
- ✅ Shows "Limit: HK$ 300 per purchase"
- ✅ Shows "Categories: Computer Accessories"
- ✅ Shows "Merchants: campus-tech, student-store"

**If it works:** 🎉 **Your frontend and backend are connected!**

---

## Troubleshooting This Step

### "CORS error" or "Request failed"
- Make sure backend is running (see Terminal 1 logs)
- Make sure it says `Running on http://0.0.0.0:3000`

### "Can't find .env" or "API_BASE_URL undefined"
- Create file named `.env` (not `.env.txt`)
- Put it in the project root (same folder as `package.json`)
- Contains: `VITE_API_BASE_URL=http://localhost:3000`
- Restart frontend: `npm run dev`

### "Still doesn't work"
- Open DevTools (F12)
- Go to **Network** tab
- Try again
- Look for the failed request
- Check the Response tab for the error message
- Check backend terminal for logs

---

## 🎯 You've Just Done This:

```
React Component (UI)
        ↓
    Calls: commerceGateway.interpretMandate({ instruction, priceLimit })
        ↓
    HTTP Request: POST http://localhost:3000/api/mandates/interpret
        ↓
    Flask Backend Receives Request
        ↓
    Calls LLM (mock parser in backend_example.py)
        ↓
    Returns JSON Response
        ↓
    React Updates UI with New Mandate
        ↓
    ✅ Mandate Appears on Screen!
```

**You've successfully connected frontend ↔ backend!** 🚀

---

## Next Steps

### Option A: Understand What Just Happened
Read [FRONTEND_BACKEND_TUTORIAL.md](./FRONTEND_BACKEND_TUTORIAL.md) (20 min)

**Learn:**
- How HTTP GET/POST works
- What the backend is doing
- How JSON flows between frontend and backend

### Option B: Test All 5 Endpoints
Follow [TESTING_GUIDE.md](./TESTING_GUIDE.md) (15 min)

**Do:**
- Test the full flow (all 5 screens)
- Watch DevTools Network tab
- See backend logs

### Option C: See Architecture Diagrams
Read [ARCHITECTURE_DIAGRAMS.md](./ARCHITECTURE_DIAGRAMS.md) (10 min)

**Understand:**
- Swappable implementations
- Request/response cycle
- Error handling

### Option D: Copy Code for Your Own Backend
Use [QUICK_REFERENCE.md](./QUICK_REFERENCE.md) + [backend_example.py](./backend_example.py)

**Adapt:**
- Replace the mock LLM with your real LLM (OpenAI, Claude, etc.)
- Connect to your database
- Customize the policy rules

---

## 📱 DevTools: Your Best Debugging Tool

When something doesn't work:

1. **F12** → Open DevTools
2. **Network tab**
3. Try the action again
4. Look for the request in the list
5. Click it
6. **Request tab**: See what was sent
7. **Response tab**: See what came back

This shows the exact problem 90% of the time!

---

## ✅ Complete Checklist

- [ ] Backend installed (`pip install flask flask-cors`)
- [ ] Backend running (`python backend_example.py`)
- [ ] `.env` file created with `VITE_API_BASE_URL=http://localhost:3000`
- [ ] [src/App.tsx](/Users/zhuoersheng/RaccoonWork/src/App.tsx) changed import from `mockGateway` to `httpGateway`
- [ ] Frontend running (`npm run dev`)
- [ ] http://localhost:5173 open in browser
- [ ] Typed instruction: "Buy me a quiet mouse under HK$300"
- [ ] Clicked "Activate mandate"
- [ ] Mandate appears on screen ✅

---

## 🎓 What This Teaches You

You've just learned:

1. **HTTP GET/POST** — How browsers talk to servers
2. **Frontend-Backend Communication** — JSON over the network
3. **Async Programming** — Waiting for network responses
4. **DevTools Debugging** — Finding exactly what went wrong
5. **React State Management** — Updating UI when data arrives

**This knowledge applies to ANY web app.** 💪

---

## 🎉 Congrats!

You've successfully:
- Connected frontend to backend
- Made an HTTP request
- Called a Python function from JavaScript
- Received and displayed data

**Now you understand how the web works!** 🌍

---

## 📖 For More Details

- **Understand the theory**: [FRONTEND_BACKEND_TUTORIAL.md](./FRONTEND_BACKEND_TUTORIAL.md)
- **Quick lookup**: [QUICK_REFERENCE.md](./QUICK_REFERENCE.md)
- **See working code**: [backend_example.py](./backend_example.py)
- **Complete test flow**: [TESTING_GUIDE.md](./TESTING_GUIDE.md)
- **Visual explanations**: [ARCHITECTURE_DIAGRAMS.md](./ARCHITECTURE_DIAGRAMS.md)
- **Overall guide**: [START_HERE.md](./START_HERE.md)

**Happy coding!** 🚀
