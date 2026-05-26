"""
FastAPI server.

Endpoints:
  POST /api/analyze      -> runs the agent, returns JSON summary + a job_id
  GET  /api/report/{id}  -> downloads the PDF report
  GET  /api/deck/{id}    -> downloads the PPTX pitch deck
  GET  /api/model/{id}   -> downloads the XLSX DCF model
  GET  /healthz          -> health check

Job results are cached in memory for the session. Restart = cache cleared.
For production, swap the dict for Redis.
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from contextlib import asynccontextmanager
from io import BytesIO

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

load_dotenv()

from backend.agent import run_agent
from backend.generators import generate_dcf_model, generate_pdf_report, generate_pitch_deck

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("api")

# In-memory job cache: job_id -> final agent state
_JOBS: dict[str, dict] = {}

TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not os.getenv("GEMINI_API_KEY"):
        logger.warning("GEMINI_API_KEY not set. The /api/analyze endpoint will fail.")
    else:
        logger.info("Gemini API key detected.")
    yield


app = FastAPI(
    title="Equity Research Agent API",
    description="AI agent that produces equity research reports, pitch decks, and DCF models.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow the frontend to call us. Tighten for production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10, description="Stock ticker symbol")


class AnalyzeResponse(BaseModel):
    job_id: str
    ticker: str
    company_name: str
    sector: str
    recommendation: str
    target_price: float
    current_price: float
    upside_pct: float
    executive_summary: str
    investment_thesis: str
    risks: str
    business_overview: str
    competitive_position: str
    dcf_assumptions: dict
    # New in Phase 2
    confidence_score: int = 5
    confidence_rationale: str = ""
    what_would_change_mind: str = ""
    momentum: dict = {}
    catalysts: list = []
    log: list[str]


@app.get("/healthz")
def healthz():
    return {"status": "ok", "gemini_configured": bool(os.getenv("GEMINI_API_KEY"))}


@app.post("/api/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest):
    ticker = req.ticker.upper().strip()
    if not TICKER_RE.match(ticker):
        raise HTTPException(status_code=400, detail="Invalid ticker format.")

    logger.info(f"Starting analysis for {ticker}")
    try:
        state = run_agent(ticker)
    except Exception as e:
        logger.exception(f"Agent failed for {ticker}")
        raise HTTPException(status_code=500, detail=f"Agent failed: {e}")

    if state.get("errors"):
        raise HTTPException(status_code=400, detail=" | ".join(state["errors"]))

    job_id = str(uuid.uuid4())
    _JOBS[job_id] = state
    logger.info(f"Job {job_id} complete for {ticker}: {state.get('recommendation')}")

    val = state.get("dcf_valuation", {})
    profile = state["company_data"]["profile"]

    return AnalyzeResponse(
        job_id=job_id,
        ticker=ticker,
        company_name=profile.get("name", ticker),
        sector=profile.get("sector", "N/A"),
        recommendation=state.get("recommendation", "HOLD"),
        target_price=state.get("target_price", 0),
        current_price=val.get("current_share_price", 0),
        upside_pct=val.get("upside_pct", 0),
        executive_summary=state.get("executive_summary", ""),
        investment_thesis=state.get("investment_thesis", ""),
        risks=state.get("risks", ""),
        business_overview=state.get("business_overview", ""),
        competitive_position=state.get("competitive_position", ""),
        dcf_assumptions=state.get("dcf_assumptions", {}),
        confidence_score=state.get("confidence_score", 5),
        confidence_rationale=state.get("confidence_rationale", ""),
        what_would_change_mind=state.get("what_would_change_mind", ""),
        momentum=state["company_data"].get("momentum", {}),
        catalysts=state.get("catalysts", []),
        log=state.get("log", []),
    )


def _get_job_or_404(job_id: str) -> dict:
    state = _JOBS.get(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found or expired.")
    return state


@app.get("/api/report/{job_id}")
def download_report(job_id: str):
    state = _get_job_or_404(job_id)
    pdf_bytes = generate_pdf_report(state)
    ticker = state["company_data"]["profile"].get("ticker", "report")
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={ticker}_research_report.pdf"},
    )


@app.get("/api/deck/{job_id}")
def download_deck(job_id: str):
    state = _get_job_or_404(job_id)
    pptx_bytes = generate_pitch_deck(state)
    ticker = state["company_data"]["profile"].get("ticker", "deck")
    return StreamingResponse(
        BytesIO(pptx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f"attachment; filename={ticker}_pitch_deck.pptx"},
    )


@app.get("/api/model/{job_id}")
def download_model(job_id: str):
    state = _get_job_or_404(job_id)
    xlsx_bytes = generate_dcf_model(state)
    ticker = state["company_data"]["profile"].get("ticker", "model")
    return StreamingResponse(
        BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={ticker}_dcf_model.xlsx"},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
