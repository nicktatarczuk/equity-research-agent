"""
Data collection layer. Wraps yfinance into a clean interface so the agent
gets predictable, JSON-serializable dicts back.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


def _safe_get(d: dict, key: str, default: Any = None) -> Any:
    """yfinance .info dicts are messy; this keeps us from crashing on missing keys."""
    v = d.get(key, default)
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return default
    return v


def _df_to_records(df: pd.DataFrame | None, max_periods: int = 4) -> list[dict]:
    """Convert a yfinance statement DataFrame to a list of period records."""
    if df is None or df.empty:
        return []
    df = df.iloc[:, :max_periods]
    records = []
    for col in df.columns:
        period = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)
        record: dict[str, Any] = {"period": period}
        for idx in df.index:
            val = df.loc[idx, col]
            if pd.isna(val):
                record[str(idx)] = None
            else:
                record[str(idx)] = float(val)
        records.append(record)
    return records


def fetch_company_data(ticker: str) -> dict[str, Any]:
    """
    Pull everything we need about a company in one shot.
    Returns a dict with: profile, financials, price_history, news, peers.
    Raises ValueError if the ticker is invalid.
    """
    ticker = ticker.upper().strip()
    logger.info(f"Fetching data for {ticker}")

    tk = yf.Ticker(ticker)
    info = tk.info or {}

    # Basic validation - if there's no name/symbol, the ticker is bad
    if not info.get("longName") and not info.get("shortName"):
        raise ValueError(f"Ticker '{ticker}' not found or has no data available.")

    # --- Profile ---
    profile = {
        "ticker": ticker,
        "name": _safe_get(info, "longName") or _safe_get(info, "shortName", ticker),
        "sector": _safe_get(info, "sector", "N/A"),
        "industry": _safe_get(info, "industry", "N/A"),
        "country": _safe_get(info, "country", "N/A"),
        "website": _safe_get(info, "website", ""),
        "summary": _safe_get(info, "longBusinessSummary", ""),
        "employees": _safe_get(info, "fullTimeEmployees"),
        "market_cap": _safe_get(info, "marketCap"),
        "enterprise_value": _safe_get(info, "enterpriseValue"),
        "currency": _safe_get(info, "currency", "USD"),
        "exchange": _safe_get(info, "exchange", ""),
    }

    # --- Key metrics ---
    metrics = {
        "current_price": _safe_get(info, "currentPrice") or _safe_get(info, "regularMarketPrice"),
        "52w_high": _safe_get(info, "fiftyTwoWeekHigh"),
        "52w_low": _safe_get(info, "fiftyTwoWeekLow"),
        "pe_ratio": _safe_get(info, "trailingPE"),
        "forward_pe": _safe_get(info, "forwardPE"),
        "peg_ratio": _safe_get(info, "pegRatio"),
        "price_to_book": _safe_get(info, "priceToBook"),
        "ev_to_revenue": _safe_get(info, "enterpriseToRevenue"),
        "ev_to_ebitda": _safe_get(info, "enterpriseToEbitda"),
        "profit_margin": _safe_get(info, "profitMargins"),
        "operating_margin": _safe_get(info, "operatingMargins"),
        "roe": _safe_get(info, "returnOnEquity"),
        "roa": _safe_get(info, "returnOnAssets"),
        "revenue_growth": _safe_get(info, "revenueGrowth"),
        "earnings_growth": _safe_get(info, "earningsGrowth"),
        "debt_to_equity": _safe_get(info, "debtToEquity"),
        "current_ratio": _safe_get(info, "currentRatio"),
        "free_cash_flow": _safe_get(info, "freeCashflow"),
        "operating_cash_flow": _safe_get(info, "operatingCashflow"),
        "total_revenue": _safe_get(info, "totalRevenue"),
        "ebitda": _safe_get(info, "ebitda"),
        "total_debt": _safe_get(info, "totalDebt"),
        "total_cash": _safe_get(info, "totalCash"),
        "shares_outstanding": _safe_get(info, "sharesOutstanding"),
        "beta": _safe_get(info, "beta"),
        "dividend_yield": _safe_get(info, "dividendYield"),
    }

    # --- Financial statements (last 4 years/quarters) ---
    try:
        income_stmt = _df_to_records(tk.financials)
        balance_sheet = _df_to_records(tk.balance_sheet)
        cash_flow = _df_to_records(tk.cashflow)
    except Exception as e:
        logger.warning(f"Statement fetch issue for {ticker}: {e}")
        income_stmt, balance_sheet, cash_flow = [], [], []

    # --- Price history (1 year, monthly closes for charting) ---
    price_history = []
    try:
        hist = tk.history(period="1y", interval="1mo")
        if not hist.empty:
            for idx, row in hist.iterrows():
                price_history.append({
                    "date": idx.strftime("%Y-%m-%d"),
                    "close": float(row["Close"]),
                    "volume": int(row["Volume"]) if not pd.isna(row["Volume"]) else 0,
                })
    except Exception as e:
        logger.warning(f"Price history issue for {ticker}: {e}")

    # --- Recent news headlines ---
    news = []
    try:
        raw_news = tk.news or []
        for item in raw_news[:8]:
            content = item.get("content", item)  # yfinance schema shifted recently
            title = content.get("title") or item.get("title", "")
            publisher = (
                content.get("provider", {}).get("displayName")
                if isinstance(content.get("provider"), dict)
                else item.get("publisher", "")
            )
            pub_date = content.get("pubDate") or item.get("providerPublishTime", "")
            if isinstance(pub_date, (int, float)):
                pub_date = datetime.fromtimestamp(pub_date).strftime("%Y-%m-%d")
            if title:
                news.append({
                    "title": title,
                    "publisher": publisher or "",
                    "date": str(pub_date),
                })
    except Exception as e:
        logger.warning(f"News fetch issue for {ticker}: {e}")

    return {
        "profile": profile,
        "metrics": metrics,
        "income_statement": income_stmt,
        "balance_sheet": balance_sheet,
        "cash_flow": cash_flow,
        "price_history": price_history,
        "news": news,
        "fetched_at": datetime.utcnow().isoformat(),
    }
