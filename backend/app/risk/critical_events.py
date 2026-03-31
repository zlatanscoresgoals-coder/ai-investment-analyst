import os
import re
from datetime import datetime, timedelta
from typing import Any, Optional
from xml.etree import ElementTree

import requests
from sqlalchemy.orm import Session

from app.config import settings
from app.ingestion.sec_filings import get_cik_for_ticker
from app.models import Company, CriticalAlert, Recommendation


CRITICAL_PATTERNS: list[tuple[str, str]] = [
    ("bankruptcy", r"\bbankrupt(cy)?\b|\bchapter\s*11\b|\bchapter\s*7\b"),
    ("going_concern", r"\bgoing concern\b|\binsolvenc(y|e)\b"),
    ("default", r"\bdefault(ed|s)?\b|\bdebt default\b|\bcovenant breach\b"),
    ("delisting", r"\bdelist(ed|ing)?\b|\btrading halt\b"),
]


def _newsapi_headlines(query: str) -> list[dict[str, str]]:
    api_key = os.getenv("NEWSAPI_KEY")
    if not api_key:
        return []
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": query,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": 20,
        "from": (datetime.utcnow() - timedelta(days=2)).strftime("%Y-%m-%d"),
        "apiKey": api_key,
    }
    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    return [
        {"headline": a.get("title", ""), "url": a.get("url", ""), "source": "newsapi"}
        for a in data.get("articles", [])
        if a.get("title")
    ]


def _google_news_rss_headlines(query: str) -> list[dict[str, str]]:
    rss_url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=en-US&gl=US&ceid=US:en"
    resp = requests.get(rss_url, timeout=20)
    resp.raise_for_status()
    root = ElementTree.fromstring(resp.content)
    items = root.findall(".//item")
    output: list[dict[str, str]] = []
    for item in items[:20]:
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        if title:
            output.append({"headline": title, "url": link, "source": "google_news_rss"})
    return output


def fetch_recent_headlines(company: Company) -> list[dict[str, str]]:
    query = f"{company.ticker} {company.name}"
    try:
        rows = _newsapi_headlines(query)
        if rows:
            return rows
    except Exception:
        pass
    try:
        return _google_news_rss_headlines(query)
    except Exception:
        return []


def detect_critical_events(headlines: list[dict[str, str]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for row in headlines:
        text = row.get("headline", "").lower()
        for event_type, pattern in CRITICAL_PATTERNS:
            if re.search(pattern, text):
                findings.append(
                    {
                        "event_type": event_type,
                        "headline": row.get("headline", ""),
                        "url": row.get("url", ""),
                        "source": row.get("source", "news"),
                        "matched_pattern": pattern,
                    }
                )
    return findings


def _sec_recent_8k_findings(company: Company) -> list[dict[str, Any]]:
    cik = get_cik_for_ticker(company.ticker)
    if not cik:
        return []
    try:
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        ua = os.getenv("SEC_USER_AGENT", "AIInvestmentAnalyst/0.1 contact@example.com")
        resp = requests.get(url, headers={"User-Agent": ua}, timeout=20)
        resp.raise_for_status()
        sub = resp.json()
    except Exception:
        return []

    recent = sub.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    filing_dates = recent.get("filingDate", [])
    primary_docs = recent.get("primaryDocument", [])
    accessions = recent.get("accessionNumber", [])
    findings: list[dict[str, Any]] = []
    for i, form in enumerate(forms[:40]):
        if form != "8-K":
            continue
        doc = (primary_docs[i] or "").lower()
        # SEC 8-K is a stronger signal; treat filing presence + keyword file names as event hints.
        if any(k in doc for k in ["bankrupt", "chapter", "default", "goingconcern", "delist", "halt"]):
            findings.append(
                {
                    "event_type": "sec_8k_critical",
                    "headline": f"SEC 8-K trigger for {company.ticker} on {filing_dates[i]} ({primary_docs[i]})",
                    "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accessions[i].replace('-', '')}/{primary_docs[i]}",
                    "source": "sec_8k",
                    "matched_pattern": "8k_filename_keyword",
                }
            )
        elif i < 5:
            # recent generic 8-Ks still matter but lower confidence
            findings.append(
                {
                    "event_type": "sec_8k_recent",
                    "headline": f"Recent SEC 8-K for {company.ticker} on {filing_dates[i]}",
                    "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accessions[i].replace('-', '')}/{primary_docs[i]}",
                    "source": "sec_8k",
                    "matched_pattern": "8k_recent",
                }
            )
    return findings


def _evaluate_confidence(findings: list[dict[str, Any]]) -> tuple[str, int]:
    if not findings:
        return "low", 0
    sources = {f.get("source", "unknown") for f in findings}
    source_count = len(sources)
    has_sec_8k_critical = any(f.get("event_type") == "sec_8k_critical" for f in findings)
    has_bankruptcy = any(f.get("event_type") == "bankruptcy" for f in findings)
    if has_sec_8k_critical or (has_bankruptcy and source_count >= 2):
        return "high", source_count
    if source_count >= 2 or has_bankruptcy:
        return "medium", source_count
    return "low", source_count


def _confidence_rank(level: str) -> int:
    return {"low": 1, "medium": 2, "high": 3}.get(level, 1)


def _send_alert_notification(payload: dict[str, Any]):
    print(f"[CRITICAL ALERT] {payload}")
    if not settings.alert_webhook_url:
        return
    try:
        requests.post(settings.alert_webhook_url, json=payload, timeout=10)
    except Exception:
        pass


def apply_critical_risk_gate(db: Session, company: Company) -> Optional[CriticalAlert]:
    headlines = fetch_recent_headlines(company)
    findings = detect_critical_events(headlines) + _sec_recent_8k_findings(company)
    if not findings:
        return None

    confidence, source_count = _evaluate_confidence(findings)
    min_required = settings.risk_block_min_confidence
    if _confidence_rank(confidence) < _confidence_rank(min_required):
        return None

    finding = findings[0]
    recent_exists = (
        db.query(CriticalAlert)
        .filter(
            CriticalAlert.company_id == company.id,
            CriticalAlert.headline == finding["headline"],
        )
        .first()
    )
    if recent_exists:
        return recent_exists

    alert = CriticalAlert(
        company_id=company.id,
        event_type=finding["event_type"],
        severity="critical",
        source=finding["source"],
        headline=finding["headline"],
        url=finding["url"],
        details_json={
            "matched_pattern": finding["matched_pattern"],
            "confidence": confidence,
            "source_count": source_count,
            "workflow_status": "blocked",
            "all_findings": findings[:10],
        },
    )
    db.add(alert)

    latest_rec = (
        db.query(Recommendation)
        .filter(Recommendation.company_id == company.id)
        .order_by(Recommendation.as_of.desc())
        .first()
    )
    if latest_rec:
        latest_rec.status = "blocked"
        latest_rec.summary = (
            f"Blocked by critical risk gate due to {finding['event_type']} signal in recent news headline."
        )
        risk = latest_rec.risk_json or {}
        risk["critical_event"] = finding
        latest_rec.risk_json = risk
    db.commit()
    db.refresh(alert)
    _send_alert_notification(
        {
            "ticker": company.ticker,
            "company_name": company.name,
            "event_type": finding["event_type"],
            "headline": finding["headline"],
            "confidence": confidence,
            "source_count": source_count,
            "workflow_status": "blocked",
        }
    )
    return alert


def update_alert_workflow(db: Session, alert_id: int, action: str) -> Optional[CriticalAlert]:
    alert = db.query(CriticalAlert).filter(CriticalAlert.id == alert_id).first()
    if not alert:
        return None
    details = alert.details_json or {}
    if action not in {"under_review", "confirmed", "unblocked"}:
        return alert
    details["workflow_status"] = action
    details["workflow_updated_at"] = datetime.utcnow().isoformat()
    alert.details_json = details

    latest_rec = (
        db.query(Recommendation)
        .filter(Recommendation.company_id == alert.company_id)
        .order_by(Recommendation.as_of.desc())
        .first()
    )
    if latest_rec and action == "unblocked" and latest_rec.status == "blocked":
        latest_rec.status = "watchlist"
        latest_rec.summary = "Moved to watchlist after manual risk review."
    db.commit()
    db.refresh(alert)
    return alert
