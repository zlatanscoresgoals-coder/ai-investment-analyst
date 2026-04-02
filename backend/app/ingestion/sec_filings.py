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


def metadata_from_submission(submission: dict[str, Any]) -> dict[str, Optional[str]]:
    """Legal name, broad sector bucket (SEC ownerOrg), and SIC industry line."""
    name = (submission.get("name") or "").strip() or None
    industry = (submission.get("sicDescription") or "").strip() or None
    owner = (submission.get("ownerOrg") or "").strip()
    sector: Optional[str] = None
    if owner:
        sector = re.sub(r"^\s*\d+\s*", "", owner).strip() or None
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


def _pick_latest_annual_fact(companyfacts: dict[str, Any], tags: list[str]) -> dict[int, float]:
    us_gaap = companyfacts.get("facts", {}).get("us-gaap", {})
    annual_by_year: dict[int, float] = {}

    for tag in tags:
        tag_obj = us_gaap.get(tag)
        if not tag_obj:
            continue
        for _, entries in tag_obj.get("units", {}).items():
            for entry in entries:
                if entry.get("form") != "10-K":
                    continue
                fy = entry.get("fy")
                val = entry.get("val")
                if fy and isinstance(val, (int, float)):
                    annual_by_year[int(fy)] = float(val)
            if annual_by_year:
                break
        if annual_by_year:
            break
    return annual_by_year


def fetch_financial_metrics_last_3y(ticker: str) -> list[dict[str, Any]]:
    cik = get_cik_for_ticker(ticker)
    if not cik:
        return []

    try:
        companyfacts = _get_json(SEC_COMPANYFACTS_URL.format(cik=cik))
    except Exception:
        return []

    revenue = _pick_latest_annual_fact(
        companyfacts,
        ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
    )
    gross_profit = _pick_latest_annual_fact(companyfacts, ["GrossProfit"])
    operating_income = _pick_latest_annual_fact(companyfacts, ["OperatingIncomeLoss"])
    net_income = _pick_latest_annual_fact(companyfacts, ["NetIncomeLoss"])
    cfo = _pick_latest_annual_fact(companyfacts, ["NetCashProvidedByUsedInOperatingActivities"])
    capex = _pick_latest_annual_fact(companyfacts, ["PaymentsToAcquirePropertyPlantAndEquipment"])
    equity = _pick_latest_annual_fact(companyfacts, ["StockholdersEquity"])
    current_assets = _pick_latest_annual_fact(companyfacts, ["AssetsCurrent"])
    current_liabilities = _pick_latest_annual_fact(companyfacts, ["LiabilitiesCurrent"])

    years = sorted(revenue.keys(), reverse=True)[:3]
    output: list[dict[str, Any]] = []
    for year in years:
        rev = revenue.get(year)
        gp = gross_profit.get(year)
        op_inc = operating_income.get(year)
        ni = net_income.get(year)
        cfo_val = cfo.get(year)
        capex_val = capex.get(year)
        eq = equity.get(year)
        ca = current_assets.get(year)
        cl = current_liabilities.get(year)

        gross_margin = (gp / rev * 100.0) if gp and rev else None
        operating_margin = (op_inc / rev * 100.0) if op_inc and rev else None
        net_margin = (ni / rev * 100.0) if ni and rev else None
        fcf = (cfo_val - abs(capex_val)) if cfo_val is not None and capex_val is not None else None
        roe = (ni / eq * 100.0) if ni and eq else None
        current_ratio = (ca / cl) if ca and cl else None

        output.append(
            {
                "fiscal_year": year,
                "revenue": rev,
                "gross_margin": gross_margin,
                "operating_margin": operating_margin,
                "net_margin": net_margin,
                "fcf": fcf,
                "roic": roe,  # proxy when invested capital is not directly available.
                "roe": roe,
                "debt_to_ebitda": None,
                "interest_coverage": None,
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
