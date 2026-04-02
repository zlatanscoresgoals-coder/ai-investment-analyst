"""Starter universe for Meridian recommendations (dashboard + full pipeline scope)."""

from __future__ import annotations

from typing import Optional

# Ticker symbols must match SEC / internal DB (e.g. BRK-B).
STARTER_COMPANIES: list[tuple[str, str]] = [
    ("AAPL", "Apple Inc."),
    ("MSFT", "Microsoft Corporation"),
    ("GOOGL", "Alphabet Inc."),
    ("AMZN", "Amazon.com, Inc."),
    ("XOM", "Exxon Mobil Corporation"),
    ("CVX", "Chevron Corporation"),
    ("NVDA", "NVIDIA Corporation"),
    ("TSLA", "Tesla, Inc."),
    ("JPM", "JPMorgan Chase & Co."),
    ("BRK-B", "Berkshire Hathaway Inc."),
]

MERIDIAN_TICKERS: frozenset[str] = frozenset(t for t, _ in STARTER_COMPANIES)

# Display / EV-heuristic fallback when SEC submissions omit ownerOrg sector (dashboard pill + valuation).
MERIDIAN_SECTOR_FALLBACK: dict[str, str] = {
    "AAPL": "Technology",
    "MSFT": "Technology",
    "GOOGL": "Communication Services",
    "AMZN": "Consumer Cyclical",
    "XOM": "Energy",
    "CVX": "Energy",
    "NVDA": "Technology",
    "TSLA": "Consumer Cyclical",
    "JPM": "Financial Services",
    "BRK-B": "Financial Services",
}


def resolve_sector_for_display(ticker: str, stored_sector: Optional[str]) -> Optional[str]:
    """Prefer DB/SEC sector; else known Meridian universe label."""
    if stored_sector and str(stored_sector).strip():
        return str(stored_sector).strip()
    t = (ticker or "").upper().strip()
    return MERIDIAN_SECTOR_FALLBACK.get(t)
