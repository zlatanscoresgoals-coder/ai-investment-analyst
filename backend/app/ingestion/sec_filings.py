import os
import re
from datetime import datetime
from typing import Any, Optional
from urllib.parse import quote

import requests
from sqlalchemy.orm import Session

from app.models import Company

SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"


def sec_edgar_company_search_url(ticker: str) -> str:
    """Human-readable SEC EDGAR company search (filings, including 10-K)."""
    t = (ticker or "").strip().upper()
    return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&owner=exclude&count=100&ticker={quote(t)}"


def _sec_headers() -> dict[str, str]:
    # SEC expects a descriptive User-Agent. Do not set Host — requests sets it from the URL;
    # a wrong Host (e.g. data.sec.gov for www.sec.gov) breaks CIK lookup and submissions.
    ua = os.getenv("SEC_USER_AGENT", "AIInvestmentAnalyst/0.1 contact@example.com")
    return {"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}


def _get_json(url: str) -> dict[str, Any]:
    response = requests.get(url, headers=_sec_headers(), timeout=30)
    response.raise_for_status()
    return response.json()


def _get_text(url: str) -> str:
    response = requests.get(url, headers={"User-Agent": _sec_headers()["User-Agent"]}, timeout=30)
    response.raise_for_status()
    return response.text


def get_cik_for_ticker(ticker: str) -> Optional[str]:
    try:
        data = _get_json(SEC_TICKER_URL)
    except Exception:
        return None
    target = ticker.upper().strip()
    for item in data.values():
        if item.get("ticker", "").upper() == target:
            return str(item["cik_str"]).zfill(10)
    return None


def get_submission_json_for_ticker(ticker: str) -> Optional[dict[str, Any]]:
    """Single SEC submissions.json fetch for a ticker (used for 10-K list + company profile)."""
    cik = get_cik_for_ticker(ticker)
    if not cik:
        return None
    try:
        return _get_json(SEC_SUBMISSIONS_URL.format(cik=cik))
    except Exception:
        return None


def _coarse_sector_from_sic(sic_raw: Any) -> Optional[str]:
    """Broad bucket when SEC submissions omit ownerOrg (SIC division from first two digits)."""
    if sic_raw is None:
        return None
    digits = "".join(c for c in str(sic_raw).strip() if c.isdigit())
    if len(digits) < 2:
        return None
    try:
        n = int(digits[:2])
    except ValueError:
        return None
    if n <= 9:
        return "Agriculture, Forestry & Fishing"
    if n <= 14:
        return "Mining"
    if n <= 17:
        return "Construction"
    if n <= 39:
        return "Manufacturing"
    if n <= 49:
        return "Transportation, Communications & Utilities"
    if n <= 51:
        return "Wholesale Trade"
    if n <= 59:
        return "Retail Trade"
    if n <= 67:
        return "Finance, Insurance & Real Estate"
    if n <= 89:
        return "Services"
    return "Public Administration"


def metadata_from_submission(submission: dict[str, Any]) -> dict[str, Optional[str]]:
    """Legal name, broad sector bucket (SEC ownerOrg or SIC-derived), and SIC industry line."""
    name = (submission.get("name") or "").strip() or None
    industry = (submission.get("sicDescription") or "").strip() or None
    owner = (submission.get("ownerOrg") or "").strip()
    sector: Optional[str] = None
    if owner:
        sector = re.sub(r"^\s*\d+\s*", "", owner).strip() or None
    if not sector:
        sector = _coarse_sector_from_sic(submission.get("sic"))
    return {"name": name, "sector": sector, "industry": industry}


def merge_sec_company_profile(company: Company, submission: dict[str, Any]) -> bool:
    """Update company row from SEC submission metadata. Returns True if any column changed."""
    meta = metadata_from_submission(submission)
    changed = False
    if meta.get("name") and company.name.strip().upper() == company.ticker.strip().upper():
        company.name = meta["name"][:255]
        changed = True
    if meta.get("sector"):
        ns = meta["sector"][:128]
        if company.sector != ns:
            company.sector = ns
            changed = True
    if meta.get("industry"):
        ni = meta["industry"][:128]
        if company.industry != ni:
            company.industry = ni
            changed = True
    return changed


def apply_sec_metadata_to_company(db: Session, company: Company) -> None:
    """Refresh sector/industry/name (when placeholder) from SEC; no-op if submissions unavailable."""
    sub = get_submission_json_for_ticker(company.ticker.upper())
    if not sub:
        return
    if merge_sec_company_profile(company, sub):
        db.add(company)
        db.commit()


def build_10k_list_from_submission(submission: dict[str, Any]) -> list[dict]:
    cik = str(submission.get("cik", "0")).zfill(10)
    try:
        cik_no_zero = str(int(cik))
    except ValueError:
        return []

    recent = submission.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    filing_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    output: list[dict] = []
    for i, form in enumerate(forms):
        if form != "10-K":
            continue

        report_date = report_dates[i] or filing_dates[i]
        fiscal_year = datetime.strptime(report_date, "%Y-%m-%d").year
        accession_raw = accessions[i]
        accession_no_dash = accession_raw.replace("-", "")
        filing_url = f"{SEC_ARCHIVES_BASE}/{cik_no_zero}/{accession_no_dash}/{primary_docs[i]}"

        filing_text = ""
        try:
            filing_text = _get_text(filing_url)[:250_000]
        except Exception:
            filing_text = ""

        output.append(
            {
                "filing_type": "10-K",
                "fiscal_year": fiscal_year,
                "filing_date": datetime.strptime(filing_dates[i], "%Y-%m-%d").date(),
                "url": filing_url,
                "source": "sec",
                "raw_text": filing_text,
            }
        )
        if len(output) >= 3:
            break

    return output


def fetch_last_3y_10k_urls(ticker: str) -> list[dict]:
    sub = get_submission_json_for_ticker(ticker)
    if not sub:
        return []
    return build_10k_list_from_submission(sub)


def fetch_financial_metrics_last_3y(ticker: str) -> list[dict[str, Any]]:
    """
    Pull last 3 fiscal years of annual metrics from SEC Company Facts (strict 10-K / FY).
    Uses the same waterfall helpers as valuation_data so all figures align to the same FY.
    """
    from app.ingestion.sec_xbrl import (
        CAPEX_TAGS,
        CFO_TAGS,
        EQUITY_TAGS,
        NET_INCOME_TAGS,
        OPERATING_INCOME_TAGS,
        REVENUE_TAGS,
        collect_fiscal_years_from_revenue,
        waterfall_money,
    )

    cik = get_cik_for_ticker(ticker)
    if not cik:
        return []

    try:
        companyfacts = _get_json(SEC_COMPANYFACTS_URL.format(cik=cik))
    except Exception:
        return []

    us_gaap = companyfacts.get("facts", {}).get("us-gaap", {})
    if not isinstance(us_gaap, dict):
        return []

    _GROSS_PROFIT_TAGS = ("GrossProfit",)
    _CURRENT_ASSETS_TAGS = ("AssetsCurrent",)
    _CURRENT_LIAB_TAGS = ("LiabilitiesCurrent",)
    _EBITDA_TAGS = ("EarningsBeforeInterestTaxesDepreciationAmortization", "EarningsBeforeInterestTaxesDepreciationAndAmortization")
    _INTEREST_TAGS = ("InterestExpense", "InterestExpenseDebt", "InterestAndDebtExpense")
    _EBIT_TAGS = ("OperatingIncomeLoss",)

    rev_tag, all_fy = collect_fiscal_years_from_revenue(us_gaap)
    if not rev_tag or not all_fy:
        return []

    years = sorted(all_fy, reverse=True)[:3]
    output: list[dict[str, Any]] = []

    for year in years:
        rev = waterfall_money(us_gaap, (rev_tag,), year)
        gp = waterfall_money(us_gaap, _GROSS_PROFIT_TAGS, year)
        op_inc = waterfall_money(us_gaap, OPERATING_INCOME_TAGS, year)
        ni = waterfall_money(us_gaap, NET_INCOME_TAGS, year)
        cfo_val = waterfall_money(us_gaap, CFO_TAGS, year)
        capex_raw = waterfall_money(us_gaap, CAPEX_TAGS, year)
        eq = waterfall_money(us_gaap, EQUITY_TAGS, year)
        ca = waterfall_money(us_gaap, _CURRENT_ASSETS_TAGS, year)
        cl = waterfall_money(us_gaap, _CURRENT_LIAB_TAGS, year)
        ebitda = waterfall_money(us_gaap, _EBITDA_TAGS, year)
        int_exp = waterfall_money(us_gaap, _INTEREST_TAGS, year)

        def _safe_pct(num, denom):
            try:
                if num is not None and denom and float(denom) != 0:
                    return float(num) / float(denom) * 100.0
            except (TypeError, ZeroDivisionError):
                pass
            return None

        gross_margin = _safe_pct(gp, rev)
        operating_margin = _safe_pct(op_inc, rev)
        net_margin = _safe_pct(ni, rev)
        fcf = None
        if cfo_val is not None and capex_raw is not None:
            fcf = float(cfo_val) - abs(float(capex_raw))
        roe = _safe_pct(ni, eq)
        current_ratio = None
        if ca is not None and cl is not None and float(cl) != 0:
            current_ratio = float(ca) / float(cl)

        # debt/EBITDA: use EBITDA if available, else approximate from op_inc
        ebitda_eff = ebitda
        if ebitda_eff is None and op_inc is not None:
            dep_approx = 0.0
            ebitda_eff = float(op_inc) + dep_approx

        debt_to_ebitda = None
        interest_coverage = None
        if ebitda_eff and float(ebitda_eff) != 0:
            if int_exp is not None and float(int_exp) != 0:
                interest_coverage = float(ebitda_eff) / abs(float(int_exp))

        output.append(
            {
                "fiscal_year": year,
                "revenue": rev,
                "gross_margin": gross_margin,
                "operating_margin": operating_margin,
                "net_margin": net_margin,
                "fcf": fcf,
                "roic": roe,
                "roe": roe,
                "debt_to_ebitda": debt_to_ebitda,
                "interest_coverage": interest_coverage,
                "current_ratio": current_ratio,
                "shares_outstanding": None,
                "valuation_pe": None,
                "valuation_ev_ebitda": None,
            }
        )

    return output


def fallback_financial_metrics_last_3y(ticker: str) -> list[dict[str, Any]]:
    # Demo fallback used only when SEC endpoints are unreachable.
    # Values are synthetic placeholders to keep the product usable.
    starter = {
        "AAPL": [383.3, 394.3, 365.8],
        "MSFT": [245.1, 211.9, 198.3],
        "GOOGL": [307.4, 282.8, 257.6],
        "AMZN": [574.8, 513.9, 469.8],
        "NVDA": [60.9, 26.9, 27.0],
        "TSLA": [96.8, 81.5, 53.8],
        "XOM": [344.6, 413.7, 285.6],
        "CVX": [200.9, 246.3, 162.5],
        "JPM": [158.1, 132.3, 121.6],
        "BRK-B": [364.5, 302.1, 276.1],
    }
    revs = starter.get(ticker.upper())
    if not revs:
        return []

    current_year = datetime.utcnow().year - 1
    out: list[dict[str, Any]] = []
    for i, rev_bn in enumerate(revs):
        out.append(
            {
                "fiscal_year": current_year - i,
                "revenue": rev_bn * 1_000_000_000.0,
                "gross_margin": 42.0 - i,
                "operating_margin": 25.0 - (i * 0.8),
                "net_margin": 21.0 - (i * 0.7),
                "fcf": rev_bn * 0.18 * 1_000_000_000.0,
                "roic": 18.0 - (i * 0.4),
                "roe": 20.0 - (i * 0.5),
                "debt_to_ebitda": 1.4 + (i * 0.1),
                "interest_coverage": 9.0 - (i * 0.2),
                "current_ratio": 1.6 - (i * 0.05),
                "shares_outstanding": None,
                "valuation_pe": 24.0,
                "valuation_ev_ebitda": 14.0,
            }
        )
    return out
