"""
Dense, investor-readable elaboration for each persona lens.
Derived from the same inputs as scores + checklists (no new signals).
"""

from __future__ import annotations

from typing import Any, Optional


LENS_COPY: dict[str, dict[str, str]] = {
    "buffett": {
        "measures": (
            "This lens approximates an owner-operator read: economic moat via returns and margins, "
            "sustainability of cash generation, and whether leverage looks prudent relative to cash flows—not hype cycles."
        ),
        "formula": (
            "Scoring engine: base 50 + 0.8×ROIC(%) + 0.3×gross margin(%) + FCF (in billions) − 4×Debt/EBITDA, clamped to 0–100."
        ),
    },
    "ackman": {
        "measures": (
            "Ackman-style concentrated quality: operating excellence, capital efficiency, and balance-sheet capacity "
            "to withstand stress—favoring businesses that compound through operations rather than financial engineering."
        ),
        "formula": (
            "Scoring engine: base 45 + 0.6×operating margin(%) + 2.0×interest coverage + 0.5×ROIC(%), clamped 0–100."
        ),
    },
    "wood": {
        "measures": (
            "Growth and innovation tilt: top-line momentum as a proxy for reinvestment and optionality, "
            "paired with gross structure and a valuation guardrail so growth is not chased blindly."
        ),
        "formula": (
            "Scoring engine: base 40 + 1.0×revenue growth(%) + 0.4×gross margin(%) − 0.15×P/E, clamped 0–100."
        ),
    },
    "burry": {
        "measures": (
            "Balance-sheet-first and contrarian value: liquidity cushion, leverage discipline, interest burden, "
            "and headline valuation multiples—stressing survival and margin of safety."
        ),
        "formula": (
            "Scoring engine: base 50 + 8×current ratio + 1.2×interest coverage − 5×Debt/EBITDA − 0.2×P/E, clamped 0–100."
        ),
    },
    "pelosi_proxy": {
        "measures": (
            "A deliberately lightweight overlay inspired by public trade-disclosure narratives. "
            "It does not ingest congressional filings in this build; it anchors the blend with a neutral midpoint so "
            "the slot exists for future signal wiring."
        ),
        "formula": "Scoring engine: fixed 55.0 in this build (no fundamental inputs). Blend weight is small (5%).",
    },
    "institutional": {
        "measures": (
            "Allocator constraints: scale (market cap proxy), tradability/liquidity score, and profitability breadth (ROE)—"
            "approximating whether a name is mechanically eligible for large mandate sleeves."
        ),
        "formula": (
            "Scoring engine: base 50 + 0.2×market cap (billions) + 0.25×liquidity score + 0.4×ROE(%), clamped 0–100."
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

    if lens_key == "buffett":
        lines.append(f"ROIC (proxy) {gv('roic') or 0:.2f}% — primary positive lever in the Buffett formula (+0.8×).")
        lines.append(f"Gross margin {gv('gross_margin') or 0:.2f}% — adds +0.3× to the score.")
        fcf_b = (gv('fcf') or 0) / 1_000_000_000
        lines.append(f"Free cash flow ~{fcf_b:.2f}B (as stored) — enters roughly dollar-for-dollar in the engine.")
        lines.append(f"Debt/EBITDA {gv('debt_to_ebitda') or 0:.2f} — each turn costs −4 points until clamped.")
    elif lens_key == "ackman":
        lines.append(f"Operating margin {gv('operating_margin') or 0:.2f}% — scaled by +0.6× in the Ackman stack.")
        lines.append(f"Interest coverage {gv('interest_coverage') or 0:.2f}× — scaled by +2.0× (balance-sheet serviceability).")
        lines.append(f"ROIC {gv('roic') or 0:.2f}% — adds +0.5×.")
    elif lens_key == "wood":
        lines.append(f"Revenue growth (YoY proxy) {revenue_growth:.2f}% — +1.0× weight in the Wood formula.")
        lines.append(f"Gross margin {gv('gross_margin') or 0:.2f}% — +0.4×.")
        lines.append(f"P/E {gv('valuation_pe') or 0:.2f} — subtracts 0.15× each point (valuation guardrail).")
    elif lens_key == "burry":
        lines.append(f"Current ratio {gv('current_ratio') or 0:.2f} — +8× in engine (liquidity emphasis).")
        lines.append(f"Interest coverage {gv('interest_coverage') or 0:.2f}× — +1.2×.")
        lines.append(f"Debt/EBITDA {gv('debt_to_ebitda') or 0:.2f} — −5× (leverage penalty).")
        lines.append(f"P/E {gv('valuation_pe') or 0:.2f} — −0.2× (headline multiple discipline).")
    elif lens_key == "pelosi_proxy":
        lines.append("No live drivers: score is pinned to illustrate a future disclosure-feed channel.")
    elif lens_key == "institutional":
        mcap = _f(raw_metrics.get("market_cap_bn"))
        liq = _f(raw_metrics.get("liquidity_score"))
        lines.append(f"Market cap proxy {mcap or 0:.1f}B — +0.2× in the institutional stack.")
        lines.append(f"Liquidity score {liq or 0:.1f} — +0.25× (tradability heuristic).")
        lines.append(f"ROE {gv('roe') or 0:.2f}% — +0.4×.")

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
