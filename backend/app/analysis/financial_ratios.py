from typing import Optional


def compute_financial_ratios(
    latest_metrics: dict,
    prior_metrics: Optional[dict] = None,
    trend_rows: Optional[list[dict]] = None,
) -> dict:
    ratios = dict(latest_metrics)

    # Year-over-year revenue growth
    if prior_metrics and prior_metrics.get("revenue"):
        growth = (
            (latest_metrics.get("revenue", 0) - prior_metrics["revenue"])
            / prior_metrics["revenue"]
        ) * 100
        ratios["revenue_growth_pct"] = growth
    else:
        ratios["revenue_growth_pct"] = 0.0

    # 3-year trend signals derived from the full historical window.
    # These give the scoring layer directional context that single-year snapshots miss.
    if trend_rows and len(trend_rows) >= 2:
        sorted_rows = sorted(trend_rows, key=lambda r: r.get("fiscal_year") or 0)

        # FCF CAGR over available history
        fcf_vals = [r["fcf"] for r in sorted_rows if r.get("fcf") is not None and r["fcf"] > 0]
        if len(fcf_vals) >= 2:
            n = len(fcf_vals) - 1
            ratios["fcf_cagr_pct"] = ((fcf_vals[-1] / fcf_vals[0]) ** (1.0 / n) - 1.0) * 100.0
        else:
            ratios["fcf_cagr_pct"] = None

        # Operating margin trend: latest minus oldest (positive = expanding)
        op_margins = [r["operating_margin"] for r in sorted_rows if r.get("operating_margin") is not None]
        if len(op_margins) >= 2:
            ratios["operating_margin_trend"] = op_margins[-1] - op_margins[0]
        else:
            ratios["operating_margin_trend"] = None

        # ROE trend: latest minus oldest
        roe_vals = [r["roe"] for r in sorted_rows if r.get("roe") is not None]
        if len(roe_vals) >= 2:
            ratios["roe_trend"] = roe_vals[-1] - roe_vals[0]
        else:
            ratios["roe_trend"] = None

        # Gross margin trend
        gm_vals = [r["gross_margin"] for r in sorted_rows if r.get("gross_margin") is not None]
        if len(gm_vals) >= 2:
            ratios["gross_margin_trend"] = gm_vals[-1] - gm_vals[0]
        else:
            ratios["gross_margin_trend"] = None

        # Debt/EBITDA trend: negative = deleveraging (good)
        de_vals = [r["debt_to_ebitda"] for r in sorted_rows if r.get("debt_to_ebitda") is not None]
        if len(de_vals) >= 2:
            ratios["debt_trend"] = de_vals[-1] - de_vals[0]
        else:
            ratios["debt_trend"] = None
    else:
        for key in ("fcf_cagr_pct", "operating_margin_trend", "roe_trend", "gross_margin_trend", "debt_trend"):
            ratios[key] = None

    return ratios
