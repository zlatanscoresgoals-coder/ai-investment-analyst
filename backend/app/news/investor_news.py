"""Live headlines from trusted outlets for dashboard context (not a trading signal)."""

from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import quote, urlparse
from xml.etree import ElementTree

import requests

from app.config import settings
from app.models import Company
from app.risk.critical_events import (
    _parse_iso_utc,
    _parse_rss_pub_date,
    _row_passes_outlet_allowlist,
)

# NewsAPI `domains=` filter (outlets we treat as primary / credible for investors).
_TRUSTED_DOMAINS_NEWSAPI = (
    "reuters.com,bloomberg.com,ft.com,wsj.com,cnbc.com,bbc.co.uk,bbc.com,"
    "economist.com,nytimes.com,washingtonpost.com,apnews.com,marketwatch.com,"
    "barrons.com,fortune.com,investopedia.com,nikkei.com,japantimes.co.jp"
)


def _domain_from_url(url: Optional[str]) -> str:
    if not url or not isinstance(url, str):
        return ""
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def _row_for_allowlist(
    headline: str,
    *,
    outlet_name: str = "",
    outlet_domain: str = "",
    feed: str = "google_news_rss",
) -> dict[str, Any]:
    return {
        "headline": headline,
        "outlet_name": outlet_name,
        "outlet_domain": outlet_domain,
        "source": feed,
    }


def _fetch_newsapi(company: Company, cutoff: datetime, limit: int, api_key: str) -> list[dict[str, Any]]:
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": company.ticker,
        "from": cutoff.date().isoformat(),
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": min(max(limit * 2, 10), 50),
        "domains": _TRUSTED_DOMAINS_NEWSAPI,
        "apiKey": api_key,
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    out: list[dict[str, Any]] = []
    for a in data.get("articles") or []:
        title = (a.get("title") or "").strip()
        if not title:
            continue
        pub = _parse_iso_utc(a.get("publishedAt"))
        if pub is not None and pub < cutoff:
            continue
        src = a.get("source") if isinstance(a.get("source"), dict) else {}
        outlet_name = (src.get("name") or "").strip()
        link = a.get("url") or ""
        row = _row_for_allowlist(
            title,
            outlet_name=outlet_name,
            outlet_domain=_domain_from_url(link),
            feed="newsapi",
        )
        if not _row_passes_outlet_allowlist(row):
            continue
        out.append(
            {
                "title": title,
                "url": link or "#",
                "source_name": outlet_name or None,
                "published_at": pub.isoformat() if pub else None,
                "description": (a.get("description") or "").strip() or None,
            }
        )
    out.sort(key=lambda x: x.get("published_at") or "", reverse=True)
    return out[:limit]


def _fetch_google_rss(company: Company, cutoff: datetime, limit: int) -> list[dict[str, Any]]:
    query = f"{company.ticker} ({company.name})"
    rss_url = f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en"
    r = requests.get(rss_url, timeout=20)
    r.raise_for_status()
    root = ElementTree.fromstring(r.content)
    items = root.findall(".//item")
    out: list[dict[str, Any]] = []
    for item in items[:50]:
        title = html.unescape(item.findtext("title") or "").strip()
        if not title:
            continue
        link = item.findtext("link") or ""
        pub = _parse_rss_pub_date(item.findtext("pubDate"))
        if pub is not None and pub < cutoff:
            continue
        outlet_name = ""
        src_el = item.find("source")
        if src_el is not None and src_el.text and src_el.text.strip():
            outlet_name = html.unescape(src_el.text.strip())
        row = _row_for_allowlist(
            title,
            outlet_name=outlet_name,
            outlet_domain=_domain_from_url(link),
            feed="google_news_rss",
        )
        if not _row_passes_outlet_allowlist(row):
            continue
        out.append(
            {
                "title": title,
                "url": link or "#",
                "source_name": outlet_name or None,
                "published_at": pub.isoformat() if pub else None,
                "description": None,
            }
        )
    out.sort(key=lambda x: x.get("published_at") or "", reverse=True)
    return out[:limit]


def fetch_investor_news(
    company: Company,
    *,
    days: int = 10,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """
    Recent headlines (within `days`) from the same trusted-outlet policy as the old risk gate.
    Prefer NewsAPI when NEWSAPI_KEY is set (domain-filtered); otherwise Google News RSS + allowlist.
    Fetched on each request (live) — not stored in DB.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    key = (settings.newsapi_key or "").strip()
    if key:
        try:
            rows = _fetch_newsapi(company, cutoff, limit, key)
            if rows:
                return rows
        except Exception:
            pass
    try:
        return _fetch_google_rss(company, cutoff, limit)
    except Exception:
        return []
