"""
Data collection layer using Financial Modeling Prep (FMP) stable API.

FMP migrated all endpoints from /api/v3/* to /stable/* in mid-2025.
The legacy endpoints return 403 for new users. We use the stable endpoints.

Key URL pattern change:
  OLD: /api/v3/profile/AAPL?apikey=...
  NEW: /stable/profile?symbol=AAPL&apikey=...

Each call to fetch_company_data() makes ~5-6 API requests.
Free tier: 250 requests/day.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

import requests

logger = logging.getLogger(__name__)

FMP_BASE = "https://financialmodelingprep.com/stable"


def _api_key() -> str:
    key = os.getenv("FMP_API_KEY")
    if not key:
        raise RuntimeError(
            "FMP_API_KEY not set. Get a free key at https://site.financialmodelingprep.com/developer/docs"
        )
    return key


def _get(endpoint: str, params: dict | None = None) -> Any:
    """Make a GET request to a stable FMP endpoint. Returns parsed JSON or empty list."""
    url = f"{FMP_BASE}/{endpoint.lstrip('/')}"
    params = dict(params or {})
    params["apikey"] = _api_key()
    try:
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 429:
            raise RuntimeError("FMP rate limit reached (250/day free tier). Try again tomorrow or upgrade.")
        if r.status_code == 401:
            raise RuntimeError("FMP API key invalid. Check FMP_API_KEY environment variable.")
        if r.status_code == 403:
            # Could be: legacy endpoint, premium endpoint, or expired key
            logger.warning(f"FMP returned 403 for {url}. Endpoint may require premium plan.")
            return []
        r.raise_for_status()
        data = r.json()
        # Some endpoints return an error object with a top-level "Error Message" field
        if isinstance(data, dict) and "Error Message" in data:
            logger.warning(f"FMP error for {endpoint}: {data['Error Message']}")
            return []
        return data
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
    Pull everything we need about a company from FMP's stable endpoints.
    Returns a dict matching the structure the agent expects.
    Raises ValueError if the ticker is invalid.
    """
    ticker = ticker.upper().strip()
    logger.info(f"Fetching data for {ticker} from FMP stable API")

    # 1. Company profile (validates ticker exists)
    profile_resp = _get("profile", {"symbol": ticker})
    if not profile_resp or not isinstance(profile_resp, list) or len(profile_resp) == 0:
        raise ValueError(f"Ticker '{ticker}' not found or has no data available.")
    p = profile_resp[0]

    # 2. TTM key metrics
    metrics_resp = _get("key-metrics-ttm", {"symbol": ticker})
    m = metrics_resp[0] if metrics_resp and isinstance(metrics_resp, list) else {}

    # 3. TTM ratios
    ratios_resp = _get("ratios-ttm", {"symbol": ticker})
    r_data = ratios_resp[0] if ratios_resp and isinstance(ratios_resp, list) else {}

    # 4. Income statement (last 4 years, annual)
    income_resp = _get("income-statement", {"symbol": ticker, "limit": 4})
    income = income_resp if isinstance(income_resp, list) else []
    latest_income = income[0] if income else {}

    # 5. Balance sheet (last 4 years, annual)
    balance_resp = _get("balance-sheet-statement", {"symbol": ticker, "limit": 4})
    balance = balance_resp if isinstance(balance_resp, list) else []
    latest_balance = balance[0] if balance else {}

    # 6. Cash flow (last 4 years, annual)
    cashflow_resp = _get("cash-flow-statement", {"symbol": ticker, "limit": 4})
    cashflow = cashflow_resp if isinstance(cashflow_resp, list) else []
    latest_cashflow = cashflow[0] if cashflow else {}

    # 7. News (free tier supports this on stable, key is "news/stock")
    news_resp = _get("news/stock", {"symbols": ticker, "limit": 8})
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
        "market_cap": _safe(p, "marketCap") or _safe(p, "mktCap"),
        "enterprise_value": _safe(m, "enterpriseValueTTM"),
        "currency": _safe(p, "currency", "USD"),
        "exchange": _safe(p, "exchangeShortName") or _safe(p, "exchange", ""),
    }

    # Convert employees to int if it came as a string
    if isinstance(profile["employees"], str):
        try:
            profile["employees"] = int(profile["employees"])
        except (ValueError, TypeError):
            profile["employees"] = None

    # --- Pull financial figures from the right places ---
    current_price = _safe(p, "price")
    revenue = _safe(latest_income, "revenue")
    ebitda = _safe(latest_income, "ebitda")
    fcf = _safe(latest_cashflow, "freeCashFlow")
    op_cf = _safe(latest_cashflow, "operatingCashFlow") or _safe(latest_cashflow, "netCashProvidedByOperatingActivities")
    total_debt = _safe(latest_balance, "totalDebt")
    total_cash = (
        _safe(latest_balance, "cashAndCashEquivalents")
        or _safe(latest_balance, "cashAndShortTermInvestments")
    )
    shares = (
        _safe(latest_income, "weightedAverageShsOut")
        or _safe(latest_income, "weightedAverageShsOutDil")
    )

    # Revenue growth: compare two most recent annual periods
    revenue_growth = None
    if len(income) >= 2:
        prev_rev = _safe(income[1], "revenue")
        if prev_rev and revenue:
            revenue_growth = (revenue - prev_rev) / prev_rev

    # Earnings growth: compare two most recent net income figures
    earnings_growth = None
    if len(income) >= 2:
        cur_ni = _safe(latest_income, "netIncome")
        prev_ni = _safe(income[1], "netIncome")
        if prev_ni and cur_ni and prev_ni > 0:
            earnings_growth = (cur_ni - prev_ni) / prev_ni

    # 52-week high/low from profile "range" field, formatted as "low-high"
    week_low, week_high = None, None
    range_str = _safe(p, "range", "")
    if isinstance(range_str, str) and "-" in range_str:
        try:
            parts = [x.strip() for x in range_str.split("-")]
            week_low = float(parts[0])
            week_high = float(parts[1])
        except (ValueError, IndexError):
            pass

    # Dividend yield calculated from lastDividend / price
    div_yield = None
    last_div = _safe(p, "lastDividend") or _safe(p, "lastDiv")
    if current_price and last_div:
        try:
            div_yield = float(last_div) / float(current_price)
        except (ValueError, TypeError, ZeroDivisionError):
            pass

    metrics = {
        "current_price": current_price,
        "52w_high": week_high,
        "52w_low": week_low,
        "pe_ratio": _safe(m, "peRatioTTM") or _safe(r_data, "priceToEarningsRatioTTM") or _safe(r_data, "priceEarningsRatioTTM") or _safe(r_data, "peRatioTTM"),
        "forward_pe": None,  # Premium tier only
        "peg_ratio": _safe(r_data, "priceToEarningsGrowthRatioTTM") or _safe(r_data, "pegRatioTTM"),
        "price_to_book": _safe(m, "pbRatioTTM") or _safe(r_data, "priceToBookRatioTTM"),
        "ev_to_revenue": _safe(m, "evToSalesTTM"),
        "ev_to_ebitda": _safe(m, "enterpriseValueOverEBITDATTM") or _safe(m, "evToEBITDATTM"),
        "profit_margin": _safe(r_data, "netProfitMarginTTM"),
        "operating_margin": _safe(r_data, "operatingProfitMarginTTM"),
        "roe": _safe(r_data, "returnOnEquityTTM") or _safe(m, "returnOnEquityTTM") or _safe(m, "roeTTM"),
        "roa": _safe(r_data, "returnOnAssetsTTM") or _safe(m, "returnOnAssetsTTM"),
        "revenue_growth": revenue_growth,
        "earnings_growth": earnings_growth,
        "debt_to_equity": _safe(r_data, "debtEquityRatioTTM") or _safe(r_data, "debtToEquityTTM"),
        "current_ratio": _safe(r_data, "currentRatioTTM"),
        "free_cash_flow": fcf,
        "operating_cash_flow": op_cf,
        "total_revenue": revenue,
        "ebitda": ebitda,
        "total_debt": total_debt,
        "total_cash": total_cash,
        "shares_outstanding": shares,
        "beta": _safe(p, "beta"),
        "dividend_yield": div_yield,
    }

    # --- Build statement lists (used by the report for completeness) ---
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
        # News endpoint returns date as "publishedDate"
        date_str = _safe(item, "publishedDate") or _safe(item, "date", "")
        if isinstance(date_str, str) and len(date_str) >= 10:
            date_str = date_str[:10]
        news.append({
            "title": title,
            "publisher": _safe(item, "site") or _safe(item, "publisher", ""),
            "date": str(date_str),
        })

    return {
        "profile": profile,
        "metrics": metrics,
        "income_statement": income_statement,
        "balance_sheet": balance_sheet,
        "cash_flow": cash_flow_list,
        "price_history": [],
        "news": news,
        "fetched_at": datetime.utcnow().isoformat(),
    }
