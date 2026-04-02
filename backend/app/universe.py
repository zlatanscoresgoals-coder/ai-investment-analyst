"""Starter universe for Meridian recommendations (dashboard + full pipeline scope)."""

from __future__ import annotations

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
