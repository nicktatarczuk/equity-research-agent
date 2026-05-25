"""
Smoke test - exercise generators without hitting Gemini.
Run from project root: python test_generators.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.generators import generate_pdf_report, generate_pitch_deck, generate_dcf_model

# Realistic mock state matching what the agent would produce
mock_state = {
    "company_data": {
        "profile": {
            "ticker": "AAPL",
            "name": "Apple Inc.",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "country": "United States",
            "website": "https://apple.com",
            "summary": "Apple Inc. designs, manufactures, and markets smartphones, personal computers, tablets, wearables, and accessories worldwide. The company also sells various related services.",
            "employees": 164000,
            "market_cap": 3_400_000_000_000,
            "enterprise_value": 3_500_000_000_000,
            "currency": "USD",
            "exchange": "NMS",
        },
        "metrics": {
            "current_price": 220.10,
            "52w_high": 237.49,
            "52w_low": 164.08,
            "pe_ratio": 33.5,
            "forward_pe": 28.2,
            "peg_ratio": 2.8,
            "price_to_book": 47.2,
            "ev_to_revenue": 8.9,
            "ev_to_ebitda": 24.5,
            "profit_margin": 0.265,
            "operating_margin": 0.302,
            "roe": 1.547,
            "roa": 0.213,
            "revenue_growth": 0.061,
            "earnings_growth": 0.054,
            "debt_to_equity": 209.0,
            "current_ratio": 0.95,
            "free_cash_flow": 110_000_000_000,
            "operating_cash_flow": 120_000_000_000,
            "total_revenue": 391_000_000_000,
            "ebitda": 134_000_000_000,
            "total_debt": 109_000_000_000,
            "total_cash": 65_000_000_000,
            "shares_outstanding": 15_400_000_000,
            "beta": 1.24,
            "dividend_yield": 0.0044,
        },
        "income_statement": [],
        "balance_sheet": [],
        "cash_flow": [],
        "price_history": [],
        "news": [],
    },
    "business_overview": (
        "Apple Inc. is the world's most valuable consumer technology company, generating "
        "approximately $391 billion in annual revenue through a vertically integrated "
        "ecosystem of hardware, software, and services. Hardware — iPhone, Mac, iPad, "
        "and Wearables — accounts for roughly 75% of revenue, while Services (App Store, "
        "iCloud, Apple Music, advertising) contributes the remaining ~25% at substantially "
        "higher margins.\n\n"
        "The company sells in over 100 countries and benefits from one of the largest "
        "installed bases in consumer electronics, exceeding 2.2 billion active devices. "
        "Apple's premium pricing, brand strength, and integrated software/hardware approach "
        "drive its industry-leading 30%+ operating margins."
    ),
    "investment_thesis": (
        "- Services revenue growing 14% YoY at ~70% gross margins, structurally shifting the mix toward higher-quality earnings\n"
        "- 2.2 billion-device installed base creates a recurring monetization flywheel via App Store, iCloud, and ads\n"
        "- $65B cash position and consistent buybacks (~$90B/year) provide a strong floor under the stock\n"
        "- AI strategy via Apple Intelligence on-device positions the company for an iPhone upgrade super-cycle"
    ),
    "risks": (
        "- iPhone is ~52% of revenue; any cyclical slowdown or share loss in China hits the model disproportionately\n"
        "- Greater China revenue declined 8% YoY, signaling competitive pressure from Huawei and Xiaomi\n"
        "- Antitrust risk: App Store commission structure under regulatory scrutiny in EU (DMA) and US (DOJ)\n"
        "- Valuation at 33x P/E vs ~21x five-year average leaves limited room for execution mistakes"
    ),
    "competitive_position": (
        "Apple sits at the premium end of the consumer electronics value chain with an "
        "unmatched vertically integrated stack (silicon design, OS, services, retail). "
        "Its primary competitors — Samsung in smartphones, Microsoft and Google in software, "
        "and Huawei/Xiaomi in international markets — each compete on individual axes but "
        "lack Apple's ecosystem lock-in. The moat rests on switching costs (iMessage, "
        "iCloud, Apple Watch pairing) and brand premium that allows 50%+ gross margins on hardware."
    ),
    "dcf_assumptions": {
        "revenue_growth_y1": 0.06,
        "revenue_growth_y2": 0.055,
        "revenue_growth_y3": 0.05,
        "revenue_growth_y4": 0.045,
        "revenue_growth_y5": 0.04,
        "fcf_margin": 0.28,
        "terminal_growth": 0.025,
        "wacc": 0.085,
        "rationale": "Conservative growth tapering reflecting iPhone maturity; 28% FCF margin tracks recent history; WACC slightly above 10Y treasury given low-beta cash-generative profile.",
    },
    "dcf_valuation": {
        "projected_revenues": [414_460_000_000, 437_255_000_000, 459_118_000_000, 479_778_000_000, 498_969_000_000],
        "projected_fcfs": [116_049_000_000, 122_431_000_000, 128_553_000_000, 134_338_000_000, 139_711_000_000],
        "pv_fcfs": [106_958_000_000, 104_009_000_000, 100_658_000_000, 96_945_000_000, 92_898_000_000],
        "terminal_value": 2_383_000_000_000,
        "pv_terminal": 1_585_000_000_000,
        "enterprise_value": 2_086_000_000_000,
        "equity_value": 2_042_000_000_000,
        "implied_share_price": 232.50,
        "current_share_price": 220.10,
        "upside_pct": 0.0564,
    },
    "executive_summary": (
        "Apple Inc. (AAPL) is the largest consumer technology company by revenue and market "
        "capitalization, generating $391B in TTM revenue across a vertically integrated "
        "hardware and services platform. We initiate coverage with a HOLD rating and a "
        "12-month price target of $232.50, implying approximately 5.6% upside from the "
        "current price of $220.10.\n\n"
        "Our base case is supported by Apple's accelerating Services segment (14% YoY growth "
        "at ~70% gross margins), an installed base exceeding 2.2 billion active devices, and "
        "approximately $90B in annual buybacks providing a strong support floor. The Apple "
        "Intelligence rollout could catalyze an iPhone upgrade cycle in fiscal year 2026.\n\n"
        "Key risks include continued share loss in Greater China (revenue down 8% YoY), "
        "App Store antitrust pressure in the EU and US, and a current 33x P/E multiple that "
        "leaves limited margin for execution missteps. We see better risk-adjusted entry "
        "points below $200."
    ),
    "recommendation": "HOLD",
    "target_price": 232.50,
    "log": [
        "[data_collector] Fetching data for AAPL",
        "[data_collector] Retrieved 4 years of financials",
        "[researcher] Generating qualitative analysis",
        "[researcher] Completed 4 analytical sections",
        "[analyst] Building DCF model",
        "[analyst] DCF complete. Implied price: $232.50",
        "[writer] Synthesizing final recommendation",
        "[writer] Final recommendation: HOLD | Target: $232.50",
    ],
}

print("Testing PDF generator...")
pdf = generate_pdf_report(mock_state)
with open("/tmp/test_report.pdf", "wb") as f:
    f.write(pdf)
print(f"  ✓ PDF: {len(pdf):,} bytes")

print("Testing PPTX generator...")
pptx = generate_pitch_deck(mock_state)
with open("/tmp/test_deck.pptx", "wb") as f:
    f.write(pptx)
print(f"  ✓ PPTX: {len(pptx):,} bytes")

print("Testing XLSX generator...")
xlsx = generate_dcf_model(mock_state)
with open("/tmp/test_model.xlsx", "wb") as f:
    f.write(xlsx)
print(f"  ✓ XLSX: {len(xlsx):,} bytes")

print("\nAll three generators ran successfully.")
