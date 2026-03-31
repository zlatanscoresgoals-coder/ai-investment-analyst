from typing import Optional


def compute_financial_ratios(latest_metrics: dict, prior_metrics: Optional[dict] = None) -> dict:
    ratios = dict(latest_metrics)

    if prior_metrics and prior_metrics.get("revenue"):
        growth = ((latest_metrics.get("revenue", 0) - prior_metrics["revenue"]) / prior_metrics["revenue"]) * 100
        ratios["revenue_growth_pct"] = growth
    else:
        ratios["revenue_growth_pct"] = 0.0

    return ratios
