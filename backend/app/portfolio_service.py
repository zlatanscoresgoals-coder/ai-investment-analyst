"""Local JSON portfolio store + enrichment with live quotes and chart series."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.market.quotes import fetch_live_quote
from app.models import Company

PORTFOLIO_PATH = Path(__file__).resolve().parent.parent / "data" / "portfolio.json"


def _ensure_parent() -> None:
    PORTFOLIO_PATH.parent.mkdir(parents=True, exist_ok=True)


def load_positions() -> list[dict[str, Any]]:
    _ensure_parent()
    if not PORTFOLIO_PATH.exists():
        PORTFOLIO_PATH.write_text(json.dumps({"positions": []}, indent=2), encoding="utf-8")
    data = json.loads(PORTFOLIO_PATH.read_text(encoding="utf-8"))
    rows = data.get("positions")
    return list(rows) if isinstance(rows, list) else []


def save_positions(positions: list[dict[str, Any]]) -> None:
    _ensure_parent()
    PORTFOLIO_PATH.write_text(json.dumps({"positions": positions}, indent=2), encoding="utf-8")


def _parse_iso_date(s: str) -> date:
    return datetime.strptime((s or "")[:10], "%Y-%m-%d").date()


def _resolve_company(db: Optional[Session], ticker: str) -> str:
    if db is None:
        return ticker
    row = db.query(Company).filter(Company.ticker == ticker.upper().strip()).first()
    return row.name if row and row.name else ticker.upper()


def add_position(
    *,
    db: Optional[Session],
    ticker: str,
    entry_price: float,
    shares: float,
    entry_date: str,
    notes: str = "",
    company: str = "",
) -> dict[str, Any]:
    t = ticker.upper().strip()
    co = (company or "").strip() or _resolve_company(db, t)
    pos = {
        "id": uuid.uuid4().hex,
        "ticker": t,
        "company": co,
        "entryPrice": float(entry_price),
        "entryDate": entry_date[:10],
        "shares": float(shares),
        "notes": (notes or "").strip(),
    }
    positions = load_positions()
    positions.append(pos)
    save_positions(positions)
    return pos


def delete_position(position_id: str) -> bool:
    positions = load_positions()
    n = len(positions)
    positions = [p for p in positions if str(p.get("id")) != position_id]
    if len(positions) == n:
        return False
    save_positions(positions)
    return True


def _enrich_one(p: dict[str, Any]) -> dict[str, Any]:
    ticker = str(p.get("ticker", "")).upper()
    entry = float(p.get("entryPrice") or 0)
    sh = float(p.get("shares") or 0)
    cost = entry * sh
    q = fetch_live_quote(ticker)
    last = q.get("last_price") if q else None
    cur_px = float(last) if last is not None and float(last) > 0 else entry
    mval = cur_px * sh
    pl = mval - cost
    pl_pct = (pl / cost * 100.0) if cost > 0 else 0.0
    try:
        ed = _parse_iso_date(str(p.get("entryDate", "")))
        days_held = max(0, (date.today() - ed).days)
    except ValueError:
        days_held = 0
    out = dict(p)
    out["currentPrice"] = round(cur_px, 4)
    out["marketValue"] = round(mval, 2)
    out["costBasis"] = round(cost, 2)
    out["gainLoss"] = round(pl, 2)
    out["gainLossPct"] = round(pl_pct, 2)
    out["daysHeld"] = days_held
    out["quoteSource"] = (q or {}).get("source")
    return out


def build_daily_value_series(positions: list[dict[str, Any]], max_points: int = 450) -> list[dict[str, Any]]:
    """Linear interpolate each holding from entry price to current price; sum per calendar day."""
    if not positions:
        return []
    entry_dates: list[date] = []
    for p in positions:
        try:
            entry_dates.append(_parse_iso_date(str(p.get("entryDate", ""))))
        except ValueError:
            continue
    if not entry_dates:
        return []
    start = min(entry_dates)
    end = date.today()
    series: list[dict[str, Any]] = []
    d = start
    while d <= end:
        day_total = 0.0
        for p in positions:
            try:
                ed = _parse_iso_date(str(p.get("entryDate", "")))
            except ValueError:
                continue
            if d < ed:
                continue
            ep = float(p.get("entryPrice") or 0)
            sh = float(p.get("shares") or 0)
            cp = float(p.get("currentPrice") or ep)
            span_days = max(1, (end - ed).days)
            elapsed = (d - ed).days
            frac = min(1.0, elapsed / span_days)
            px = ep + (cp - ep) * frac
            day_total += sh * px
        series.append({"date": d.isoformat(), "value": round(day_total, 2)})
        d += timedelta(days=1)
    if len(series) > max_points:
        step = max(1, len(series) // max_points)
        series = series[::step] + [series[-1]]
    return series


def compute_summary(enriched: list[dict[str, Any]]) -> dict[str, Any]:
    if not enriched:
        return {
            "totalInvested": 0.0,
            "currentValue": 0.0,
            "totalGainLoss": 0.0,
            "totalGainLossPct": 0.0,
            "bestTicker": None,
            "bestPct": None,
            "worstTicker": None,
            "worstPct": None,
        }
    inv = sum(float(p.get("costBasis") or 0) for p in enriched)
    cur = sum(float(p.get("marketValue") or 0) for p in enriched)
    tg = cur - inv
    tgp = (tg / inv * 100.0) if inv > 0 else 0.0
    by_pct = [(p["ticker"], float(p.get("gainLossPct") or 0)) for p in enriched if float(p.get("costBasis") or 0) > 0]
    best_t, best_p = None, None
    worst_t, worst_p = None, None
    if by_pct:
        best_t, best_p = max(by_pct, key=lambda x: x[1])
        worst_t, worst_p = min(by_pct, key=lambda x: x[1])
    return {
        "totalInvested": round(inv, 2),
        "currentValue": round(cur, 2),
        "totalGainLoss": round(tg, 2),
        "totalGainLossPct": round(tgp, 2),
        "bestTicker": best_t,
        "bestPct": round(best_p, 2) if best_p is not None else None,
        "worstTicker": worst_t,
        "worstPct": round(worst_p, 2) if worst_p is not None else None,
    }


def get_portfolio_payload(db: Optional[Session]) -> dict[str, Any]:
    raw = load_positions()
    enriched = [_enrich_one(p) for p in raw]
    summary = compute_summary(enriched)
    chart = build_daily_value_series(enriched)
    return {"positions": enriched, "summary": summary, "chart": chart}
