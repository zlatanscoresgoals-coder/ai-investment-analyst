import html
import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional
from urllib.parse import quote as urlquote
from urllib.parse import urlparse
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

# News + SEC critical signals only block if the event is within this window (and news is not a “old story” headline).
BANKRUPTCY_GATE_MAX_AGE_DAYS = 730

_NEWS_FEED_SOURCES = frozenset({"newsapi", "google_news_rss"})
_CRITICAL_NEWS_EVENT_TYPES = frozenset(t for t, _ in CRITICAL_PATTERNS)

# Headlines that describe past / retrospective distress (block false positives when article is new but event was long ago).
_HISTORICAL_RISK_HEADLINE_RE = re.compile(
    r"(?i)"
    r"\b(19\d{2}|18\d{2})\b|"
    r"\bdecades?\s+ago\b|\bhalf\s+a\s+century\b|\byears?\s+ago\b|"
    r"\b(flashback|look\s+back|on\s+this\s+day|this\s+day\s+in\s+history|historical|"
    r"retrospective|remember\s+when|throwback)\b|"
    r"\bin\s+the\s+(19|20)\d{2}s\b|"
    r"\b(once\s+(almost|nearly)|how\s+.+\s+(avoided|survived|escaped)|"
    r"brush\s+with\s+(bankruptcy|insolvency)|near-?death\s+experience)\b|"
    r"\b(when|why)\s+.{0,40}\b(almost|nearly)\s+(went\s+)?bankrupt|"
    # e.g. "Apple Turns 50 — From Near Bankruptcy To $3.6T" (anniversary / journey story, not a new filing)
    r"\bturns?\s+\d{1,4}\b|"
    r"\bfrom\s+near\s+bankruptcy\b|"
    r"\bnear\s+bankruptcy\s+to\b|"
    r"\bfrom\s+bankruptcy\s+to\b"
)


def _outlet_hints_from_row(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("outlet_name", "outlet_domain"):
        v = row.get(key)
        if v and isinstance(v, str) and v.strip():
            parts.append(v.strip())
    title = row.get("headline") or ""
    for sep in (" — ", " – ", " - "):
        if sep in title:
            tail = title.rsplit(sep, 1)[-1].strip()
            if tail and len(tail) < 120:
                parts.append(tail)
            break
    return " ".join(parts).lower()


def _row_passes_outlet_allowlist(row: dict[str, Any]) -> bool:
    if not settings.critical_news_strict_outlets:
        return True
    phrases = [p.strip().lower() for p in settings.critical_news_allowlist.split(",") if p.strip()]
    if not phrases:
        return True
    hay = _outlet_hints_from_row(row)
    if not hay:
        return False
    for p in phrases:
        if len(p) <= 3:
            if re.search(rf"(?<![a-z0-9]){re.escape(p)}(?![a-z0-9])", hay):
                return True
        elif p in hay:
            return True
    return False


def _filter_headlines_trusted_outlets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if _row_passes_outlet_allowlist(r)]


def _domain_from_url(url: Optional[str]) -> str:
    if not url or not isinstance(url, str):
        return ""
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


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


def _finding_needs_recency_gate(f: dict[str, Any]) -> bool:
    et = f.get("event_type")
    src = f.get("source", "")
    if et in _CRITICAL_NEWS_EVENT_TYPES and src in _NEWS_FEED_SOURCES:
        return True
    if et in ("sec_8k_critical", "sec_8k_recent"):
        return True
    return False


def headline_is_historical_risk_story(headline: str) -> bool:
    return bool(_HISTORICAL_RISK_HEADLINE_RE.search(headline or ""))


def _news_headline_is_historical_story(f: dict[str, Any]) -> bool:
    if f.get("source") not in _NEWS_FEED_SOURCES:
        return False
    return headline_is_historical_risk_story(f.get("headline") or "")


def is_actionable_critical_alert(alert: CriticalAlert) -> bool:
    """
    False for news alerts that would NOT fire under current rules (wrong outlet, retrospective headline).
    Used to hide stale DB rows without waiting for a rescan; SEC-sourced alerts stay visible.
    """
    src = (alert.source or "").strip()
    if src not in _NEWS_FEED_SOURCES:
        return True
    row: dict[str, Any] = {
        "headline": alert.headline or "",
        "source": src,
        "outlet_name": "",
    }
    if _news_headline_is_historical_story(row):
        return False
    if not _row_passes_outlet_allowlist(row):
        return False
    return True


def _filter_findings_by_bankruptcy_recency(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop stale headlines, retrospective “50 years ago” stories, and old SEC 8-K triggers."""
    out: list[dict[str, Any]] = []
    for f in findings:
        if not _finding_needs_recency_gate(f):
            out.append(f)
            continue
        if _news_headline_is_historical_story(f):
            continue
        if _occurred_at_is_recent(f.get("occurred_at")):
            out.append(f)
    return out


def _newsapi_headlines(query: str) -> list[dict[str, Any]]:
    api_key = (settings.newsapi_key or "").strip()
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
        src = a.get("source")
        outlet_name = ""
        if isinstance(src, dict):
            outlet_name = (src.get("name") or "").strip()
        rows.append(
            {
                "headline": title,
                "url": a.get("url", ""),
                "source": "newsapi",
                "published_at": _parse_iso_utc(a.get("publishedAt")),
                "outlet_name": outlet_name,
                "outlet_domain": _domain_from_url(a.get("url")),
            }
        )
    return rows


def _google_news_rss_headlines(query: str) -> list[dict[str, Any]]:
    rss_url = f"https://news.google.com/rss/search?q={urlquote(query)}&hl=en-US&gl=US&ceid=US:en"
    resp = requests.get(rss_url, timeout=20)
    resp.raise_for_status()
    root = ElementTree.fromstring(resp.content)
    items = root.findall(".//item")
    output: list[dict[str, Any]] = []
    for item in items[:20]:
        title = html.unescape(item.findtext("title") or "")
        link = item.findtext("link") or ""
        pub = item.findtext("pubDate")
        outlet_name = ""
        src_el = item.find("source")
        if src_el is not None and src_el.text and src_el.text.strip():
            outlet_name = html.unescape(src_el.text.strip())
        if title:
            output.append(
                {
                    "headline": title,
                    "url": link,
                    "source": "google_news_rss",
                    "published_at": _parse_rss_pub_date(pub),
                    "outlet_name": outlet_name,
                    "outlet_domain": _domain_from_url(link),
                }
            )
    return output


def fetch_recent_headlines(company: Company) -> list[dict[str, Any]]:
    query = f"{company.ticker} {company.name}"
    try:
        rows = _filter_headlines_trusted_outlets(_newsapi_headlines(query))
        if rows:
            return rows
    except Exception:
        pass
    try:
        return _filter_headlines_trusted_outlets(_google_news_rss_headlines(query))
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


def _unblock_all_blocked_alerts_for_company(db: Session, company_id: int) -> bool:
    """Mark every workflow=blocked alert for this company as unblocked (unless user confirmed a critical)."""
    changed = False
    for alert in db.query(CriticalAlert).filter(CriticalAlert.company_id == company_id).all():
        details = dict(alert.details_json or {})
        if details.get("workflow_status", "blocked") != "blocked":
            continue
        details["workflow_status"] = "unblocked"
        details["workflow_updated_at"] = datetime.now(timezone.utc).isoformat()
        details["auto_cleared_reason"] = "gate_rescan_no_actionable_signals"
        alert.details_json = details
        changed = True
    return changed


def _restore_recommendation_if_autoblocked(db: Session, company: Company) -> bool:
    """If latest rec is still an automatic critical block, restore recommended/watchlist from score."""
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
    return True


def reconcile_stale_news_policy_alerts(db: Session) -> dict[str, Any]:
    """
    One-shot DB cleanup: unblock news alerts that would not fire today (outlet allowlist / historical
    headline rules). Restores recommendations that were auto-blocked for those tickers.
    Safe to call without re-running the full SEC pipeline.
    """
    touched: set[int] = set()
    n_alerts = 0
    for alert in db.query(CriticalAlert).all():
        ws = (alert.details_json or {}).get("workflow_status", "blocked")
        if ws != "blocked":
            continue
        if is_actionable_critical_alert(alert):
            continue
        if _has_manually_confirmed_critical_alert(db, alert.company_id):
            continue
        details = dict(alert.details_json or {})
        details["workflow_status"] = "unblocked"
        details["workflow_updated_at"] = datetime.now(timezone.utc).isoformat()
        details["auto_cleared_reason"] = "stale_under_current_news_policy"
        alert.details_json = details
        touched.add(alert.company_id)
        n_alerts += 1
    n_recs = 0
    for cid in touched:
        company = db.query(Company).filter(Company.id == cid).first()
        if company and _restore_recommendation_if_autoblocked(db, company):
            n_recs += 1
    return {"alerts_unblocked": n_alerts, "recommendations_restored": n_recs}


def reconcile_after_gate_passes(db: Session, company: Company) -> bool:
    """
    When the current scan would NOT block: always clear blocked alerts for this company,
    and restore the recommendation if it was auto-blocked.

    Previously we only cleared alerts if the recommendation was still blocked — that left
    orphaned CriticalAlert rows (still workflow=blocked) when state diverged.
    """
    if _has_manually_confirmed_critical_alert(db, company.id):
        return False
    alerts_changed = _unblock_all_blocked_alerts_for_company(db, company.id)
    rec_changed = _restore_recommendation_if_autoblocked(db, company)
    return alerts_changed or rec_changed


def apply_critical_risk_gate(db: Session, company: Company) -> Optional[CriticalAlert]:
    headlines = fetch_recent_headlines(company)
    findings = detect_critical_events(headlines) + _sec_recent_8k_findings(company)
    findings = _filter_findings_by_bankruptcy_recency(findings)

    confidence, source_count = _evaluate_confidence(findings) if findings else ("low", 0)
    min_required = settings.risk_block_min_confidence
    would_block = bool(findings) and _confidence_rank(confidence) >= _confidence_rank(min_required)

    if not would_block:
        if reconcile_after_gate_passes(db, company):
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
