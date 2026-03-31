"""Structured forward-looking investment narrative (illustrative, not a forecast guarantee)."""

from typing import Any, Optional


def build_forward_investment_case(
    company_name: str,
    ticker: str,
    revenue_growth_pct: float,
    operating_margin: Optional[float],
    roe: Optional[float],
    fcf: Optional[float],
    valuation_pe: Optional[float],
    final_score: float,
    top_persona: str,
) -> dict[str, Any]:
    """
    Produces incentive-oriented bullets for the investor. All forward views are scenario-style
    and must be paired with the standard disclaimer in the UI.
    """
    bullets: list[str] = []

    if revenue_growth_pct and revenue_growth_pct > 5:
        bullets.append(
            f"Revenue momentum of roughly {revenue_growth_pct:.1f}% year over year, if sustained, "
            "supports a path to higher earnings power as operating leverage compounds."
        )
    elif revenue_growth_pct and revenue_growth_pct > 0:
        bullets.append(
            "Modest top-line growth, if paired with margin discipline, can still support steady per-share value creation."
        )
    else:
        bullets.append(
            "Stabilization or re-acceleration in revenue would be a key forward catalyst to monitor in filings and guidance."
        )

    if operating_margin is not None and operating_margin > 15:
        bullets.append(
            f"Operating margin near {operating_margin:.1f}% suggests pricing power or cost structure that could defend earnings in a softer macro."
        )

    if roe is not None and roe > 12:
        bullets.append(
            f"Return on equity around {roe:.1f}% indicates capital is being deployed productively; sustained ROE supports compounding narratives."
        )

    if fcf is not None and fcf > 0:
        fcf_b = fcf / 1_000_000_000.0
        if fcf_b >= 1:
            bullets.append(
                f"Positive free cash flow on the order of {fcf_b:.2f} billion creates optionality for buybacks, dividends, or reinvestment at attractive returns."
            )
        else:
            fcf_m = fcf / 1_000_000.0
            bullets.append(
                f"Positive free cash flow near {fcf_m:.1f} million supports balance-sheet flexibility and shareholder returns over time."
            )

    if valuation_pe is not None:
        if valuation_pe < 18:
            bullets.append(
                f"Valuation near {valuation_pe:.1f}x earnings (model proxy) leaves more room for upside if fundamentals improve versus expectations."
            )
        elif valuation_pe > 28:
            bullets.append(
                f"A higher multiple near {valuation_pe:.1f}x implies the market already prices strong growth; the forward case depends on execution beating those expectations."
            )
        else:
            bullets.append(
                f"Valuation near {valuation_pe:.1f}x earnings sits in a middle ground where incremental surprises in growth or margins would matter most."
            )

    bullets.append(
        f"The blended framework score of {final_score:.1f} aligns most closely with a {top_persona}-style thesis; "
        "forward conviction should be validated against your own price target and risk tolerance."
    )

    headline = (
        f"{ticker} ({company_name}) is framed here as a multi-year holding candidate where fundamentals and "
        f"persona alignment ({top_persona}) support continued research—not as a short-term trade signal."
    )

    return {
        "headline": headline,
        "bullets": bullets,
        "horizon_note": "Illustrative view over roughly 12–36 months; not a price target or guaranteed outcome.",
        "disclaimer": (
            "Forward-looking statements are based on historical filings and model assumptions. "
            "They are not investment advice, forecasts, or guarantees. Markets and results can differ materially."
        ),
    }
