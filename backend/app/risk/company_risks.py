"""
Build company-specific risk factors from SEC 10-K financials and live headlines.

Risk categories an investor actually cares about:
  - Balance sheet / leverage
  - Profitability trend
  - Cash generation
  - Valuation stretch
  - News-driven (regulatory, litigation, management, macro)
  - Sector / business-model specific
"""
from __future__ import annotations

from typing import Any, Optional


# ─── Sector-level structural risks ───────────────────────────────────────────

_SECTOR_RISKS: dict[str, list[str]] = {
    "Technology": [
        "Rapid technology obsolescence could erode competitive moat.",
        "Regulatory scrutiny on data privacy, AI, and antitrust is intensifying globally.",
        "Customer concentration in cloud/enterprise contracts creates renewal risk.",
    ],
    "Communication Services": [
        "Advertising revenue is cyclical and sensitive to macro downturns.",
        "Content licensing costs and streaming competition compress margins.",
        "Platform regulation (DSA, antitrust) could restrict monetisation.",
    ],
    "Consumer Cyclical": [
        "Discretionary spending contracts sharply in recessions.",
        "Supply-chain disruptions and input-cost inflation directly hit margins.",
        "Consumer sentiment and credit availability drive near-term demand.",
    ],
    "Consumer Defensive": [
        "Private-label competition and retailer bargaining power limit pricing.",
        "Input-cost inflation (commodities, packaging, logistics) is hard to fully pass on.",
        "Slow organic growth makes M&A execution risk a key value driver.",
    ],
    "Financial Services": [
        "Net interest margin is sensitive to rate cycles and yield-curve shape.",
        "Credit-loss provisions spike in downturns, compressing earnings.",
        "Regulatory capital requirements and stress-test outcomes constrain capital return.",
    ],
    "Healthcare": [
        "Patent cliffs and generic/biosimilar competition can cause sudden revenue step-downs.",
        "Drug-pricing legislation and reimbursement pressure weigh on long-term margins.",
        "Clinical-trial failure risk is binary and can destroy significant value.",
    ],
    "Energy": [
        "Commodity price volatility directly drives revenue and free cash flow.",
        "Energy-transition policy and ESG-driven capital allocation reduce long-term demand.",
        "Geopolitical supply disruptions create both upside and downside price risk.",
    ],
    "Industrials": [
        "Order-book cyclicality amplifies economic slowdowns.",
        "Raw-material and labour-cost inflation compress margins when pricing power is limited.",
        "Long project cycles mean revenue recognition lags and backlog quality matters.",
    ],
    "Basic Materials": [
        "Commodity prices are driven by global supply/demand and are highly volatile.",
        "Environmental compliance costs and mine/plant permitting risk are rising.",
        "China demand is the dominant swing factor for many materials.",
    ],
    "Utilities": [
        "Rising interest rates increase cost of capital and compress regulated returns.",
        "Grid-modernisation and renewable-transition capex requirements are substantial.",
        "Regulatory rate-case outcomes directly set allowed earnings.",
    ],
}

_DEFAULT_SECTOR_RISKS = [
    "Sector-specific regulatory or competitive dynamics could affect long-term returns.",
    "Macro conditions (rates, FX, inflation) may weigh on earnings.",
]


# ─── Headline-driven risk signals ────────────────────────────────────────────

_HEADLINE_RISK_MAP: list[tuple[tuple[str, ...], str]] = [
    (("lawsuit", "class action", "securities fraud"), "Active litigation or class-action exposure flagged in recent news."),
    (("sec investigation", "sec charges", "doj", "subpoena", "probe"), "Regulatory investigation or enforcement action reported."),
    (("layoff", "layoffs", "restructuring", "workforce reduction"), "Workforce restructuring signals cost pressure or strategic pivot."),
    (("guidance cut", "lowered guidance", "misses estimates", "profit warning"), "Recent earnings miss or guidance reduction raises near-term earnings risk."),
    (("ceo", "cfo", "chief executive", "management change", "resign"), "Senior management change introduces execution and strategy uncertainty."),
    (("recall", "product defect", "safety"), "Product recall or safety issue could trigger liability and brand damage."),
    (("data breach", "cyberattack", "ransomware", "hack"), "Cybersecurity incident may result in regulatory fines and reputational harm."),
    (("antitrust", "monopoly", "competition authority"), "Antitrust scrutiny could restrict business practices or require divestitures."),
    (("downgrade", "sell rating", "price target cut"), "Analyst downgrades reflect deteriorating near-term fundamental outlook."),
    (("debt", "credit rating", "junk", "default"), "Credit-quality concerns or rating action could raise funding costs."),
    (("tariff", "trade war", "sanctions", "export control"), "Trade-policy changes or sanctions create supply-chain and revenue risk."),
    (("strike", "union", "labour dispute"), "Labour disputes could disrupt operations and increase wage costs."),
]


def _headline_risks(news_rows: list[dict[str, Any]]) -> list[str]:
    if not news_rows:
        return []
    blob = " ".join(
        ((h.get("title") or "") + " " + (h.get("description") or "")).lower()
        for h in news_rows
    )
    found: list[str] = []
    for keywords, risk_text in _HEADLINE_RISK_MAP:
        if any(kw in blob for kw in keywords):
            found.append(risk_text)
    return found


# ─── Financial-data-driven risk signals ──────────────────────────────────────

def _financial_risks(
    latest: Any,
    revenue_growth: float,
    trend_rows: list[dict[str, Any]],
) -> list[str]:
    risks: list[str] = []

    # Leverage
    dtoe = getattr(latest, "debt_to_ebitda", None)
    if dtoe is not None:
        if dtoe > 4.0:
            risks.append(
                f"High leverage: Debt/EBITDA of {dtoe:.1f}× exceeds 4× — refinancing risk rises if rates stay elevated."
            )
        elif dtoe > 2.5:
            risks.append(
                f"Moderate leverage: Debt/EBITDA of {dtoe:.1f}× warrants monitoring in a rising-rate environment."
            )

    # Interest coverage
    ic = getattr(latest, "interest_coverage", None)
    if ic is not None and ic < 3.0:
        risks.append(
            f"Thin interest coverage of {ic:.1f}× — earnings deterioration could stress debt-service capacity."
        )

    # FCF
    fcf = getattr(latest, "fcf", None)
    if fcf is not None and fcf < 0:
        fcf_bn = fcf / 1e9
        risks.append(
            f"Negative free cash flow (${fcf_bn:.2f}B) means the company is consuming cash; "
            "continued capex or working-capital build could require external financing."
        )
    elif fcf is not None:
        rev = getattr(latest, "revenue", None)
        if rev and rev > 0:
            fcf_yield = fcf / rev * 100
            if fcf_yield < 3.0:
                risks.append(
                    f"FCF conversion is thin ({fcf_yield:.1f}% of revenue) — limited buffer for shareholder returns or reinvestment."
                )

    # Margin compression
    if len(trend_rows) >= 2:
        latest_om = trend_rows[0].get("operating_margin")
        prior_om = trend_rows[1].get("operating_margin")
        if latest_om is not None and prior_om is not None:
            delta = latest_om - prior_om
            if delta < -3.0:
                risks.append(
                    f"Operating margin contracted {abs(delta):.1f}pp year-over-year "
                    f"(from {prior_om:.1f}% to {latest_om:.1f}%) — cost pressure or pricing headwinds."
                )

    # Revenue growth
    if revenue_growth < -5.0:
        risks.append(
            f"Revenue declined {abs(revenue_growth):.1f}% — top-line contraction may signal market-share loss or demand weakness."
        )
    elif revenue_growth < 0:
        risks.append(
            f"Revenue growth turned slightly negative ({revenue_growth:.1f}%) — watch for sustained deceleration."
        )

    # Current ratio / liquidity
    cr = getattr(latest, "current_ratio", None)
    if cr is not None and cr < 1.0:
        risks.append(
            f"Current ratio of {cr:.2f}× is below 1 — short-term liquidity is tight; "
            "the company may need to roll over or refinance near-term obligations."
        )

    # Gross margin
    gm = getattr(latest, "gross_margin", None)
    if gm is not None and gm < 20.0:
        risks.append(
            f"Low gross margin ({gm:.1f}%) leaves limited cushion to absorb cost increases or pricing pressure."
        )

    return risks


# ─── Public API ──────────────────────────────────────────────────────────────

def build_company_risk_json(
    company_name: str,
    ticker: str,
    sector: Optional[str],
    latest: Any,
    revenue_growth: float,
    trend_rows: list[dict[str, Any]],
    keyword_counts: dict[str, int],
    news_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Return risk_json with company-specific risks derived from:
      - Balance sheet and income statement metrics (SEC 10-K)
      - Revenue and margin trends (3-year)
      - Live news headlines (litigation, regulatory, management)
      - Sector structural risks
    """
    fin_risks = _financial_risks(latest, revenue_growth, trend_rows)
    news_risks = _headline_risks(news_rows)
    sector_risks = _SECTOR_RISKS.get(sector or "", _DEFAULT_SECTOR_RISKS)

    # Filing keyword signals
    filing_signals: list[str] = []
    if keyword_counts.get("litigation", 0) > 5:
        filing_signals.append(
            f"10-K filings contain elevated litigation mentions ({keyword_counts['litigation']} hits) — legal exposure may be material."
        )
    if keyword_counts.get("risk", 0) > 50:
        filing_signals.append(
            f"High risk-factor density in filings ({keyword_counts['risk']} mentions) — review Item 1A for company-specific disclosures."
        )
    if keyword_counts.get("debt", 0) > 20:
        filing_signals.append(
            f"Debt discussed frequently in filings ({keyword_counts['debt']} mentions) — capital structure is a key management focus."
        )

    # Combine: financial first (most quantitative), then news, then filing signals, then sector
    all_risks = fin_risks + news_risks + filing_signals + sector_risks

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_risks: list[str] = []
    for r in all_risks:
        if r not in seen:
            seen.add(r)
            unique_risks.append(r)

    return {
        "key_risks": unique_risks,
        "risk_word_hits": {
            "risk": keyword_counts.get("risk", 0),
            "litigation": keyword_counts.get("litigation", 0),
            "debt": keyword_counts.get("debt", 0),
        },
        "headline_risk_count": len(news_risks),
        "financial_risk_count": len(fin_risks),
        "sector": sector or "Unknown",
        "note": (
            "Risks are derived from SEC 10-K financial metrics, 3-year trends, "
            "live news headlines, and sector-level structural factors."
        ),
    }
