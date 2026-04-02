"""Rule-based two-sentence valuation summary (no external API)."""

from __future__ import annotations

import math
from typing import Any, Literal, Optional

Signal = Literal["below", "above", "inline"]


def _sig(price: Any, intrinsic: Any) -> Optional[Signal]:
    if price is None or intrinsic is None:
        return None
    try:
        p, v = float(price), float(intrinsic)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(p) or not math.isfinite(v) or v <= 0 or p <= 0:
        return None
    if p < v:
        return "below"
    if p > v:
        return "above"
    return "inline"


def _ev_sig(price: Any, implieds: list[Any]) -> Optional[Signal]:
    nums: list[float] = []
    for x in implieds:
        if x is None:
            continue
        try:
            f = float(x)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f) and f > 0:
            nums.append(f)
    if not nums or price is None:
        return None
    try:
        p = float(price)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(p) or p <= 0:
        return None
    lo, hi = min(nums), max(nums)
    if p < lo:
        return "below"
    if p > hi:
        return "above"
    return "inline"


def build_valuation_interpretation(bundle: dict[str, Any]) -> str:
    """
    Exactly two sentences: agreement/divergence of DCF, Graham, and EV-implied band vs price,
    plus a limitations disclaimer. Not investment advice.
    """
    price = bundle.get("current_price")
    dcf = bundle.get("dcf_intrinsic_per_share_default")
    graham = bundle.get("graham_number")
    p075 = bundle.get("ev_implied_price_075x")
    p100 = bundle.get("ev_implied_price_1x")
    p125 = bundle.get("ev_implied_price_125x")

    dcf_s = _sig(price, dcf)
    gr_s = _sig(price, graham)
    ev_s = _ev_sig(price, [p075, p100, p125])

    have = [(n, s) for n, s in (("DCF", dcf_s), ("Graham", gr_s), ("EV/EBITDA comps", ev_s)) if s is not None]
    n = len(have)
    if n == 0:
        s1 = (
            "With the current quote or model anchors missing, these three lenses cannot be compared coherently—"
            "treat the panel as incomplete until SEC inputs and a live price populate."
        )
    elif n == 1:
        name, sig = have[0]
        if sig == "below":
            s1 = (
                f"Only the {name} lens has a usable anchor right now, and it reads the quote as below that level—"
                "the other lenses need more data before they can confirm or contradict."
            )
        elif sig == "above":
            s1 = (
                f"Only the {name} lens is populated, and it reads the quote as above that anchor—"
                "wait for the other lenses to fill in before drawing a broader conclusion."
            )
        else:
            s1 = (
                f"Only the {name} lens is usable here, with the quote roughly in line versus that anchor—"
                "additional inputs would be needed for a multi-lens check."
            )
    else:
        below = sum(1 for _, s in have if s == "below")
        above = sum(1 for _, s in have if s == "above")
        inline = n - below - above
        if below == n:
            s1 = (
                "Across every lens that has data, the quote sits below its anchor, "
                "so they agree directionally on a cheaper versus-model read."
            )
        elif above == n:
            s1 = (
                "Across those same lenses, the quote is above each anchor, "
                "so they align on a richer versus-model read."
            )
        elif below > 0 and above > 0:
            s1 = (
                "The lenses diverge: some anchors lie above the quote and others below, "
                "which often happens when growth, leverage, or multiple assumptions differ across methods."
            )
        elif inline == n:
            s1 = (
                "Versus these anchors the quote is roughly in line with each lens that has data, "
                "without a strong directional gap on this static snapshot."
            )
        else:
            s1 = (
                "The picture is mixed: not all lenses agree on whether the quote is rich or cheap versus their anchors, "
                "so the combined signal is nuanced rather than one-sided."
            )

    s2 = (
        "All figures are illustrative—heuristic sector EV/EBITDA anchors, a simplified multi-stage DCF, "
        "and book-based Graham math—so use them to frame uncertainty, not as a price target or recommendation."
    )
    return f"{s1} {s2}"
