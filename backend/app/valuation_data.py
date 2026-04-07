"""Latest FY valuation inputs from SEC Company Facts (XBRL), 10-K / FY only."""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.ingestion.sec_filings import SEC_COMPANYFACTS_URL, _get_json, get_cik_for_ticker
from app.ingestion.sec_xbrl import (
    BUYBACK_TAGS,
    CAPEX_TAGS,
    CASH_TAGS,
    CFO_TAGS,
    DEPRECIATION_TAGS,
    DIVIDEND_TAGS,
    EBITDA_DIRECT_TAGS,
    EPS_BASIC_TAGS,
    EQUITY_TAGS,
    INCOME_BEFORE_TAX_TAGS,
    INTEREST_EXPENSE_TAGS,
    NET_INCOME_TAGS,
    OPERATING_INCOME_TAGS,
    RETAINED_EARNINGS_TAGS,
    TAX_PROVISION_TAGS,
    TOTAL_ASSETS_TAGS,
    collect_fiscal_years_from_revenue,
    effective_tax_rate_pct,
    revenue_for_fy,
    shares_outstanding_for_fy,
    total_debt_for_fy,
    waterfall_eps_basic,
    waterfall_money,
)

logger = logging.getLogger(__name__)


def fetch_latest_valuation_inputs(ticker: str) -> dict[str, Any]:
    """
    Pull figures from SEC companyfacts JSON. Strict: form 10-K, fp FY, latest filed per fy.
    Operating window: last three fiscal years present on the primary revenue tag.
    FCF = operating cash flow − |capital expenditures| using specified concept waterfalls.
    """
    out: dict[str, Any] = {
        "fiscal_year": None,
        "revenue": None,
        "revenue_xbrl_tag": None,
        "net_income": None,
        "stockholders_equity": None,
        "total_assets": None,
        "retained_earnings": None,
        "fcf": None,
        "cfo": None,
        "capex": None,
        "ebitda": None,
        "operating_income": None,
        "depreciation": None,
        "shares_outstanding": None,
        "shares_diluted": None,
        "eps_basic": None,
        "eps_diluted": None,
        "long_term_debt": None,
        "short_term_debt": None,
        "current_portion_long_term_debt": None,
        "total_debt": None,
        "debt_current": None,
        "cash": None,
        "dividends_paid": None,
        "buybacks": None,
        "interest_expense": None,
        "income_tax_expense": None,
        "pretax_income": None,
        "effective_tax_rate_pct": None,
        "historical_window": [],
        "ok": False,
    }
    cik = get_cik_for_ticker(ticker)
    if not cik:
        return out
    try:
        companyfacts = _get_json(SEC_COMPANYFACTS_URL.format(cik=cik))
    except Exception as exc:
        logger.debug("companyfacts %s: %s", ticker, exc)
        return out

    us_gaap = companyfacts.get("facts", {}).get("us-gaap", {})
    if not isinstance(us_gaap, dict):
        return out

    rev_tag, all_fy = collect_fiscal_years_from_revenue(us_gaap)
    if not rev_tag or not all_fy:
        return out

    last_three = sorted(all_fy, reverse=True)[:3]
    anchor_fy = last_three[0]
    out["revenue_xbrl_tag"] = rev_tag
    out["fiscal_year"] = anchor_fy
    out["revenue"] = revenue_for_fy(us_gaap, anchor_fy, rev_tag)

    def _fcf_for_fy(fy_i: int) -> Optional[float]:
        cfo_i = waterfall_money(us_gaap, CFO_TAGS, fy_i)
        cap_raw = waterfall_money(us_gaap, CAPEX_TAGS, fy_i)
        if cfo_i is None or cap_raw is None:
            return None
        return float(cfo_i) - abs(float(cap_raw))

    def _dist_for_fy(fy_i: int) -> tuple[Optional[float], Optional[float], Optional[float]]:
        dv = waterfall_money(us_gaap, DIVIDEND_TAGS, fy_i)
        bv = waterfall_money(us_gaap, BUYBACK_TAGS, fy_i)
        div_a = abs(float(dv)) if dv is not None else None
        bb_a = abs(float(bv)) if bv is not None else None
        tot = None
        if div_a is not None or bb_a is not None:
            tot = (div_a or 0.0) + (bb_a or 0.0)
        return div_a, bb_a, tot

    historical_window: list[dict[str, Any]] = []
    for hfy in sorted(last_three):
        div_h, bb_h, dist_h = _dist_for_fy(hfy)
        historical_window.append(
            {
                "fiscal_year": hfy,
                "fcf": _fcf_for_fy(hfy),
                "net_income": waterfall_money(us_gaap, NET_INCOME_TAGS, hfy),
                "dividends_paid": div_h,
                "buybacks": bb_h,
                "distributions": dist_h,
            }
        )
    out["historical_window"] = historical_window

    fy = anchor_fy
    out["net_income"] = waterfall_money(us_gaap, NET_INCOME_TAGS, fy)
    out["stockholders_equity"] = waterfall_money(us_gaap, EQUITY_TAGS, fy)
    out["total_assets"] = waterfall_money(us_gaap, TOTAL_ASSETS_TAGS, fy)
    out["retained_earnings"] = waterfall_money(us_gaap, RETAINED_EARNINGS_TAGS, fy)

    out["cfo"] = waterfall_money(us_gaap, CFO_TAGS, fy)
    capex_raw = waterfall_money(us_gaap, CAPEX_TAGS, fy)
    out["capex"] = abs(float(capex_raw)) if capex_raw is not None else None
    if out["cfo"] is not None and capex_raw is not None:
        out["fcf"] = float(out["cfo"]) - abs(float(capex_raw))

    out["operating_income"] = waterfall_money(us_gaap, OPERATING_INCOME_TAGS, fy)
    out["depreciation"] = waterfall_money(us_gaap, DEPRECIATION_TAGS, fy)
    ebitda_direct = waterfall_money(us_gaap, EBITDA_DIRECT_TAGS, fy)
    if ebitda_direct is not None:
        out["ebitda"] = ebitda_direct
    elif out["operating_income"] is not None and out["depreciation"] is not None:
        out["ebitda"] = float(out["operating_income"]) + abs(float(out["depreciation"]))
    elif out["operating_income"] is not None:
        out["ebitda"] = float(out["operating_income"])
    else:
        out["ebitda"] = None

    sh = shares_outstanding_for_fy(us_gaap, fy)
    out["shares_outstanding"] = sh
    out["shares_diluted"] = sh

    out["eps_basic"] = waterfall_eps_basic(us_gaap, EPS_BASIC_TAGS, fy)
    out["eps_diluted"] = None

    lt, st, curp, tdebt = total_debt_for_fy(us_gaap, fy)
    out["long_term_debt"] = lt
    out["short_term_debt"] = st
    out["current_portion_long_term_debt"] = curp
    out["total_debt"] = tdebt
    if st is not None or curp is not None:
        out["debt_current"] = (st or 0.0) + (curp or 0.0)
    else:
        out["debt_current"] = None

    out["cash"] = waterfall_money(us_gaap, CASH_TAGS, fy)

    div_raw = waterfall_money(us_gaap, DIVIDEND_TAGS, fy)
    if div_raw is not None:
        out["dividends_paid"] = abs(float(div_raw))

    bb_raw = waterfall_money(us_gaap, BUYBACK_TAGS, fy)
    if bb_raw is not None:
        out["buybacks"] = abs(float(bb_raw))

    out["interest_expense"] = waterfall_money(us_gaap, INTEREST_EXPENSE_TAGS, fy)

    tax_raw = waterfall_money(us_gaap, TAX_PROVISION_TAGS, fy)
    if tax_raw is not None:
        out["income_tax_expense"] = float(tax_raw)

    pre_raw = waterfall_money(us_gaap, INCOME_BEFORE_TAX_TAGS, fy)
    if pre_raw is not None:
        out["pretax_income"] = float(pre_raw)

    out["effective_tax_rate_pct"] = effective_tax_rate_pct(out.get("income_tax_expense"), out.get("pretax_income"))

    out["ok"] = bool(out["revenue"] is not None and out["fiscal_year"])
    return out


def net_debt_from_inputs(v: dict[str, Any]) -> float:
    """
    Net debt = total financial debt − cash & equivalents.
    Returns a signed float: positive = net debt, negative = net cash.
    Net cash companies (e.g. Apple, Google) will have a negative value here,
    which correctly *adds* to equity value in the DCF bridge.
    """
    td = v.get("total_debt")
    if td is not None:
        debt = float(td)
    else:
        lt = float(v.get("long_term_debt") or 0)
        st = float(v.get("short_term_debt") or 0)
        cp = float(v.get("current_portion_long_term_debt") or 0)
        dc = v.get("debt_current")
        if dc is not None:
            debt = lt + float(dc)
        else:
            debt = lt + st + cp
    cash = float(v.get("cash") or 0)
    return debt - cash


def book_value_per_share(v: dict[str, Any]) -> Optional[float]:
    eq = v.get("stockholders_equity")
    sh = v.get("shares_outstanding") or v.get("shares_diluted")
    if eq is None or not sh or float(sh) <= 0:
        return None
    return float(eq) / float(sh)
