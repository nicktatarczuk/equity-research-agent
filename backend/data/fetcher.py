"""
Data collection layer using Financial Modeling Prep (FMP) API.

Why FMP instead of yfinance? yfinance scrapes Yahoo Finance and gets rate-limited
hard when running on shared cloud IPs (like Render's free tier). FMP is a proper
API with a free tier (250 requests/day) and reliable access from any IP.

Each call to fetch_company_data() makes ~5 API requests.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

import requests

logger = logging.getLogger(__name__)

FMP_BASE = "https://financialmodelingprep.com/api/v3"
FMP_STABLE = "https://financialmodelingprep.com/stable"


def _api_key() -> str:
    key = os.getenv("FMP_API_KEY")
    if not key:
        raise RuntimeError(
            "FMP_API_KEY not set. Get a free key at https://site.financialmodelingprep.com/developer/docs"
        )
    return key


def _get(url: str, params: dict | None = None) -> Any:
    """Make a GET request to FMP. Returns parsed JSON or empty list on error."""
    params = params or {}
    params["apikey"] = _api_key()
    try:
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 429:
            raise RuntimeError("FMP rate limit reached (250/day free tier). Try again tomorrow or upgrade.")
        if r.status_code == 401:
            raise RuntimeError("FMP API key invalid. Check FMP_API_KEY environment variable.")
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        logger.warning(f"FMP request failed for {url}: {e}")
        return []


def _safe(d: dict, key: str, default: Any = None) -> Any:
    """Pull a value from a dict, treating None/empty as the default."""
    if not isinstance(d, dict):
        return default
    v = d.get(key)
    if v is None or v == "":
        return default
    return v


def fetch_company_data(ticker: str) -> dict[str, Any]:
    """
    Pull everything we need about a company in one shot.
    Returns a dict matching the structure the agent expects.
    Raises ValueError if the ticker is invalid.
    """
    ticker = ticker.upper().strip()
    logger.info(f"Fetching data for {ticker} from FMP")

    # 1. Company profile (1 API call) - this is also our ticker validation
    profile_resp = _get(f"{FMP_BASE}/profile/{ticker}")
    if not profile_resp or not isinstance(profile_resp, list) or len(profile_resp) == 0:
        raise ValueError(f"Ticker '{ticker}' not found or has no data available.")

    p = profile_resp[0]

    # 2. Key metrics TTM (1 API call) - ratios, margins, multiples
    metrics_resp = _get(f"{FMP_BASE}/key-metrics-ttm/{ticker}")
    m = metrics_resp[0] if metrics_resp and isinstance(metrics_resp, list) else {}

    # 3. Financial ratios TTM (1 API call) - more ratios
    ratios_resp = _get(f"{FMP_BASE}/ratios-ttm/{ticker}")
    r = ratios_resp[0] if ratios_resp and isinstance(ratios_resp, list) else {}

    # 4. Latest income statement (1 API call) - for revenue, EBITDA
    income_resp = _get(f"{FMP_BASE}/income-statement/{ticker}", {"limit": 4})
    income = income_resp if isinstance(income_resp, list) else []
    latest_income = income[0] if income else {}

    # 5. Latest balance sheet (1 API call) - for debt, cash, shares
    balance_resp = _get(f"{FMP_BASE}/balance-sheet-statement/{ticker}", {"limit": 4})
    balance = balance_resp if isinstance(balance_resp, list) else []
    latest_balance = balance[0] if balance else {}

    # 6. Latest cash flow (1 API call) - for FCF
    cashflow_resp = _get(f"{FMP_BASE}/cash-flow-statement/{ticker}", {"limit": 4})
    cashflow = cashflow_resp if isinstance(cashflow_resp, list) else []
    latest_cashflow = cashflow[0] if cashflow else {}

    # 7. Stock news (1 API call) - optional, fail gracefully
    news_resp = _get(f"{FMP_BASE}/stock_news", {"tickers": ticker, "limit": 8})
    news_list = news_resp if isinstance(news_resp, list) else []

    # --- Build profile dict ---
    profile = {
        "ticker": ticker,
        "name": _safe(p, "companyName", ticker),
        "sector": _safe(p, "sector", "N/A"),
        "industry": _safe(p, "industry", "N/A"),
        "country": _safe(p, "country", "N/A"),
        "website": _safe(p, "website", ""),
        "summary": _safe(p, "description", ""),
        "employees": _safe(p, "fullTimeEmployees"),
        "market_cap": _safe(p, "mktCap"),
        "enterprise_value": _safe(m, "enterpriseValueTTM"),
        "currency": _safe(p, "currency", "USD"),
        "exchange": _safe(p, "exchangeShortName", ""),
    }

    # Convert employees to int if it came as a string
    if isinstance(profile["employees"], str):
        try:
            profile["employees"] = int(profile["employees"])
        except (ValueError, TypeError):
            profile["employees"] = None

    # --- Build metrics dict ---
    # Many fields are in different places between profile/metrics/ratios.
    # We pull from whichever has them.
    current_price = _safe(p, "price")
    revenue = _safe(latest_income, "revenue") or _safe(m, "revenuePerShareTTM", 0) * (_safe(p, "mktCap", 0) / max(_safe(p, "price", 1), 1) or 1)
    ebitda = _safe(latest_income, "ebitda")
    fcf = _safe(latest_cashflow, "freeCashFlow")
    op_cf = _safe(latest_cashflow, "operatingCashFlow") or _safe(latest_cashflow, "netCashProvidedByOperatingActivities")
    total_debt = _safe(latest_balance, "totalDebt")
    total_cash = _safe(latest_balance, "cashAndCashEquivalents") or _safe(latest_balance, "cashAndShortTermInvestments")
    shares = _safe(latest_income, "weightedAverageShsOut") or _safe(latest_income, "weightedAverageShsOutDil")

    # Revenue growth: compare last two periods if available
    revenue_growth = None
    if len(income) >= 2:
        prev_rev = _safe(income[1], "revenue")
        if prev_rev and revenue:
            revenue_growth = (revenue - prev_rev) / prev_rev

    metrics = {
        "current_price": current_price,
        "52w_high": _safe(p, "range", "").split("-")[-1].strip() if isinstance(_safe(p, "range"), str) and "-" in _safe(p, "range", "") else None,
        "52w_low": _safe(p, "range", "").split("-")[0].strip() if isinstance(_safe(p, "range"), str) and "-" in _safe(p, "range", "") else None,
        "pe_ratio": _safe(m, "peRatioTTM") or _safe(r, "priceEarningsRatioTTM"),
        "forward_pe": None,  # FMP free tier doesn't include forward P/E
        "peg_ratio": _safe(r, "pegRatioTTM"),
        "price_to_book": _safe(m, "pbRatioTTM") or _safe(r, "priceToBookRatioTTM"),
        "ev_to_revenue": _safe(m, "evToSalesTTM") or _safe(m, "enterpriseValueOverEBITDATTM"),
        "ev_to_ebitda": _safe(m, "enterpriseValueOverEBITDATTM"),
        "profit_margin": _safe(r, "netProfitMarginTTM"),
        "operating_margin": _safe(r, "operatingProfitMarginTTM"),
        "roe": _safe(r, "returnOnEquityTTM") or _safe(m, "roeTTM"),
        "roa": _safe(r, "returnOnAssetsTTM"),
        "revenue_growth": revenue_growth,
        "earnings_growth": None,
        "debt_to_equity": _safe(r, "debtEquityRatioTTM"),
        "current_ratio": _safe(r, "currentRatioTTM"),
        "free_cash_flow": fcf,
        "operating_cash_flow": op_cf,
        "total_revenue": revenue,
        "ebitda": ebitda,
        "total_debt": total_debt,
        "total_cash": total_cash,
        "shares_outstanding": shares,
        "beta": _safe(p, "beta"),
        "dividend_yield": _safe(p, "lastDiv", 0) / current_price if current_price and _safe(p, "lastDiv") else None,
    }

    # Parse 52w high/low from "range" field which is "low-high" format
    range_str = _safe(p, "range", "")
    if isinstance(range_str, str) and "-" in range_str:
        try:
            parts = [x.strip() for x in range_str.split("-")]
            metrics["52w_low"] = float(parts[0])
            metrics["52w_high"] = float(parts[1])
        except (ValueError, IndexError):
            metrics["52w_low"] = None
            metrics["52w_high"] = None

    # --- Build statement lists (for completeness, though the agent mainly uses metrics) ---
    income_statement = [
        {
            "period": _safe(i, "date", ""),
            "Revenue": _safe(i, "revenue"),
            "Gross Profit": _safe(i, "grossProfit"),
            "Operating Income": _safe(i, "operatingIncome"),
            "Net Income": _safe(i, "netIncome"),
            "EBITDA": _safe(i, "ebitda"),
        }
        for i in income[:4]
    ]
    balance_sheet = [
        {
            "period": _safe(b, "date", ""),
            "Total Assets": _safe(b, "totalAssets"),
            "Total Debt": _safe(b, "totalDebt"),
            "Total Equity": _safe(b, "totalStockholdersEquity"),
            "Cash": _safe(b, "cashAndCashEquivalents"),
        }
        for b in balance[:4]
    ]
    cash_flow_list = [
        {
            "period": _safe(c, "date", ""),
            "Operating Cash Flow": _safe(c, "operatingCashFlow"),
            "Free Cash Flow": _safe(c, "freeCashFlow"),
            "Capex": _safe(c, "capitalExpenditure"),
        }
        for c in cashflow[:4]
    ]

    # --- News ---
    news = []
    for item in (news_list or [])[:8]:
        title = _safe(item, "title", "")
        if not title:
            continue
        news.append({
            "title": title,
            "publisher": _safe(item, "site", ""),
            "date": str(_safe(item, "publishedDate", ""))[:10],
        })

    return {
        "profile": profile,
        "metrics": metrics,
        "income_statement": income_statement,
        "balance_sheet": balance_sheet,
        "cash_flow": cash_flow_list,
        "price_history": [],  # Not pulled — agent doesn't use this directly
        "news": news,
        "fetched_at": datetime.utcnow().isoformat(),
    }
