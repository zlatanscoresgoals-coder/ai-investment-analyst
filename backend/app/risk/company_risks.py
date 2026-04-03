"""
Build company-specific, categorised risk factors from:
  - SEC 10-K financial metrics (balance sheet, margins, cash flow)
  - 3-year trend analysis
  - Live news headlines with source attribution
  - Sector structural risks

Each risk item carries a severity level: HIGH / MEDIUM / LOW
Risk output is structured by category for rich frontend rendering.
"""
from __future__ import annotations

from typing import Any, Optional


# ─── Severity constants ───────────────────────────────────────────────────────

HIGH   = "HIGH"
MEDIUM = "MEDIUM"
LOW    = "LOW"


# ─── Sector-level structural risks ───────────────────────────────────────────

_SECTOR_RISKS: dict[str, list[dict]] = {
    "Technology": [
        {"text": "AI regulation and data-privacy laws (EU AI Act, US executive orders) could impose compliance costs and restrict product capabilities.", "severity": MEDIUM},
        {"text": "Rapid technology obsolescence — a single architectural shift (e.g. new chip paradigm, open-source disruption) can erode competitive moat quickly.", "severity": MEDIUM},
        {"text": "Customer concentration in cloud/enterprise contracts creates renewal and churn risk in a downturn.", "severity": LOW},
        {"text": "Antitrust scrutiny on big-tech platforms is intensifying globally, with potential for forced divestitures or behavioural remedies.", "severity": MEDIUM},
    ],
    "Communication Services": [
        {"text": "Digital advertising revenue is highly cyclical — a macro slowdown typically causes advertisers to cut budgets faster than GDP contracts.", "severity": HIGH},
        {"text": "Platform regulation (EU DSA/DMA, potential US legislation) could restrict targeted advertising and content moderation practices.", "severity": MEDIUM},
        {"text": "Content licensing and streaming competition are compressing margins across the sector.", "severity": MEDIUM},
        {"text": "User engagement and time-spent metrics are under pressure from short-form video competition.", "severity": LOW},
    ],
    "Consumer Cyclical": [
        {"text": "Discretionary spending contracts sharply in recessions — revenue and margins can fall faster than the broader economy.", "severity": HIGH},
        {"text": "Supply-chain disruptions and input-cost inflation directly compress gross margins when pricing power is limited.", "severity": MEDIUM},
        {"text": "Consumer credit availability and sentiment are key demand drivers — rising delinquencies signal near-term risk.", "severity": MEDIUM},
        {"text": "E-commerce competition and shifting channel mix create structural margin pressure for traditional retailers.", "severity": LOW},
    ],
    "Consumer Defensive": [
        {"text": "Private-label competition is intensifying as retailers expand own-brand ranges, pressuring branded-goods pricing power.", "severity": MEDIUM},
        {"text": "Input-cost inflation (commodities, packaging, logistics) is difficult to fully pass on without volume loss.", "severity": MEDIUM},
        {"text": "Slow organic growth makes M&A execution risk a key value driver — integration failures destroy capital.", "severity": LOW},
    ],
    "Financial Services": [
        {"text": "Net interest margin is highly sensitive to rate cycles — a rapid rate cut cycle compresses bank earnings materially.", "severity": HIGH},
        {"text": "Credit-loss provisions spike in downturns, compressing earnings and potentially requiring capital raises.", "severity": HIGH},
        {"text": "Regulatory capital requirements and stress-test outcomes constrain capital return and growth capacity.", "severity": MEDIUM},
        {"text": "Fintech disruption and digital-wallet adoption are eroding fee income in payments and retail banking.", "severity": MEDIUM},
    ],
    "Healthcare": [
        {"text": "Patent cliffs and generic/biosimilar entry can cause sudden, steep revenue step-downs on key products.", "severity": HIGH},
        {"text": "Drug-pricing legislation (IRA Medicare negotiation, international reference pricing) is a structural headwind to long-term margins.", "severity": HIGH},
        {"text": "Clinical-trial failure risk is binary — a single Phase 3 failure can destroy significant market value.", "severity": MEDIUM},
        {"text": "Reimbursement pressure from payers and PBMs is intensifying across therapeutics and devices.", "severity": MEDIUM},
    ],
    "Energy": [
        {"text": "Commodity price volatility directly drives revenue and free cash flow — oil/gas prices are set by global supply/demand and geopolitics.", "severity": HIGH},
        {"text": "Energy-transition policy and ESG-driven capital allocation are reducing long-term demand for fossil fuels.", "severity": HIGH},
        {"text": "Geopolitical supply disruptions (OPEC+ decisions, sanctions, conflict) create both upside and downside price risk.", "severity": MEDIUM},
        {"text": "Carbon pricing and emissions regulation are increasing operating costs and stranded-asset risk.", "severity": MEDIUM},
    ],
    "Industrials": [
        {"text": "Order-book cyclicality amplifies economic slowdowns — industrial capex is typically cut early in a downturn.", "severity": HIGH},
        {"text": "Raw-material and labour-cost inflation compress margins when long-term contracts limit pricing pass-through.", "severity": MEDIUM},
        {"text": "Reshoring and supply-chain regionalisation trends create both opportunity and execution risk.", "severity": LOW},
    ],
    "Basic Materials": [
        {"text": "Commodity prices are driven by global supply/demand dynamics and are inherently volatile.", "severity": HIGH},
        {"text": "China demand is the dominant swing factor for most industrial metals and bulk materials.", "severity": HIGH},
        {"text": "Environmental compliance costs and permitting risk are rising, increasing project timelines and capex.", "severity": MEDIUM},
    ],
    "Utilities": [
        {"text": "Rising interest rates increase cost of capital and compress regulated returns, reducing equity valuations.", "severity": HIGH},
        {"text": "Grid-modernisation and renewable-transition capex requirements are substantial and require regulatory approval.", "severity": MEDIUM},
        {"text": "Regulatory rate-case outcomes directly set allowed earnings — adverse rulings can impair returns for years.", "severity": MEDIUM},
    ],
}

_DEFAULT_SECTOR_RISKS = [
    {"text": "Sector-specific regulatory or competitive dynamics could affect long-term returns.", "severity": LOW},
    {"text": "Macro conditions (interest rates, FX, inflation) may weigh on earnings and valuations.", "severity": LOW},
]


# ─── Headline → structured risk mapping ──────────────────────────────────────

_HEADLINE_RISK_MAP: list[tuple[tuple[str, ...], str, str]] = [
    # (keywords, risk_text, severity)
    (("securities fraud", "class action", "shareholder lawsuit"),
     "Active securities class-action or shareholder litigation flagged in recent news — legal liability and management distraction risk.",
     HIGH),
    (("sec investigation", "sec charges", "doj investigation", "subpoena", "grand jury"),
     "Regulatory investigation or enforcement action by SEC/DOJ reported — potential fines, settlements, and reputational damage.",
     HIGH),
    (("fraud", "accounting irregularity", "restatement", "material weakness"),
     "Accounting irregularity or fraud allegation in recent news — financial statement reliability risk.",
     HIGH),
    (("bankruptcy", "chapter 11", "insolvency", "liquidity crisis", "debt default"),
     "Solvency or liquidity stress flagged in recent news — existential financial risk.",
     HIGH),
    (("guidance cut", "lowered guidance", "profit warning", "misses estimates", "earnings miss"),
     "Recent earnings miss or guidance reduction — near-term earnings risk and potential estimate cuts.",
     HIGH),
    (("data breach", "cyberattack", "ransomware", "hack", "cybersecurity incident"),
     "Cybersecurity incident reported — regulatory fines, remediation costs, and reputational harm.",
     HIGH),
    (("recall", "product defect", "safety warning", "fda warning"),
     "Product recall or safety issue flagged — liability exposure and brand damage.",
     HIGH),
    (("antitrust", "monopoly ruling", "competition authority", "forced divestiture"),
     "Antitrust action or ruling reported — could restrict business practices or require divestitures.",
     HIGH),
    (("tariff", "trade war", "export ban", "sanctions", "export control", "chip ban"),
     "Trade-policy changes, tariffs, or sanctions flagged — supply-chain disruption and revenue risk.",
     HIGH),
    (("layoff", "layoffs", "mass redundancy", "workforce reduction", "job cuts"),
     "Significant workforce reduction announced — signals cost pressure or strategic pivot.",
     MEDIUM),
    (("ceo resign", "cfo resign", "chief executive resign", "management departure", "leadership change"),
     "Senior management departure — execution and strategy continuity uncertainty.",
     MEDIUM),
    (("downgrade", "sell rating", "price target cut", "underperform"),
     "Analyst downgrade or price-target reduction — reflects deteriorating near-term fundamental outlook.",
     MEDIUM),
    (("credit rating", "rating downgrade", "junk", "negative outlook", "watch negative"),
     "Credit-rating action or negative outlook — could raise funding costs and restrict capital access.",
     MEDIUM),
    (("strike", "union dispute", "labour action", "walkout"),
     "Labour dispute or strike action — operational disruption and wage-cost risk.",
     MEDIUM),
    (("probe", "investigation", "lawsuit", "litigation", "legal action"),
     "Legal or regulatory proceedings noted in recent news — potential financial and reputational impact.",
     MEDIUM),
    (("acquisition", "merger", "takeover bid", "deal announced"),
     "M&A activity reported — integration risk, premium paid, and potential dilution.",
     LOW),
    (("activist investor", "activist stake", "proxy fight"),
     "Activist investor involvement — potential for strategic change, board disruption, or forced sale.",
     LOW),
]


def _extract_headline_risks(
    news_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Match live headlines against risk keywords.
    Returns structured risk items with the triggering headline attached.
    """
    if not news_rows:
        return []

    # Build a searchable blob per headline, keeping the original row for attribution
    matched: list[dict[str, Any]] = []
    seen_risk_texts: set[str] = set()

    for keywords, risk_text, severity in _HEADLINE_RISK_MAP:
        triggering_headlines = []
        for h in news_rows:
            blob = ((h.get("title") or "") + " " + (h.get("description") or "")).lower()
            if any(kw in blob for kw in keywords):
                triggering_headlines.append(h)
        if triggering_headlines and risk_text not in seen_risk_texts:
            seen_risk_texts.add(risk_text)
            matched.append({
                "text": risk_text,
                "severity": severity,
                "category": "News & Market",
                "headlines": triggering_headlines[:3],  # attach up to 3 triggering headlines
            })

    return matched


# ─── Financial-data-driven risk signals ──────────────────────────────────────

def _financial_risks(
    latest: Any,
    revenue_growth: float,
    trend_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []

    def r(text: str, severity: str) -> dict:
        return {"text": text, "severity": severity, "category": "Financial Health", "headlines": []}

    # Leverage
    dtoe = getattr(latest, "debt_to_ebitda", None)
    if dtoe is not None:
        if dtoe > 5.0:
            risks.append(r(f"Very high leverage: Debt/EBITDA of {dtoe:.1f}× — refinancing risk is elevated, especially if rates stay high or earnings deteriorate.", HIGH))
        elif dtoe > 3.5:
            risks.append(r(f"High leverage: Debt/EBITDA of {dtoe:.1f}× exceeds 3.5× — limited financial flexibility and sensitivity to rate rises.", HIGH))
        elif dtoe > 2.5:
            risks.append(r(f"Moderate leverage: Debt/EBITDA of {dtoe:.1f}× warrants monitoring in a rising-rate environment.", MEDIUM))

    # Interest coverage
    ic = getattr(latest, "interest_coverage", None)
    if ic is not None:
        if ic < 2.0:
            risks.append(r(f"Dangerously thin interest coverage of {ic:.1f}× — earnings deterioration could trigger covenant breaches.", HIGH))
        elif ic < 3.5:
            risks.append(r(f"Thin interest coverage of {ic:.1f}× — limited buffer if EBITDA declines.", MEDIUM))

    # FCF
    fcf = getattr(latest, "fcf", None)
    if fcf is not None:
        if fcf < 0:
            fcf_bn = fcf / 1e9
            risks.append(r(f"Negative free cash flow (${fcf_bn:.1f}B) — the company is burning cash and may require external financing or asset sales.", HIGH))
        else:
            rev = getattr(latest, "revenue", None)
            if rev and rev > 0:
                fcf_yield = fcf / rev * 100
                if fcf_yield < 2.0:
                    risks.append(r(f"Very thin FCF conversion ({fcf_yield:.1f}% of revenue) — minimal buffer for shareholder returns, debt service, or reinvestment.", HIGH))
                elif fcf_yield < 5.0:
                    risks.append(r(f"Below-average FCF conversion ({fcf_yield:.1f}% of revenue) — watch for capex creep or working-capital deterioration.", MEDIUM))

    # Margin compression (year-over-year)
    if len(trend_rows) >= 2:
        latest_om = trend_rows[0].get("operating_margin")
        prior_om  = trend_rows[1].get("operating_margin")
        if latest_om is not None and prior_om is not None:
            delta = latest_om - prior_om
            if delta < -5.0:
                risks.append(r(f"Significant operating margin compression: {prior_om:.1f}% → {latest_om:.1f}% ({delta:+.1f}pp YoY) — cost structure or pricing power is deteriorating.", HIGH))
            elif delta < -2.5:
                risks.append(r(f"Operating margin contracted {abs(delta):.1f}pp YoY ({prior_om:.1f}% → {latest_om:.1f}%) — monitor for continued cost pressure.", MEDIUM))

    # Multi-year margin trend
    if len(trend_rows) >= 3:
        oldest_om = trend_rows[2].get("operating_margin")
        latest_om = trend_rows[0].get("operating_margin")
        if oldest_om is not None and latest_om is not None and (oldest_om - latest_om) > 5.0:
            risks.append(r(f"3-year operating margin decline of {oldest_om - latest_om:.1f}pp — structural erosion of profitability.", MEDIUM))

    # Revenue growth
    if revenue_growth < -10.0:
        risks.append(r(f"Revenue declined sharply ({revenue_growth:.1f}% YoY) — significant market-share loss or demand destruction.", HIGH))
    elif revenue_growth < -3.0:
        risks.append(r(f"Revenue contraction of {revenue_growth:.1f}% YoY — top-line weakness may signal structural headwinds.", MEDIUM))
    elif revenue_growth < 0:
        risks.append(r(f"Revenue growth turned slightly negative ({revenue_growth:.1f}%) — watch for sustained deceleration.", LOW))

    # Liquidity
    cr = getattr(latest, "current_ratio", None)
    if cr is not None:
        if cr < 0.8:
            risks.append(r(f"Current ratio of {cr:.2f}× is critically low — near-term liquidity is stressed; the company may need emergency financing.", HIGH))
        elif cr < 1.0:
            risks.append(r(f"Current ratio of {cr:.2f}× is below 1 — short-term obligations exceed current assets; refinancing risk is elevated.", MEDIUM))

    # Gross margin
    gm = getattr(latest, "gross_margin", None)
    if gm is not None:
        if gm < 10.0:
            risks.append(r(f"Very low gross margin ({gm:.1f}%) — minimal pricing power; any cost increase flows directly to operating losses.", HIGH))
        elif gm < 20.0:
            risks.append(r(f"Low gross margin ({gm:.1f}%) — limited cushion to absorb cost increases or competitive pricing pressure.", MEDIUM))

    # ROE
    roe = getattr(latest, "roe", None)
    if roe is not None and roe < 0:
        risks.append(r(f"Negative ROE ({roe:.1f}%) — the company is destroying equity value; review capital allocation and earnings quality.", HIGH))

    return risks


# ─── Filing keyword signals ───────────────────────────────────────────────────

def _filing_risks(keyword_counts: dict[str, int]) -> list[dict[str, Any]]:
    risks = []

    def r(text: str, severity: str) -> dict:
        return {"text": text, "severity": severity, "category": "SEC Filing Signals", "headlines": []}

    lit = keyword_counts.get("litigation", 0)
    if lit > 15:
        risks.append(r(f"Very high litigation density in 10-K filings ({lit} mentions) — material legal exposure likely; review Item 1A and Note disclosures.", HIGH))
    elif lit > 5:
        risks.append(r(f"Elevated litigation mentions in 10-K filings ({lit} hits) — legal proceedings may be a material risk factor.", MEDIUM))

    risk_kw = keyword_counts.get("risk", 0)
    if risk_kw > 100:
        risks.append(r(f"Exceptionally high risk-factor density in filings ({risk_kw} mentions) — management is flagging an unusually broad set of risk factors.", MEDIUM))
    elif risk_kw > 50:
        risks.append(r(f"High risk-factor density in filings ({risk_kw} mentions) — review Item 1A for company-specific disclosures.", LOW))

    debt_kw = keyword_counts.get("debt", 0)
    if debt_kw > 30:
        risks.append(r(f"Debt discussed extensively in filings ({debt_kw} mentions) — capital structure and refinancing are key management concerns.", MEDIUM))

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
    Return structured risk_json with company-specific risks categorised by source and severity.
    """
    fin_risks    = _financial_risks(latest, revenue_growth, trend_rows)
    news_risks   = _extract_headline_risks(news_rows)
    filing_risks = _filing_risks(keyword_counts)
    sector_risks = [
        {**item, "category": "Sector & Macro", "headlines": []}
        for item in _SECTOR_RISKS.get(sector or "", _DEFAULT_SECTOR_RISKS)
    ]

    # All structured items
    all_structured = fin_risks + news_risks + filing_risks + sector_risks

    # Deduplicate by text
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in all_structured:
        if item["text"] not in seen:
            seen.add(item["text"])
            unique.append(item)

    # Flat list for backward compatibility (used by scoring)
    key_risks_flat = [item["text"] for item in unique]

    # Severity counts
    high_count   = sum(1 for i in unique if i["severity"] == HIGH)
    medium_count = sum(1 for i in unique if i["severity"] == MEDIUM)
    low_count    = sum(1 for i in unique if i["severity"] == LOW)

    # Overall risk level
    if high_count >= 3:
        overall = "HIGH"
    elif high_count >= 1 or medium_count >= 3:
        overall = "MEDIUM-HIGH"
    elif medium_count >= 1:
        overall = "MEDIUM"
    else:
        overall = "LOW"

    # Live news feed (all headlines, not just those triggering risks)
    live_news_feed = [
        {
            "title": h.get("title", ""),
            "url": h.get("url", "#"),
            "source": h.get("source_name") or "",
            "published_at": h.get("published_at") or "",
            "description": h.get("description") or "",
        }
        for h in (news_rows or [])
        if h.get("title")
    ]

    return {
        # Structured items with category + severity (new)
        "risk_items": unique,
        # Flat list for backward compat
        "key_risks": key_risks_flat,
        # Summary
        "overall_risk_level": overall,
        "high_count": high_count,
        "medium_count": medium_count,
        "low_count": low_count,
        # Live news feed
        "live_news": live_news_feed,
        "news_fetched_count": len(news_rows),
        # Metadata
        "risk_word_hits": {
            "risk": keyword_counts.get("risk", 0),
            "litigation": keyword_counts.get("litigation", 0),
            "debt": keyword_counts.get("debt", 0),
        },
        "sector": sector or "Unknown",
        "note": (
            "Risks are derived from live news headlines, SEC 10-K financial metrics, "
            "3-year trends, filing keyword analysis, and sector structural factors."
        ),
    }
