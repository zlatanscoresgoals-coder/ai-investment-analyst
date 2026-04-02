"""
Strict SEC Company Facts (us-gaap) reads: 10-K + fp=FY only, latest filed per fiscal year.

Used by valuation_data and optionally other ingest paths. No fallbacks outside XBRL rules here.
"""

from __future__ import annotations

from typing import Any, Optional

# --- Concept waterfalls (priority order) ---

REVENUE_TAGS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
    "RevenuesNetOfInterestExpense",
    "InterestAndDividendIncomeOperating",
)

NET_INCOME_TAGS = (
    "NetIncomeLoss",
    "NetIncomeLossAvailableToCommonStockholdersBasic",
    "ProfitLoss",
)

CFO_TAGS = ("NetCashProvidedByUsedInOperatingActivities",)

CAPEX_TAGS = (
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsForCapitalImprovements",
    "CapitalExpendituresIncurredButNotYetPaid",
)

DIVIDEND_TAGS = (
    "PaymentsOfDividends",
    "PaymentsOfDividendsCommonStock",
    "PaymentsOfDividendsAndDividendEquivalentsOnCommonStockAndRestrictedStockUnits",
)

BUYBACK_TAGS = (
    "PaymentsForRepurchaseOfCommonStock",
    "PaymentsForRepurchaseOfEquity",
    "TreasuryStockValueAcquiredCostMethod",
)

TOTAL_ASSETS_TAGS = ("Assets",)

LONG_TERM_DEBT_TAGS = (
    "LongTermDebt",
    "LongTermDebtNoncurrent",
    "LongTermNotesPayable",
)

SHORT_TERM_DEBT_TAGS = (
    "ShortTermBorrowings",
    "CommercialPaper",
    "LineOfCredit",
)

CURRENT_PORTION_LTD_TAGS = ("CurrentPortionOfLongTermDebt",)

EPS_BASIC_TAGS = (
    "EarningsPerShareBasic",
    "IncomeLossFromContinuingOperationsPerBasicShare",
)

INTEREST_EXPENSE_TAGS = (
    "InterestExpense",
    "InterestExpenseDebt",
    "InterestAndDebtExpense",
)

TAX_PROVISION_TAGS = ("IncomeTaxExpenseBenefit",)

INCOME_BEFORE_TAX_TAGS = (
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
)

EQUITY_TAGS = (
    "StockholdersEquity",
    "StockholdersEquityAttributableToParent",
    "PartnersCapital",
)

RETAINED_EARNINGS_TAGS = ("RetainedEarningsAccumulatedDeficit",)

DEPRECIATION_TAGS = (
    "DepreciationDepletionAndAmortization",
    "DepreciationAndAmortization",
    "Depreciation",
)

EBITDA_DIRECT_TAGS = (
    "EarningsBeforeInterestTaxesDepreciationAmortization",
    "EarningsBeforeInterestTaxesDepreciationAndAmortization",
)

CASH_TAGS = (
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsAndRestrictedCash",
)

OPERATING_INCOME_TAGS = ("OperatingIncomeLoss",)


def _annual_winners_for_entries(entries: list[Any]) -> dict[int, dict[str, Any]]:
    """One entry per fy: the one with the latest *filed* date (amendments / restatements)."""
    by_fy: dict[int, dict[str, Any]] = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        if e.get("form") != "10-K":
            continue
        if e.get("fp") != "FY":
            continue
        fy = e.get("fy")
        if fy is None:
            continue
        try:
            fy_i = int(fy)
        except (TypeError, ValueError):
            continue
        filed = str(e.get("filed") or "")
        prev = by_fy.get(fy_i)
        if prev is None or filed > str(prev.get("filed") or ""):
            by_fy[fy_i] = e
    return by_fy


def _read_numeric_for_fy(
    us_gaap: dict[str, Any],
    tag: str,
    fy: int,
    unit_order: tuple[str, ...],
) -> Optional[float]:
    obj = us_gaap.get(tag)
    if not isinstance(obj, dict):
        return None
    for uk in unit_order:
        raw = obj.get("units", {}).get(uk)
        if not raw:
            continue
        winners = _annual_winners_for_entries(raw if isinstance(raw, list) else [])
        row = winners.get(fy)
        if row is None:
            continue
        val = row.get("val")
        if isinstance(val, (int, float)):
            return float(val)
    return None


MONEY_UNITS = ("USD", "usd")

EPS_UNITS = ("USD/shares", "usd/shares", "USD", "usd")


def waterfall_money(us_gaap: dict[str, Any], tags: tuple[str, ...], fy: int) -> Optional[float]:
    for t in tags:
        v = _read_numeric_for_fy(us_gaap, t, fy, MONEY_UNITS)
        if v is not None:
            return v
    return None


def waterfall_eps_basic(us_gaap: dict[str, Any], tags: tuple[str, ...], fy: int) -> Optional[float]:
    for t in tags:
        v = _read_numeric_for_fy(us_gaap, t, fy, EPS_UNITS)
        if v is not None:
            return v
    return None


def _read_shares_for_fy(us_gaap: dict[str, Any], tag: str, fy: int) -> Optional[float]:
    obj = us_gaap.get(tag)
    if not isinstance(obj, dict):
        return None
    units = obj.get("units") or {}
    # Prefer "shares", then other non-USD numeric units (exclude pure ratio units if any)
    keys = sorted(units.keys(), key=lambda u: (0 if str(u).lower() == "shares" else 1, str(u)))
    for uk in keys:
        if str(uk).upper() in ("USD", "USD/shares", "EUR", "GBP"):
            continue
        raw = units.get(uk)
        if not raw or not isinstance(raw, list):
            continue
        winners = _annual_winners_for_entries(raw)
        row = winners.get(fy)
        if row is None:
            continue
        val = row.get("val")
        if isinstance(val, (int, float)):
            return float(val)
    return None


def shares_outstanding_for_fy(us_gaap: dict[str, Any], fy: int) -> Optional[float]:
    v = _read_shares_for_fy(us_gaap, "CommonStockSharesOutstanding", fy)
    if v is not None:
        return v
    issued = _read_shares_for_fy(us_gaap, "CommonStockSharesIssued", fy)
    if issued is None:
        return None
    treasury = _read_shares_for_fy(us_gaap, "TreasuryStockShares", fy)
    if treasury is None:
        treasury = _read_shares_for_fy(us_gaap, "TreasuryStockCommonShares", fy)
    if treasury is not None:
        return max(0.0, float(issued) - abs(float(treasury)))
    return float(issued)


def collect_fiscal_years_from_revenue(us_gaap: dict[str, Any]) -> tuple[Optional[str], list[int]]:
    """
    First revenue tag in waterfall that has any 10-K FY USD facts; return that tag and
    all fiscal years present (deduped), sorted descending.
    """
    for tag in REVENUE_TAGS:
        obj = us_gaap.get(tag)
        if not isinstance(obj, dict):
            continue
        years: set[int] = set()
        for uk in ("USD", "usd"):
            raw = obj.get("units", {}).get(uk)
            if not raw or not isinstance(raw, list):
                continue
            winners = _annual_winners_for_entries(raw)
            years.update(winners.keys())
        if years:
            return tag, sorted(years, reverse=True)
    return None, []


def revenue_for_fy(us_gaap: dict[str, Any], fy: int, tag: str) -> Optional[float]:
    return _read_money_for_fy(us_gaap, tag, fy)


def effective_tax_rate_pct(tax: Optional[float], pretax: Optional[float]) -> Optional[float]:
    """tax / pretax * 100, capped [0, 50]. None if not computable from 10-K lines."""
    if tax is None or pretax is None:
        return None
    pt = float(pretax)
    if abs(pt) < 1e-9:
        return None
    raw = (float(tax) / pt) * 100.0
    return max(0.0, min(50.0, raw))


def total_debt_for_fy(us_gaap: dict[str, Any], fy: int) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """
    Returns (long_term, short_term, current_portion, total_sum).
    total_sum is None unless at least one component is non-null; missing components treated as 0 in the sum.
    """
    lt = waterfall_money(us_gaap, LONG_TERM_DEBT_TAGS, fy)
    st = waterfall_money(us_gaap, SHORT_TERM_DEBT_TAGS, fy)
    cur = waterfall_money(us_gaap, CURRENT_PORTION_LTD_TAGS, fy)
    parts = [x for x in (lt, st, cur) if x is not None]
    if not parts:
        return lt, st, cur, None
    total = (lt or 0.0) + (st or 0.0) + (cur or 0.0)
    return lt, st, cur, float(total)
