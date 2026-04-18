"""Shared 50-stock large-cap screening universe and sector ETF list."""

SCREEN_UNIVERSE: list[str] = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "BRK-B", "LLY", "JPM", "V",
    "UNH", "XOM", "MA", "JNJ", "PG", "HD", "MRK", "AVGO", "CVX", "ABBV",
    "KO", "PEP", "COST", "WMT", "BAC", "MCD", "CRM", "ACN", "LIN", "TMO",
    "ABT", "CSCO", "DHR", "NEE", "TXN", "VZ", "INTC", "ADBE", "NFLX", "CMCSA",
    "PM", "RTX", "HON", "UPS", "AMGN", "IBM", "GS", "CAT", "BA", "MMM",
]

SECTOR_ETFS: dict[str, str] = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Health Care",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLI": "Industrials",
    "XLB": "Materials",
    "XLU": "Utilities",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
}
