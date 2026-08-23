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
        latest_row = sorted_rows[-1]

        # FCF CAGR over available history, anchored on the latest fiscal year.
        fcf_vals = [r["fcf"] for r in sorted_rows if r.get("fcf") is not None and r["fcf"] > 0]
        if latest_row.get("fcf") is not None and latest_row["fcf"] > 0 and len(fcf_vals) >= 2:
            n = len(fcf_vals) - 1
            cagr = ((fcf_vals[-1] / fcf_vals[0]) ** (1.0 / n) - 1.0) * 100.0
            ratios["fcf_cagr_pct"] = max(-40.0, min(40.0, cagr))
        else:
            ratios["fcf_cagr_pct"] = None

        def anchored_delta(field: str) -> Optional[float]:
            latest_value = latest_row.get(field)
            if latest_value is None:
                return None
            older_values = [r[field] for r in sorted_rows[:-1] if r.get(field) is not None]
            if not older_values:
                return None
            return latest_value - older_values[0]

        # Operating margin trend: latest minus oldest (positive = expanding)
        ratios["operating_margin_trend"] = anchored_delta("operating_margin")

        # ROE trend: latest minus oldest
        ratios["roe_trend"] = anchored_delta("roe")

        # Gross margin trend
        ratios["gross_margin_trend"] = anchored_delta("gross_margin")

        # Debt/EBITDA trend: negative = deleveraging (good)
        ratios["debt_trend"] = anchored_delta("debt_to_ebitda")
    else:
        for key in ("fcf_cagr_pct", "operating_margin_trend", "roe_trend", "gross_margin_trend", "debt_trend"):
            ratios[key] = None

    return ratios
