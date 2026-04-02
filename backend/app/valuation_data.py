"""Latest FY valuation inputs from SEC Company Facts (XBRL)."""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.ingestion.sec_filings import SEC_COMPANYFACTS_URL, _get_json, get_cik_for_ticker

logger = logging.getLogger(__name__)


def _value_for_fy(companyfacts: dict[str, Any], tags: list[str], fy: int) -> Optional[float]:
    us_gaap = companyfacts.get("facts", {}).get("us-gaap", {})
    for tag in tags:
        tag_obj = us_gaap.get(tag)
        if not tag_obj:
            continue
        for _, entries in tag_obj.get("units", {}).items():
            for entry in entries:
                if entry.get("form") != "10-K":
                    continue
                if int(entry.get("fy", 0) or 0) != fy:
                    continue
                val = entry.get("val")
                if isinstance(val, (int, float)):
                    return float(val)
    return None


def fetch_latest_valuation_inputs(ticker: str) -> dict[str, Any]:
    """
    Pull latest fiscal year (anchored to revenue 10-K) figures for DCF / Graham / EV-EBITDA.
    All amounts USD as reported; shares in units.
    """
    out: dict[str, Any] = {
        "fiscal_year": None,
        "revenue": None,
        "net_income": None,
        "stockholders_equity": None,
        "fcf": None,
        "cfo": None,
        "capex": None,
        "ebitda": None,
        "operating_income": None,
        "depreciation": None,
        "shares_diluted": None,
        "eps_diluted": None,
        "long_term_debt": None,
        "debt_current": None,
        "cash": None,
        "dividends_paid": None,
        "buybacks": None,
        "interest_expense": None,
        "income_tax_expense": None,
        "pretax_income": None,
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
    revenue_fy: set[int] = set()
    for tag in (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ):
        tag_obj = us_gaap.get(tag)
        if not tag_obj:
            continue
        for _, entries in tag_obj.get("units", {}).items():
            for entry in entries:
                if entry.get("form") != "10-K":
                    continue
                fy = entry.get("fy")
                if fy:
                    revenue_fy.add(int(fy))
        if revenue_fy:
            break
    if not revenue_fy:
        return out
    fy = max(revenue_fy)

    def _fcf_for_fy(fy_i: int) -> Optional[float]:
        cfo_i = _value_for_fy(companyfacts, ["NetCashProvidedByUsedInOperatingActivities"], fy_i)
        cap_i = _value_for_fy(companyfacts, ["PaymentsToAcquirePropertyPlantAndEquipment"], fy_i)
        if cap_i is not None:
            cap_i = abs(float(cap_i))
        if cfo_i is not None and cap_i is not None:
            return float(cfo_i) - cap_i
        return None

    def _dist_for_fy(fy_i: int) -> tuple[Optional[float], Optional[float], Optional[float]]:
        dv = _value_for_fy(
            companyfacts,
            ["PaymentsOfDividends", "DividendsPaid", "DividendPaid"],
            fy_i,
        )
        bv = _value_for_fy(
            companyfacts,
            [
                "PaymentsForRepurchaseOfCommonStock",
                "PaymentsForRepurchaseOfEquity",
                "PaymentsForRepurchaseOfCommonAndPreferredStock",
            ],
            fy_i,
        )
        div_a = abs(float(dv)) if dv is not None else None
        bb_a = abs(float(bv)) if bv is not None else None
        tot = None
        if div_a is not None or bb_a is not None:
            tot = (div_a or 0.0) + (bb_a or 0.0)
        return div_a, bb_a, tot

    historical_window: list[dict[str, Any]] = []
    for off in (4, 3, 2, 1, 0):
        hfy = fy - off
        if hfy <= 2000:
            continue
        div_h, bb_h, dist_h = _dist_for_fy(hfy)
        historical_window.append(
            {
                "fiscal_year": hfy,
                "fcf": _fcf_for_fy(hfy),
                "net_income": _value_for_fy(companyfacts, ["NetIncomeLoss"], hfy),
                "dividends_paid": div_h,
                "buybacks": bb_h,
                "distributions": dist_h,
            }
        )
    out["historical_window"] = historical_window

    out["fiscal_year"] = fy
    out["revenue"] = _value_for_fy(
        companyfacts,
        [
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
        ],
        fy,
    )
    out["net_income"] = _value_for_fy(companyfacts, ["NetIncomeLoss"], fy)
    out["stockholders_equity"] = _value_for_fy(companyfacts, ["StockholdersEquity"], fy)
    out["cfo"] = _value_for_fy(companyfacts, ["NetCashProvidedByUsedInOperatingActivities"], fy)
    capex = _value_for_fy(companyfacts, ["PaymentsToAcquirePropertyPlantAndEquipment"], fy)
    if capex is not None:
        capex = abs(capex)
    out["capex"] = capex
    if out["cfo"] is not None and capex is not None:
        out["fcf"] = out["cfo"] - capex

    out["ebitda"] = _value_for_fy(
        companyfacts,
        [
            "EarningsBeforeInterestTaxesDepreciationAmortization",
            "EarningsBeforeInterestTaxesDepreciationAndAmortization",
        ],
        fy,
    )
    out["operating_income"] = _value_for_fy(companyfacts, ["OperatingIncomeLoss"], fy)
    out["depreciation"] = _value_for_fy(
        companyfacts,
        [
            "DepreciationDepletionAndAmortization",
            "DepreciationAndAmortization",
            "OperatingExpensesDepreciationAndAmortization",
        ],
        fy,
    )
    if out["ebitda"] is None and out["operating_income"] is not None and out["depreciation"] is not None:
        out["ebitda"] = out["operating_income"] + abs(out["depreciation"])

    out["shares_diluted"] = _value_for_fy(
        companyfacts,
        [
            "WeightedAverageNumberOfDilutedSharesOutstanding",
            "WeightedAverageNumberOfSharesOutstandingBasicAndDiluted",
            "CommonStockSharesOutstanding",
            "EntityCommonStockSharesOutstanding",
        ],
        fy,
    )
    out["eps_diluted"] = _value_for_fy(
        companyfacts,
        [
            "EarningsPerShareDiluted",
            "EarningsPerShareBasic",
        ],
        fy,
    )
    if out["eps_diluted"] is None and out["net_income"] and out["shares_diluted"] and out["shares_diluted"] > 0:
        out["eps_diluted"] = out["net_income"] / out["shares_diluted"]

    out["long_term_debt"] = _value_for_fy(
        companyfacts,
        ["LongTermDebtNoncurrent", "LongTermDebt"],
        fy,
    )
    out["debt_current"] = _value_for_fy(companyfacts, ["DebtCurrent", "ShortTermBorrowings"], fy)
    out["cash"] = _value_for_fy(
        companyfacts,
        ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsAndRestrictedCash"],
        fy,
    )

    div_raw = _value_for_fy(
        companyfacts,
        [
            "PaymentsOfDividends",
            "DividendsPaid",
            "DividendPaid",
        ],
        fy,
    )
    if div_raw is not None:
        out["dividends_paid"] = abs(float(div_raw))

    bb_raw = _value_for_fy(
        companyfacts,
        [
            "PaymentsForRepurchaseOfCommonStock",
            "PaymentsForRepurchaseOfEquity",
            "PaymentsForRepurchaseOfCommonAndPreferredStock",
        ],
        fy,
    )
    if bb_raw is not None:
        out["buybacks"] = abs(float(bb_raw))

    int_raw = _value_for_fy(
        companyfacts,
        ["InterestExpense", "InterestExpenseDebt", "InterestAndDebtExpense"],
        fy,
    )
    if int_raw is not None:
        out["interest_expense"] = abs(float(int_raw))

    tax_raw = _value_for_fy(
        companyfacts,
        [
            "IncomeTaxExpenseBenefit",
            "IncomeTaxExpenseContinuingOperations",
            "IncomeTaxExpense",
        ],
        fy,
    )
    if tax_raw is not None:
        out["income_tax_expense"] = abs(float(tax_raw))

    pre_raw = _value_for_fy(
        companyfacts,
        [
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            "IncomeBeforeIncomeTaxes",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        ],
        fy,
    )
    if pre_raw is not None:
        out["pretax_income"] = float(pre_raw)

    out["ok"] = bool(out["revenue"] and out["fiscal_year"])
    return out


def net_debt_from_inputs(v: dict[str, Any]) -> float:
    debt = (v.get("long_term_debt") or 0) + (v.get("debt_current") or 0)
    cash = v.get("cash") or 0
    return max(0.0, float(debt) - float(cash))


def book_value_per_share(v: dict[str, Any]) -> Optional[float]:
    eq = v.get("stockholders_equity")
    sh = v.get("shares_diluted")
    if eq is None or not sh or float(sh) <= 0:
        return None
    return float(eq) / float(sh)
