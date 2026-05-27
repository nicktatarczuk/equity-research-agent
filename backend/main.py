"""
FastAPI server for the 14-agent equity research workflow.

Endpoints:
  POST /api/analyze      -> runs the agent, returns JSON summary + job_id
  GET  /api/report/{id}  -> PDF research report
  GET  /api/deck/{id}    -> PPTX pitch deck
  GET  /api/model/{id}   -> XLSX DCF model
  GET  /healthz
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

_JOBS: dict[str, dict] = {}
TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not os.getenv("GEMINI_API_KEY"):
        logger.warning("GEMINI_API_KEY not set.")
    if not os.getenv("FMP_API_KEY"):
        logger.warning("FMP_API_KEY not set.")
    yield


app = FastAPI(
    title="Equity Research Agent API",
    description="14-agent AI workflow producing equity research reports.",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10)


class AnalyzeResponse(BaseModel):
    job_id: str
    ticker: str
    company_name: str
    sector: str
    # Classification
    stock_type: str = "BALANCED"
    stock_type_rationale: str = ""
    valuation_framework: str = "DCF-led"
    # The call
    recommendation: str
    target_price: float
    target_range_low: float | None = None
    target_range_high: float | None = None
    current_price: float
    upside_pct: float
    confidence_score: int = 5
    confidence_rationale: str = ""
    what_would_change_mind: str = ""
    # Synthesis
    executive_summary: str
    investment_thesis: str
    risks: str
    # Research outputs
    business_overview: str = ""
    moat: str = ""
    margin_trajectory: str = ""
    competitive_position: str = ""
    technicals_read: str = ""
    macro_view: str = ""
    peer_interpretation: str = ""
    bull_case: str = ""
    bear_case: str = ""
    # Tables
    catalysts: list = []
    peer_table: list = []
    scenarios: dict = {}
    valuation_weights: dict = {}
    momentum: dict = {}
    dcf_assumptions: dict = {}
    log: list[str]


@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY")),
        "fmp_configured": bool(os.getenv("FMP_API_KEY")),
        "version": "3.0.0-multi-agent",
    }


@app.post("/api/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest):
    ticker = req.ticker.upper().strip()
    if not TICKER_RE.match(ticker):
        raise HTTPException(status_code=400, detail="Invalid ticker format.")

    logger.info(f"Starting 14-agent analysis for {ticker}")
    try:
        state = run_agent(ticker)
    except Exception as e:
        logger.exception(f"Agent failed for {ticker}")
        raise HTTPException(status_code=500, detail=f"Agent failed: {e}")

    if state.get("errors"):
        raise HTTPException(status_code=400, detail=" | ".join(state["errors"]))

    job_id = str(uuid.uuid4())
    _JOBS[job_id] = state
    logger.info(f"Job {job_id}: {state.get('recommendation')} @ ${state.get('target_price', 0):.2f}")

    company_data = state["company_data"]
    profile = company_data["profile"]
    metrics = company_data["metrics"]
    fundamentals = state.get("fundamentals", {}) or {}
    technicals = state.get("technicals", {}) or {}
    macro = state.get("macro_view", {}) or {}
    peer_analysis = state.get("peer_analysis", {}) or {}
    bull = state.get("bull_case", {}) or {}
    bear = state.get("bear_case", {}) or {}
    reality = state.get("valuation_reality", {}) or {}
    dcf = state.get("dcf_valuation", {}) or {}

    current = metrics.get("current_price") or 0
    target = state.get("target_price", 0) or 0
    upside = (target / current - 1) if current and target else 0

    return AnalyzeResponse(
        job_id=job_id,
        ticker=ticker,
        company_name=profile.get("name", ticker),
        sector=profile.get("sector", "N/A"),
        stock_type=state.get("stock_type", "BALANCED"),
        stock_type_rationale=state.get("stock_type_rationale", ""),
        valuation_framework=state.get("valuation_framework", "DCF-led"),
        recommendation=state.get("recommendation", "HOLD"),
        target_price=target,
        target_range_low=state.get("target_range_low"),
        target_range_high=state.get("target_range_high"),
        current_price=current,
        upside_pct=upside,
        confidence_score=state.get("confidence_score", 5),
        confidence_rationale=state.get("confidence_rationale", ""),
        what_would_change_mind=state.get("what_would_change_mind", ""),
        executive_summary=state.get("executive_summary", ""),
        investment_thesis=state.get("investment_thesis", ""),
        risks=state.get("key_risks", ""),
        business_overview=fundamentals.get("business_model", ""),
        moat=fundamentals.get("moat", ""),
        margin_trajectory=fundamentals.get("margin_trajectory", ""),
        competitive_position=fundamentals.get("moat", ""),  # back-compat
        technicals_read=technicals.get("read", ""),
        macro_view=macro.get("view", ""),
        peer_interpretation=peer_analysis.get("interpretation", ""),
        bull_case=bull.get("argument", ""),
        bear_case=bear.get("argument", ""),
        catalysts=state.get("catalysts", []),
        peer_table=peer_analysis.get("rows", []),
        scenarios=state.get("scenarios", {}),
        valuation_weights=reality.get("weights", {}),
        momentum=company_data.get("momentum", {}),
        dcf_assumptions=dcf.get("assumptions", {}),
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
