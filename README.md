# 🏛️ AI Equity Research Agent

> A multi-step LangGraph agent that produces institutional-grade equity research reports — including a full PDF report, pitch deck (PPTX), and editable DCF model (XLSX) — from a single ticker input.

![Stack](https://img.shields.io/badge/stack-Python%20%7C%20FastAPI%20%7C%20LangGraph%20%7C%20Gemini-blue)
![Status](https://img.shields.io/badge/status-MVP-green)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

---

## ✨ What it does

Enter a stock ticker (e.g. `AAPL`). The agent:

1. **Collects** financials, price history, and news from Yahoo Finance
2. **Researches** the business, moat, bull case, and risks using Gemini
3. **Analyzes** the company with a discounted cash flow valuation grounded in real financials
4. **Writes** an executive summary and `BUY` / `HOLD` / `SELL` recommendation
5. **Generates** three downloadable artifacts:
   - 📄 Multi-page PDF research report
   - 📊 7-slide PowerPoint pitch deck
   - 📈 Editable Excel DCF model (live formulas + sensitivity table)

All in **~30 seconds**, **free**, with no paid APIs.

---

## 🧠 Architecture

```
                      ┌────────────────────────┐
                      │   Browser (HTML/JS)    │
                      └───────────┬────────────┘
                                  │ HTTP
                      ┌───────────▼────────────┐
                      │   FastAPI (Python)     │
                      └───────────┬────────────┘
                                  │
                  ┌───────────────▼────────────────┐
                  │      LangGraph Agent           │
                  │                                │
                  │  ┌─────────────────────────┐   │
                  │  │ 1. Data Collector       │   │  yfinance
                  │  │    (deterministic)      │   │
                  │  └────────────┬────────────┘   │
                  │               ▼                │
                  │  ┌─────────────────────────┐   │
                  │  │ 2. Researcher           │   │  Gemini
                  │  │    (LLM, qualitative)   │   │
                  │  └────────────┬────────────┘   │
                  │               ▼                │
                  │  ┌─────────────────────────┐   │
                  │  │ 3. Analyst              │   │  Gemini + Python
                  │  │    (LLM + DCF math)     │   │
                  │  └────────────┬────────────┘   │
                  │               ▼                │
                  │  ┌─────────────────────────┐   │
                  │  │ 4. Writer               │   │  Gemini
                  │  │    (synthesizes call)   │   │
                  │  └─────────────────────────┘   │
                  └───────────────┬────────────────┘
                                  │
                  ┌───────────────▼────────────────┐
                  │   Generators                   │
                  │   PDF (reportlab) /            │
                  │   PPTX (python-pptx) /         │
                  │   XLSX (openpyxl)              │
                  └────────────────────────────────┘
```

Each agent node reads from and writes to a shared `AgentState` (typed dict). This gives you stateful, multi-step reasoning — the kind of architecture you can credibly call an **AI agent** rather than an LLM wrapper.

---

## 🛠️ Tech stack

| Layer        | Choice                                                   |
|--------------|----------------------------------------------------------|
| Agent        | [LangGraph](https://langchain-ai.github.io/langgraph/) — stateful multi-step graphs |
| LLM          | Google **Gemini 2.5 Flash** (free tier)                  |
| Data         | [`yfinance`](https://github.com/ranaroussi/yfinance) — free, no key |
| Backend      | FastAPI + Uvicorn                                        |
| Generators   | `reportlab` (PDF), `python-pptx` (deck), `openpyxl` (Excel) |
| Frontend     | Vanilla HTML/CSS/JS — fast, no build step                |
| Deploy       | Render (backend free tier) + Netlify/Vercel (frontend)   |

---

## 🚀 Quickstart (local)

### 1. Clone & install backend

```bash
git clone <your-repo-url>
cd equity-research-agent/backend
python -m venv venv
source venv/bin/activate    # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Get a free Gemini API key

1. Go to **https://aistudio.google.com/apikey**
2. Sign in → "Create API key" → "Create API key in new project"
3. Copy the key

### 3. Configure environment

```bash
cp .env.example .env
# Open .env and paste your key:
# GEMINI_API_KEY=AIza...
```

### 4. Start the backend

From the **project root** (one level above `backend/`):

```bash
cd ..  # back to project root
uvicorn backend.main:app --reload --port 8000
```

Visit http://localhost:8000/healthz — you should see `{"status": "ok", "gemini_configured": true}`.

### 5. Open the frontend

In a second terminal:

```bash
cd frontend
python -m http.server 5173
```

Open http://localhost:5173 in your browser. Try `AAPL`.

---

## 📡 API Reference

### `POST /api/analyze`

Run the agent on a ticker.

**Request:**
```json
{ "ticker": "AAPL" }
```

**Response:**
```json
{
  "job_id": "uuid",
  "ticker": "AAPL",
  "company_name": "Apple Inc.",
  "sector": "Technology",
  "recommendation": "HOLD",
  "target_price": 230.45,
  "current_price": 220.10,
  "upside_pct": 0.047,
  "executive_summary": "...",
  "investment_thesis": "...",
  "risks": "...",
  "business_overview": "...",
  "competitive_position": "...",
  "dcf_assumptions": { ... },
  "log": [ ... ]
}
```

### `GET /api/report/{job_id}` → PDF
### `GET /api/deck/{job_id}` → PPTX
### `GET /api/model/{job_id}` → XLSX

Download generated artifacts. Job results are cached in memory for the lifetime of the server process.

---

## 🌐 Deployment

### Backend → Render (free)

1. Push this repo to GitHub.
2. Go to https://render.com → "New +" → "Blueprint"
3. Connect your GitHub repo. Render reads `render.yaml` automatically.
4. In the Render dashboard, set the `GEMINI_API_KEY` environment variable.
5. Wait ~5 min for first build. You'll get a URL like `https://equity-research-agent-api.onrender.com`.

> Note: Render's free tier sleeps after 15 min of inactivity. First request after sleep takes ~30s to wake up.

### Frontend → Netlify or Vercel (free)

**Option A — Netlify (easiest):**
1. Drag the `frontend/` folder onto https://app.netlify.com/drop
2. Before that, open `frontend/app.js` and change line ~6 to point at your Render URL:
   ```js
   const API_BASE = "https://your-backend.onrender.com";
   ```

**Option B — Vercel:**
1. `npm i -g vercel`
2. `cd frontend && vercel`
3. Set `API_BASE` the same way.

---

## 📁 Project structure

```
equity-research-agent/
├── backend/
│   ├── agent/
│   │   ├── graph.py          # LangGraph workflow
│   │   ├── nodes.py          # Data/Research/Analyst/Writer nodes
│   │   ├── state.py          # Shared AgentState schema
│   │   └── llm.py            # Gemini client
│   ├── data/
│   │   └── fetcher.py        # yfinance wrapper
│   ├── generators/
│   │   ├── pdf_report.py     # reportlab PDF builder
│   │   ├── pitch_deck.py     # python-pptx deck builder
│   │   └── dcf_excel.py      # openpyxl DCF model
│   ├── main.py               # FastAPI app
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── render.yaml               # Render deployment config
├── .gitignore
└── README.md
```

---

## 🎓 Engineering notes (what's worth highlighting on a resume)

- **Real agent architecture**: Multi-node LangGraph with typed shared state, not a single-prompt LLM call.
- **Mixed deterministic + LLM logic**: The DCF math runs in pure Python (deterministic, auditable) while only the *assumptions* come from the LLM (judgment). This is how real quant + AI hybrid systems are built.
- **Robust JSON parsing**: The analyst node uses constrained-output prompting + multi-strategy JSON extraction so the pipeline doesn't break when Gemini occasionally wraps output in markdown.
- **Live Excel formulas**: The XLSX model uses real `openpyxl` formulas (not just static values), so users can edit assumption cells and watch the DCF recalculate in Excel.
- **Production-flavored API**: Pydantic schemas, CORS, healthcheck, streamed file responses, in-memory job cache.

---

## 🧪 Things you can extend (great resume talking points)

- Add a **comparable companies** node (peer P/E, EV/EBITDA multiples)
- Add a **Monte Carlo** simulation around the DCF
- Replace in-memory job cache with **Redis** for horizontal scalability
- Add a **vector store** (e.g. Chroma) with recent 10-K filings, let the researcher cite them
- Add **streaming responses** (SSE) so the UI shows each step as it completes
- Add **caching** by ticker (e.g. don't re-fetch yfinance data within 1 hour)

---

## ⚠️ Disclaimer

This is an educational project. The DCF assumptions are generated by an LLM and may be wildly off. **Do not use this for actual investment decisions.**

---

## 📄 License

MIT
