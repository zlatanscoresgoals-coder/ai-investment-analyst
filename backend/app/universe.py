"""Screening universe for Meridian: loaded from data file (not a fixed list of ten)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

_CANDIDATE_FILE = Path(__file__).resolve().parent.parent / "data" / "meridian_candidate_universe.json"


def _default_candidates() -> list[dict[str, Any]]:
    return [
        {"ticker": "AAPL", "name": "Apple Inc.", "sector": "Technology"},
        {"ticker": "MSFT", "name": "Microsoft Corporation", "sector": "Technology"},
    ]


def load_candidate_universe_raw() -> list[dict[str, Any]]:
    if not _CANDIDATE_FILE.is_file():
        return _default_candidates()
    try:
        data = json.loads(_CANDIDATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_candidates()
    if not isinstance(data, list) or not data:
        return _default_candidates()
    return data


def load_candidate_companies() -> list[tuple[str, str]]:
    """(ticker, name) pairs — reads JSON on each call so edits apply without redeploy."""
    out: list[tuple[str, str]] = []
    for row in load_candidate_universe_raw():
        if not isinstance(row, dict):
            continue
        t = (row.get("ticker") or "").strip().upper()
        n = (row.get("name") or t).strip() or t
        if t:
            out.append((t, n[:255]))
    return out


def get_candidate_companies() -> list[tuple[str, str]]:
    return load_candidate_companies()


def get_candidate_tickers() -> frozenset[str]:
    return frozenset(t for t, _ in load_candidate_companies())


def sector_fallback_map() -> dict[str, str]:
    m: dict[str, str] = {}
    for row in load_candidate_universe_raw():
        if not isinstance(row, dict):
            continue
        t = (row.get("ticker") or "").strip().upper()
        s = (row.get("sector") or "").strip()
        if t and s:
            m[t] = s
    return m


def resolve_sector_for_display(ticker: str, stored_sector: Optional[str]) -> Optional[str]:
    if stored_sector and str(stored_sector).strip():
        return str(stored_sector).strip()
    t = (ticker or "").upper().strip()
    return sector_fallback_map().get(t)
