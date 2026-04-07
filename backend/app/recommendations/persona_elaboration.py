"""
Dense, investor-readable elaboration for each persona lens.
Derived from the same inputs as scores + checklists (no new signals).
"""

from __future__ import annotations

from typing import Any, Optional


LENS_COPY: dict[str, dict[str, str]] = {
    "buffett": {
        "measures": (
            "This lens approximates an owner-operator read: economic moat via sector-relative ROIC and gross margins, "
            "FCF margin as a fraction of revenue (not raw dollars), leverage discipline, and improving multi-year trends."
        ),
        "formula": (
            "Scoring engine: base 50 + soft(ROIC, sector band, ±14) + soft(gross margin, sector band, ±10) "
            "+ soft(FCF/revenue %, 15%→0%, ±10) + soft(Debt/EBITDA, 0.5→3.5, ±8) "
            "+ trend bonuses (gross margin trend ±3, FCF CAGR ±3). Sector-relative thresholds applied."
        ),
    },
    "ackman": {
        "measures": (
            "Ackman-style concentrated quality: operating excellence, capital efficiency, and balance-sheet capacity "
            "to withstand stress. Margin expansion over 3 years is rewarded as a secondary signal."
        ),
        "formula": (
            "Scoring engine: base 45 + soft(op margin, sector band, ±14) + soft(interest coverage, 12→3, ±10) "
            "+ soft(ROIC, sector band, ±8) + operating margin trend bonus (±5). Sector-relative thresholds."
        ),
    },
    "wood": {
        "measures": (
            "Growth and innovation tilt: top-line momentum is primary, gross margin shows scalability, "
            "FCF CAGR shows the growth is converting to cash. P/E penalty removed—Wood accepts high valuations."
        ),
        "formula": (
            "Scoring engine: base 35 + soft(revenue growth %, 25→5, ±20) + soft(gross margin %, 60→30, ±10) "
            "+ FCF CAGR bonus (±8). No P/E penalty."
        ),
    },
    "burry": {
        "measures": (
            "Balance-sheet-first and contrarian value: liquidity cushion, sector-adjusted leverage discipline, "
            "interest burden, and headline valuation multiples. Deleveraging trend is rewarded."
        ),
        "formula": (
            "Scoring engine: base 45 + soft(current ratio, 2.5→0.8, ±12) + soft(Debt/EBITDA, sector-adj, ±12) "
            "+ soft(interest coverage, 10→2, ±8) + soft(P/E, 12→30, ±8) + debt trend bonus (±4). Sector-adjusted."
        ),
    },
    "pelosi_proxy": {
        "measures": (
            "This lens has been retired from active scoring. Its 5% weight has been redistributed to the "
            "Buffett (+3%) and Burry (+2%) lenses. Score is shown as 0 for schema compatibility."
        ),
        "formula": "Retired. Score = 0. Weight = 0.",
    },
    "institutional": {
        "measures": (
            "Allocator constraints: ROE relative to sector norms, revenue scale as a size proxy (replaces "
            "hardcoded market cap), and net margin as an earnings quality signal."
        ),
        "formula": (
            "Scoring engine: base 45 + soft(ROE %, sector band, ±14) + soft(revenue $B, 50→5, ±8) "
            "+ soft(net margin %, 15→3, ±8) + ROE trend bonus (±4). Sector-relative thresholds."
        ),
    },
}


def _f(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v


def _digest_checklist(items: list[dict[str, Any]]) -> dict[str, Any]:
    passed = [c for c in items if c.get("pass")]
    failed = [c for c in items if not c.get("pass")]
    return {
        "pass_count": len(passed),
        "fail_count": len(failed),
        "passed_criteria": [c.get("criterion", "") for c in passed],
        "failed_criteria": [c.get("criterion", "") for c in failed],
        "failed_detail": [
            {
                "criterion": c.get("criterion"),
                "actual": c.get("actual"),
                "threshold": c.get("threshold"),
                "comparator": c.get("comparator"),
            }
            for c in failed
        ],
    }


def _trend_paragraph(lens_key: str, trends: list[dict[str, Any]]) -> str:
    if len(trends) < 2:
        return "Less than two fiscal years in the trend strip—multi-year lens context is limited until more 10-K history is loaded."
    newest = trends[0]
    oldest = trends[-1]
    fy_n = newest.get("fiscal_year")
    fy_o = oldest.get("fiscal_year")

    def span(label: str, field: str, is_pct: bool = True) -> Optional[str]:
        a, b = _f(oldest.get(field)), _f(newest.get(field))
        if a is None or b is None:
            return None
        suf = "%" if is_pct else ""
        delta = b - a
        return f"{label} {a:.2f}{suf} (FY{fy_o}) → {b:.2f}{suf} (FY{fy_n}), net {delta:+.2f}{suf}"

    parts: list[str] = []
    if lens_key == "buffett":
        for lab, fld in (("Gross margin", "gross_margin"), ("ROIC", "roic"), ("Operating margin", "operating_margin")):
            s = span(lab, fld)
            if s:
                parts.append(s + ".")
        rev_o, rev_n = _f(oldest.get("revenue")), _f(newest.get("revenue"))
        if rev_o and rev_n and rev_o > 0:
            chg = (rev_n - rev_o) / rev_o * 100
            parts.append(f"Revenue scale moved ~{chg:+.1f}% from FY{fy_o} to FY{fy_n} (reported units as stored).")
    elif lens_key == "ackman":
        for lab, fld in (("Operating margin", "operating_margin"), ("ROIC", "roic")):
            s = span(lab, fld)
            if s:
                parts.append(s + ".")
    elif lens_key == "wood":
        s = span("Gross margin", "gross_margin")
        if s:
            parts.append(s + ".")
        rev_o, rev_n = _f(oldest.get("revenue")), _f(newest.get("revenue"))
        if rev_o and rev_n and rev_o > 0:
            parts.append(f"Revenue {rev_o:.0f} → {rev_n:.0f} across FY{fy_o}–FY{fy_n} (store units).")
    elif lens_key == "burry":
        for lab, fld in (("Current ratio", "current_ratio"), ("Debt/EBITDA", "debt_to_ebitda")):
            s = span(lab, fld, is_pct=False)
            if s:
                parts.append(s + ".")
        pe_o, pe_n = _f(oldest.get("valuation_pe")), _f(newest.get("valuation_pe"))
        if pe_o and pe_n:
            parts.append(f"P/E {pe_o:.1f} → {pe_n:.1f} over the window.")
    elif lens_key == "institutional":
        s = span("ROE", "roe")
        if s:
            parts.append(s + ".")
    else:
        parts.append("Multi-year filing trend is shown primarily through other lenses; Pelosi slot has no trend hook in this build.")

    return " ".join(parts) if parts else "Trend fields were sparse for this lens; expand filing coverage to tighten the arc."


def _keyword_note(lens_key: str, kw: dict[str, int]) -> Optional[str]:
    risk = kw.get("risk") or 0
    debt = kw.get("debt") or 0
    lit = kw.get("litigation") or 0
    growth = kw.get("growth") or 0
    if lens_key == "burry":
        return (
            f"10-K text keyword counts (illustrative, not scored into this lens): "
            f"“debt” {debt}, “risk” {risk}, “litigation” {lit}. Elevated counts deserve a qualitative read in the risk section."
        )
    if lens_key == "wood":
        return f"10-K mentions of “growth” as a crude narrative intensity proxy: {growth} hits across parsed filing text."
    if lens_key == "buffett":
        return f"10-K mentions of “risk” / “debt” (narrative density only): {risk} / {debt}."
    return None


def _driver_lines(lens_key: str, latest: Any, revenue_growth: float, raw_metrics: dict[str, Any]) -> list[str]:
    lines: list[str] = []

    def gv(attr: str) -> Optional[float]:
        return _f(getattr(latest, attr, None))

    rev = gv("revenue") or 0.0
    rev_bn = rev / 1e9

    if lens_key == "buffett":
        lines.append(f"ROIC {gv('roic') or 0:.1f}% — primary moat signal; sector-relative threshold applied (±14 pts).")
        lines.append(f"Gross margin {gv('gross_margin') or 0:.1f}% — pricing power proxy (±10 pts, sector-adjusted).")
        fcf = gv("fcf") or 0.0
        fcf_margin = (fcf / rev * 100.0) if rev > 0 else 0.0
        lines.append(f"FCF margin {fcf_margin:.1f}% of revenue — normalised so large-cap doesn't dominate (±10 pts).")
        lines.append(f"Debt/EBITDA {gv('debt_to_ebitda') or 0:.2f}× — leverage penalty (±8 pts, sector-adjusted).")
    elif lens_key == "ackman":
        lines.append(f"Operating margin {gv('operating_margin') or 0:.1f}% — core profitability (±14 pts, sector-adjusted).")
        lines.append(f"Interest coverage {gv('interest_coverage') or 0:.1f}× — financial safety buffer (±10 pts).")
        lines.append(f"ROIC {gv('roic') or 0:.1f}% — capital efficiency (±8 pts).")
        lines.append("Operating margin 3-year trend also modifies score (±5 pts).")
    elif lens_key == "wood":
        lines.append(f"Revenue growth {revenue_growth:.1f}% YoY — primary signal (±20 pts; good=25%, ok=5%).")
        lines.append(f"Gross margin {gv('gross_margin') or 0:.1f}% — scalability of growth (±10 pts).")
        lines.append("FCF CAGR (3Y) — secondary growth-to-cash conversion signal (±8 pts).")
        lines.append("No P/E penalty — Wood accepts elevated valuations for disruptive growth.")
    elif lens_key == "burry":
        lines.append(f"Current ratio {gv('current_ratio') or 0:.2f} — liquidity buffer (±12 pts; good=2.5, bad=0.8).")
        lines.append(f"Debt/EBITDA {gv('debt_to_ebitda') or 0:.2f}× — leverage (±12 pts, sector-adjusted thresholds).")
        lines.append(f"Interest coverage {gv('interest_coverage') or 0:.1f}× — debt serviceability (±8 pts).")
        pe = gv("valuation_pe")
        if pe and pe > 0:
            lines.append(f"P/E {pe:.1f}× — valuation discipline (±8 pts; good=12×, bad=30×).")
        lines.append("Deleveraging trend (3Y) adds up to ±4 pts.")
    elif lens_key == "pelosi_proxy":
        lines.append("Lens retired. Score = 0. Weight redistributed to Buffett (+3%) and Burry (+2%).")
    elif lens_key == "institutional":
        lines.append(f"ROE {gv('roe') or 0:.1f}% — primary return signal (±14 pts, sector-adjusted).")
        lines.append(f"Revenue ${rev_bn:.1f}B — scale proxy replacing hardcoded market cap (±8 pts; good=$50B+).")
        lines.append(f"Net margin {gv('net_margin') or 0:.1f}% — earnings quality (±8 pts).")
        lines.append("ROE 3-year trend adds up to ±4 pts.")

    return lines


def _verdict_paragraph(lens_key: str, digest: dict[str, Any]) -> str:
    if lens_key == "pelosi_proxy":
        return "No pass/fail grid is attached; the lens is a small, fixed-weight overlay."
    p, f = digest["pass_count"], digest["fail_count"]
    if f == 0:
        return f"All {p} checklist gates cleared for this lens—filing metrics meet or beat every stated threshold."
    failed = digest.get("failed_criteria") or []
    failed_s = ", ".join(failed) if failed else "see criteria table"
    return (
        f"{p} of {p + f} gates passed. "
        f"The lens is held back primarily by: {failed_s}. "
        "Those misses are arithmetic in the checklist layer; the headline lens score still blends the continuous formula above."
    )


def build_persona_lens_elaboration(
    *,
    score_card: dict[str, float],
    weights: dict[str, float],
    persona_checklist: dict[str, list[dict[str, Any]]],
    latest: Any,
    revenue_growth: float,
    trend_rows: list[dict[str, Any]],
    keyword_counts: dict[str, int],
    raw_metrics: dict[str, Any],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    score_keys = {
        "buffett": "buffett_score",
        "ackman": "ackman_score",
        "wood": "wood_score",
        "burry": "burry_score",
        "pelosi_proxy": "pelosi_proxy_score",
        "institutional": "institutional_score",
    }

    for lens_key, sk in score_keys.items():
        meta = LENS_COPY[lens_key]
        raw_score = float(score_card.get(sk) or 0.0)
        w = float(weights.get(lens_key) or 0.0)
        contrib = raw_score * w

        checklist_items = persona_checklist.get(lens_key, []) if lens_key != "pelosi_proxy" else []
        digest = _digest_checklist(checklist_items) if checklist_items else {
            "pass_count": 0,
            "fail_count": 0,
            "passed_criteria": [],
            "failed_criteria": [],
            "failed_detail": [],
        }

        kw_note = _keyword_note(lens_key, keyword_counts)

        block: dict[str, Any] = {
            "measures": meta["measures"],
            "formula": meta["formula"],
            "raw_score": round(raw_score, 4),
            "weight": w,
            "weighted_points": round(contrib, 4),
            "blend_equation": f"{raw_score:.2f} (lens) × {w:.4f} (weight) = {contrib:.2f} weighted points toward the blended score.",
            "driver_lines": _driver_lines(lens_key, latest, revenue_growth, raw_metrics),
            "checklist_digest": digest,
            "checklist_verdict": _verdict_paragraph(lens_key, digest),
            "trend_paragraph": _trend_paragraph(lens_key, trend_rows),
            "keyword_note": kw_note,
        }
        out[lens_key] = block

    return out
