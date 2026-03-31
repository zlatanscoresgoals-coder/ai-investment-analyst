import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
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

# Bankruptcy-style headlines and SEC 8-K signals only block if the event is within this window.
BANKRUPTCY_GATE_MAX_AGE_DAYS = 730

# Event types that require a parsed event time and must fall within BANKRUPTCY_GATE_MAX_AGE_DAYS.
_RECENCY_GATED_EVENT_TYPES = frozenset({"bankruptcy", "sec_8k_critical", "sec_8k_recent"})


def _parse_iso_utc(value: Optional[str]) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        text = value.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _parse_rss_pub_date(value: Optional[str]) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = parsedate_to_datetime(value.strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _occurred_at_is_recent(occurred_at: Optional[datetime]) -> bool:
    if occurred_at is None:
        return False
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)
    occurred_at = occurred_at.astimezone(timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(days=BANKRUPTCY_GATE_MAX_AGE_DAYS)
    return occurred_at >= cutoff


def _filter_findings_by_bankruptcy_recency(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop stale bankruptcy headlines and old SEC 8-K triggers (e.g. historical Chapter 11)."""
    out: list[dict[str, Any]] = []
    for f in findings:
        et = f.get("event_type")
        if et in _RECENCY_GATED_EVENT_TYPES:
            if _occurred_at_is_recent(f.get("occurred_at")):
                out.append(f)
        else:
            out.append(f)
    return out


def _newsapi_headlines(query: str) -> list[dict[str, Any]]:
    api_key = os.getenv("NEWSAPI_KEY")
    if not api_key:
        return []
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": query,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": 20,
        "from": (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d"),
        "apiKey": api_key,
    }
    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    rows: list[dict[str, Any]] = []
    for a in data.get("articles", []):
        title = a.get("title")
        if not title:
            continue
        rows.append(
            {
                "headline": title,
                "url": a.get("url", ""),
                "source": "newsapi",
                "published_at": _parse_iso_utc(a.get("publishedAt")),
            }
        )
    return rows


def _google_news_rss_headlines(query: str) -> list[dict[str, Any]]:
    rss_url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=en-US&gl=US&ceid=US:en"
    resp = requests.get(rss_url, timeout=20)
    resp.raise_for_status()
    root = ElementTree.fromstring(resp.content)
    items = root.findall(".//item")
    output: list[dict[str, Any]] = []
    for item in items[:20]:
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        pub = item.findtext("pubDate")
        if title:
            output.append(
                {
                    "headline": title,
                    "url": link,
                    "source": "google_news_rss",
                    "published_at": _parse_rss_pub_date(pub),
                }
            )
    return output


def fetch_recent_headlines(company: Company) -> list[dict[str, Any]]:
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


def detect_critical_events(headlines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for row in headlines:
        text = row.get("headline", "").lower()
        published_at = row.get("published_at")
        for event_type, pattern in CRITICAL_PATTERNS:
            if re.search(pattern, text):
                findings.append(
                    {
                        "event_type": event_type,
                        "headline": row.get("headline", ""),
                        "url": row.get("url", ""),
                        "source": row.get("source", "news"),
                        "matched_pattern": pattern,
                        "occurred_at": published_at if isinstance(published_at, datetime) else None,
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
        fd = filing_dates[i] if i < len(filing_dates) else None
        occurred_at: Optional[datetime] = None
        if fd:
            try:
                occurred_at = datetime.strptime(fd, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                occurred_at = None
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
                    "occurred_at": occurred_at,
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
                    "occurred_at": occurred_at,
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


def _is_automatic_critical_block(rec: Recommendation) -> bool:
    if rec.status != "blocked":
        return False
    if "critical risk gate" in (rec.summary or "").lower():
        return True
    risk = rec.risk_json or {}
    return bool(risk.get("critical_event"))


def _has_manually_confirmed_critical_alert(db: Session, company_id: int) -> bool:
    for row in db.query(CriticalAlert).filter(CriticalAlert.company_id == company_id).all():
        if (row.details_json or {}).get("workflow_status") == "confirmed":
            return True
    return False


def _try_clear_automatic_block(db: Session, company: Company) -> bool:
    """
    If the latest recommendation was blocked by the automatic gate but the current scan
    would not block, restore status from the stored score (recommended vs watchlist).
    """
    if _has_manually_confirmed_critical_alert(db, company.id):
        return False
    latest_rec = (
        db.query(Recommendation)
        .filter(Recommendation.company_id == company.id)
        .order_by(Recommendation.as_of.desc())
        .first()
    )
    if not latest_rec or not _is_automatic_critical_block(latest_rec):
        return False
    if latest_rec.final_score >= settings.recommendation_threshold:
        latest_rec.status = "recommended"
    else:
        latest_rec.status = "watchlist"
    latest_rec.summary = "Critical risk gate cleared on latest scan (no actionable signals)."
    risk = dict(latest_rec.risk_json or {})
    if "critical_event" in risk:
        risk.pop("critical_event", None)
    risk["critical_gate_cleared_at"] = datetime.now(timezone.utc).isoformat()
    latest_rec.risk_json = risk

    for alert in db.query(CriticalAlert).filter(CriticalAlert.company_id == company.id).all():
        details = dict(alert.details_json or {})
        ws = details.get("workflow_status", "blocked")
        if ws == "blocked":
            details["workflow_status"] = "unblocked"
            details["workflow_updated_at"] = datetime.now(timezone.utc).isoformat()
            details["auto_cleared_reason"] = "gate_rescan_no_actionable_signals"
            alert.details_json = details
    return True


def apply_critical_risk_gate(db: Session, company: Company) -> Optional[CriticalAlert]:
    headlines = fetch_recent_headlines(company)
    findings = detect_critical_events(headlines) + _sec_recent_8k_findings(company)
    findings = _filter_findings_by_bankruptcy_recency(findings)

    confidence, source_count = _evaluate_confidence(findings) if findings else ("low", 0)
    min_required = settings.risk_block_min_confidence
    would_block = bool(findings) and _confidence_rank(confidence) >= _confidence_rank(min_required)

    if not would_block:
        if _try_clear_automatic_block(db, company):
            db.commit()
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
    details["workflow_updated_at"] = datetime.now(timezone.utc).isoformat()
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
