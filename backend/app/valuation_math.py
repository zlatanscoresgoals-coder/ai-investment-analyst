"""DCF, Graham number, EV/EBITDA heuristic multiples."""

from __future__ import annotations

import math
from typing import Any, Optional

from app.valuation_data import book_value_per_share, net_debt_from_inputs

# Heuristic sector EV/EBITDA anchors (illustrative; not live market data).
SECTOR_EV_EBITDA_ANCHOR: dict[str, float] = {
    "technology": 18.0,
    "software": 20.0,
    "health": 16.0,
    "pharma": 14.0,
    "financial": 10.0,
    "bank": 9.0,
    "energy": 6.5,
    "oil": 6.0,
    "gas": 7.0,
    "consumer": 12.0,
    "retail": 11.0,
    "industrial": 13.0,
    "materials": 8.5,
    "utility": 10.0,
    "real estate": 14.0,
    "communication": 15.0,
    "telecom": 9.0,
    "default": 13.0,
}


def sector_ev_ebitda_multiple(sector: Optional[str], industry: Optional[str]) -> tuple[float, str]:
    blob = f"{sector or ''} {industry or ''}".lower()
    for key, mult in SECTOR_EV_EBITDA_ANCHOR.items():
        if key == "default":
            continue
        if key in blob:
            return mult, key
    return SECTOR_EV_EBITDA_ANCHOR["default"], "default"


def dcf_equity_value(
    fcf0: float,
    g1_pct: float,
    g2_pct: float,
    g_terminal_pct: float,
    wacc_pct: float,
    net_debt: float,
    shares: float,
) -> tuple[Optional[float], Optional[float]]:
    """
    FCFF DCF: five-year forward projection (discounted) + terminal, anchored on latest FY FCF.
    Five prior fiscal years of actual FCF are supplied separately for the 10-year worksheet view.
    Years 1-3 grow at g1; years 4-5 at g2; terminal Gordon from year-6 FCFF.
    """
    if fcf0 is None or shares is None or float(shares) <= 0:
        return None, None
    w = float(wacc_pct) / 100.0
    g1 = float(g1_pct) / 100.0
    g2 = float(g2_pct) / 100.0
    gt = float(g_terminal_pct) / 100.0
    if w <= gt + 0.001:
        w = gt + 0.005
    fcf = float(fcf0)
    pv = 0.0
    for t in range(1, 6):
        if t <= 3:
            fcf *= 1.0 + g1
        else:
            fcf *= 1.0 + g2
        pv += fcf / (1.0 + w) ** t
    fcf_6 = fcf * (1.0 + gt)
    tv = fcf_6 / (w - gt)
    pv += tv / (1.0 + w) ** 5
    equity = max(0.0, pv - float(net_debt or 0))
    return equity, equity / float(shares)


def graham_number(eps: Optional[float], bvps: Optional[float]) -> Optional[float]:
    if eps is None or bvps is None:
        return None
    if eps <= 0 or bvps <= 0:
        return None
    return math.sqrt(22.5 * eps * bvps)


def enterprise_value(market_cap: float, net_debt: float) -> float:
    return float(market_cap) + float(net_debt)


def implied_price_from_ev_multiple(
    ebitda: float,
    ev_ebitda_multiple: float,
    net_debt: float,
    shares: float,
) -> Optional[float]:
    if ebitda is None or ebitda <= 0 or shares is None or float(shares) <= 0:
        return None
    ev = float(ev_ebitda_multiple) * float(ebitda)
    equity = ev - float(net_debt or 0)
    if equity <= 0:
        return None
    return equity / float(shares)


def current_ev_ebitda(price: float, shares: float, net_debt: float, ebitda: float) -> Optional[float]:
    if price is None or shares is None or ebitda is None or ebitda <= 0 or float(shares) <= 0:
        return None
    mc = float(price) * float(shares)
    ev = enterprise_value(mc, net_debt)
    return ev / float(ebitda)


def margin_safety(intrinsic: Optional[float], price: Optional[float]) -> Optional[float]:
    if intrinsic is None or price is None or intrinsic <= 0 or price <= 0:
        return None
    return (intrinsic - price) / intrinsic * 100.0


def upside_vs_price(intrinsic: Optional[float], price: Optional[float]) -> Optional[float]:
    if intrinsic is None or price is None or price <= 0:
        return None
    return (intrinsic - price) / price * 100.0


def ggm_inputs_from_sec(
    sec_inputs: dict[str, Any],
    current_price: Optional[float],
    shares: Optional[float],
) -> dict[str, Any]:
    """Base inputs for frontend Gordon Growth model (distributions + WACC building blocks)."""
    ni = sec_inputs.get("net_income")
    div_v = sec_inputs.get("dividends_paid")
    bb_v = sec_inputs.get("buybacks")
    div = float(div_v) if div_v is not None else 0.0
    bb = float(bb_v) if bb_v is not None else 0.0
    dist_act = div + bb if (div_v is not None or bb_v is not None) else None

    div_pct: Optional[float] = None
    bb_pct: Optional[float] = None
    if ni is not None and float(ni) > 0:
        fni = float(ni)
        if div_v is not None:
            div_pct = min(100.0, max(0.0, div / fni * 100.0))
        if bb_v is not None:
            bb_pct = min(100.0, max(0.0, bb / fni * 100.0))

    tax_rate: Optional[float] = sec_inputs.get("effective_tax_rate_pct")

    td = sec_inputs.get("total_debt")
    if td is not None:
        debt = float(td)
    else:
        debt = float(sec_inputs.get("long_term_debt") or 0) + float(sec_inputs.get("debt_current") or 0)
    cash = float(sec_inputs.get("cash") or 0)
    int_exp = sec_inputs.get("interest_expense")

    int_rate_pct: Optional[float] = None
    if debt > 0 and int_exp is not None and float(int_exp) != 0:
        int_rate_pct = min(20.0, max(0.0, abs(float(int_exp)) / debt * 100.0))

    sh = float(shares) if shares is not None and float(shares) > 0 else None
    px = float(current_price) if current_price is not None and float(current_price) > 0 else None
    e_mkt = sh * px if sh is not None and px is not None else None
    eq_book = sec_inputs.get("stockholders_equity")
    e_book_f = float(eq_book) if eq_book is not None else None

    hist = sec_inputs.get("historical_window") or []
    dist_hist: list[dict[str, Any]] = []
    for row in hist:
        if not isinstance(row, dict):
            continue
        dist_hist.append(
            {
                "fiscal_year": row.get("fiscal_year"),
                "dividends_paid": row.get("dividends_paid"),
                "buybacks": row.get("buybacks"),
                "distributions": row.get("distributions"),
                "net_income": row.get("net_income"),
            }
        )

    return {
        "net_income": float(ni) if ni is not None else None,
        "dividends_paid": float(div_v) if div_v is not None else None,
        "buybacks": float(bb_v) if bb_v is not None else None,
        "distributions_actual": dist_act,
        "dividend_payout_pct_default": div_pct,
        "buyback_rate_pct_default": bb_pct,
        "distribution_growth_pct_default": None,
        "terminal_growth_pct_default": None,
        "risk_free_pct_default": None,
        "beta_default": None,
        "erp_pct_default": None,
        "interest_rate_pct_default": int_rate_pct,
        "tax_rate_pct_default": tax_rate,
        "debt_book": debt,
        "cash": cash,
        "equity_market": e_mkt,
        "equity_book": e_book_f,
        "shares_default": sh,
        "pretax_income": float(pretax) if pretax is not None else None,
        "interest_expense": float(int_exp) if int_exp is not None else None,
        "historical_distributions": dist_hist,
    }


def build_valuation_bundle(
    *,
    ticker: str,
    company_name: str,
    sector: Optional[str],
    industry: Optional[str],
    sec_inputs: dict[str, Any],
    current_price: Optional[float],
    dcf_g1: float = 10.0,
    dcf_g2: float = 5.0,
    dcf_g_term: float = 2.5,
    dcf_wacc: float = 9.0,
) -> dict[str, Any]:
    """Assemble JSON for API + dashboard (defaults match slider defaults)."""
    fy = sec_inputs.get("fiscal_year")
    fcf = sec_inputs.get("fcf")
    shares = sec_inputs.get("shares_outstanding")
    if shares is None:
        shares = sec_inputs.get("shares_diluted")
    eps = sec_inputs.get("eps_basic")
    if eps is None:
        eps = sec_inputs.get("eps_diluted")
    ebitda = sec_inputs.get("ebitda")
    nd = net_debt_from_inputs(sec_inputs)

    bvps = book_value_per_share(sec_inputs)
    graham = graham_number(eps, bvps)

    anchor, anchor_key = sector_ev_ebitda_multiple(sector, industry)

    price = float(current_price) if current_price is not None and current_price > 0 else None

    dcf_iv = None
    ev_equity = None
    if fcf is not None and float(fcf) > 0 and shares and float(shares) > 0:
        ev_equity, dcf_iv = dcf_equity_value(
            float(fcf),
            dcf_g1,
            dcf_g2,
            dcf_g_term,
            dcf_wacc,
            nd,
            float(shares),
        )

    p075 = implied_price_from_ev_multiple(ebitda, 0.75 * anchor, nd, float(shares) if shares else 0)
    p100 = implied_price_from_ev_multiple(ebitda, 1.0 * anchor, nd, float(shares) if shares else 0)
    p125 = implied_price_from_ev_multiple(ebitda, 1.25 * anchor, nd, float(shares) if shares else 0)

    cur_ev_e = None
    if price is not None and shares and ebitda and ebitda > 0:
        cur_ev_e = current_ev_ebitda(price, float(shares), nd, float(ebitda))

    def band_label() -> str:
        if cur_ev_e is None or anchor <= 0:
            return "unknown"
        lo, hi = 0.75 * anchor, 1.25 * anchor
        if cur_ev_e < lo:
            return "below_075x_band"
        if cur_ev_e > hi:
            return "above_125x_band"
        return "within_sector_band"

    warnings: list[str] = []
    if fcf is None or fcf <= 0:
        warnings.append("FCF missing or non-positive — DCF unreliable.")
    if ebitda is None or ebitda <= 0:
        warnings.append("EBITDA missing — EV/EBITDA comps unavailable.")
    if not shares or shares <= 0:
        warnings.append("Share count missing — per-share metrics unavailable.")
    if eps is None or bvps is None or (eps and eps <= 0) or (bvps and bvps <= 0):
        warnings.append("EPS or book value missing/invalid — Graham number unavailable.")
    warnings.append("Sector EV/EBITDA uses a static heuristic, not live peer averages.")

    ggm_block = ggm_inputs_from_sec(sec_inputs, price, float(shares) if shares else None)
    if ggm_block.get("net_income") is None or float(ggm_block["net_income"] or 0) <= 0:
        warnings.append("GGM: net income missing or non-positive — distributions model disabled.")
    if not ggm_block.get("shares_default"):
        warnings.append("GGM: share count missing — per-share output unavailable.")

    hist_fcf = []
    for row in sec_inputs.get("historical_window") or []:
        if isinstance(row, dict) and row.get("fiscal_year") is not None:
            hist_fcf.append({"fiscal_year": row["fiscal_year"], "fcf": row.get("fcf")})

    return {
        "ticker": ticker,
        "company_name": company_name,
        "fiscal_year": fy,
        "revenue_xbrl_tag": sec_inputs.get("revenue_xbrl_tag"),
        "dcf_historical_fcf": hist_fcf,
        "projection_years": 5,
        "fcf": fcf,
        "shares": shares,
        "eps": eps,
        "book_value_per_share": bvps,
        "ebitda": ebitda,
        "net_debt": nd,
        "revenue": sec_inputs.get("revenue"),
        "sector_ev_ebitda_anchor": anchor,
        "sector_ev_ebitda_label": anchor_key,
        "current_price": price,
        "defaults": {
            "g1": dcf_g1,
            "g2": dcf_g2,
            "gTerm": dcf_g_term,
            "wacc": dcf_wacc,
        },
        "dcf_intrinsic_per_share_default": dcf_iv,
        "dcf_equity_value_default": ev_equity,
        "graham_number": graham,
        "ev_implied_price_075x": p075,
        "ev_implied_price_1x": p100,
        "ev_implied_price_125x": p125,
        "company_ev_ebitda_current": cur_ev_e,
        "ev_ebitda_band": band_label(),
        "dcf_margin_safety_pct_default": margin_safety(dcf_iv, price),
        "dcf_upside_pct_default": upside_vs_price(dcf_iv, price),
        "graham_margin_safety_pct": margin_safety(graham, price),
        "graham_upside_pct": upside_vs_price(graham, price),
        "warnings": warnings,
        "sec_ok": bool(sec_inputs.get("ok")),
        "ggm": ggm_block,
    }
