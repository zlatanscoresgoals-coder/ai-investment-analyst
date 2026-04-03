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
    "NetRevenues",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
    "RevenuesNetOfInterestExpense",
    "InterestAndDividendIncomeOperating",
)

NET_INCOME_TAGS = (
    "NetIncomeLoss",
    "ProfitLoss",
    "NetIncomeLossAvailableToCommonStockholdersBasic",
    "IncomeLossFromContinuingOperations",
)

CFO_TAGS = ("NetCashProvidedByUsedInOperatingActivities",)

CAPEX_TAGS = (
    # Cash paid for PP&E — primary sources (cash flow statement)
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",        # NVDA, AMZN use this
    "PaymentsForCapitalImprovements",
    "PurchasesOfPropertyAndEquipment",
    # Accrued-but-not-yet-paid — last resort only; significantly understates true capex
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
    "LongTermDebtAndCapitalLeaseObligations",
    "LongTermNotesPayable",
)

SHORT_TERM_DEBT_TAGS = (
    "ShortTermBorrowings",
    "ShortTermDebt",
    "NotesPayableCurrent",
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
    "InterestExpenseNonoperating",   # NVDA, Visa, MSFT report here
    "InterestCostsIncurred",
)

TAX_PROVISION_TAGS = ("IncomeTaxExpenseBenefit",)

INCOME_BEFORE_TAX_TAGS = (
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
)

EQUITY_TAGS = (
    "StockholdersEquity",
    "StockholdersEquityAttributableToParent",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",  # Visa, UNH
    "PartnersCapital",
)

RETAINED_EARNINGS_TAGS = ("RetainedEarningsAccumulatedDeficit",)

DEPRECIATION_TAGS = (
    "DepreciationDepletionAndAmortization",
    "DepreciationAndAmortization",
    "Depreciation",
    "DepreciationAmortizationAndAccretionNet",  # JPM, MA use this
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
    """
    One entry per fiscal period, keyed by year(end-date).

    SEC EDGAR re-files prior-year comparative figures in every subsequent 10-K,
    all tagged with the *filing* year in the `fy` field.  For example Apple's
    FY2025 10-K contains three rows for RevenueFromContract…, all with fy=2025
    but with end-dates 2023-09-30, 2024-09-28, and 2025-09-27.  Keying by `fy`
    therefore collapses three distinct periods into one and picks the wrong value.

    Fix: key by year(end), require form=10-K + fp=FY, require period ≥ 340 days
    (full-year), and among duplicates keep the one with the latest filed date
    (picks up 10-K/A amendments).
    """
    by_end_year: dict[int, dict[str, Any]] = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        if e.get("form") not in ("10-K", "10-K/A"):
            continue
        if e.get("fp") != "FY":
            continue
        end_str = e.get("end") or ""
        start_str = e.get("start") or ""
        if not end_str:
            continue
        try:
            end_year = int(end_str[:4])
        except (ValueError, TypeError):
            continue
        # Require full-year period (≥ 340 days) to exclude stub / transition periods.
        if start_str and end_str:
            try:
                from datetime import date as _date
                s = _date.fromisoformat(start_str)
                en = _date.fromisoformat(end_str)
                if (en - s).days < 340:
                    continue
            except (ValueError, TypeError):
                pass
        filed = str(e.get("filed") or "")
        prev = by_end_year.get(end_year)
        if prev is None or filed > str(prev.get("filed") or ""):
            by_end_year[end_year] = e
    return by_end_year


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
    Pick the revenue tag whose most-recent 10-K FY data is the latest calendar year.
    This handles companies that switched GAAP tags over time (e.g. Mastercard moved from
    RevenueFromContractWithCustomer… to Revenues after 2021). Without this, the first
    matching tag wins even if it only has stale data from years ago.
    """
    best_tag: Optional[str] = None
    best_max_year: int = 0
    best_years: list[int] = []

    for tag in REVENUE_TAGS:
        obj = us_gaap.get(tag)
        if not isinstance(obj, dict):
            continue
        years: set[int] = set()
        for uk in ("USD", "usd"):
            raw = obj.get("units", {}).get(uk)
            if not raw or not isinstance(raw, list):
                continue
            w = _annual_winners_for_entries(raw)
            years.update(w.keys())
        if not years:
            continue
        max_year = max(years)
        if max_year > best_max_year:
            best_max_year = max_year
            best_tag = tag
            best_years = sorted(years, reverse=True)

    if best_tag:
        return best_tag, best_years
    return None, []


def revenue_for_fy(us_gaap: dict[str, Any], fy: int, tag: str) -> Optional[float]:
    return waterfall_money(us_gaap, (tag,), fy)


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
