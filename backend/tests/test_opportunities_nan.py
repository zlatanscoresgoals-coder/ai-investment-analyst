import json
import math
import sys
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.opportunities import earnings, regime  # noqa: E402


class OpportunitiesNanTests(unittest.TestCase):
    def test_regime_scan_filters_nan_closes(self):
        original_fetch = regime._fetch_history
        original_sector_etfs = regime.SECTOR_ETFS

        def fake_fetch(symbol: str, days: int = 300):
            if symbol == "^VIX":
                return [20.0] * 29 + [math.nan]
            series_len = max(days, 220)
            series = [100.0 + i * 0.1 for i in range(series_len)]
            series[-1] = math.nan
            return series

        try:
            regime._fetch_history = fake_fetch
            regime.SECTOR_ETFS = {"XLK": "Technology"}

            result = regime.scan_regime(["AAPL"])
        finally:
            regime._fetch_history = original_fetch
            regime.SECTOR_ETFS = original_sector_etfs

        json.dumps(result, allow_nan=False)
        self.assertIsNotNone(result["spy_current"])
        self.assertIsNotNone(result["vix_current"])
        self.assertEqual(len(result["sectors"]), 1)

    def test_earnings_fetch_omits_nan_info_and_surprises(self):
        future_earnings = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")

        class FakeTicker:
            def __init__(self, ticker: str):
                self.ticker = ticker
                self.info = {
                    "shortName": ticker,
                    "currentPrice": math.nan,
                    "regularMarketPrice": math.nan,
                    "targetMeanPrice": math.nan,
                    "forwardEps": math.nan,
                }
                self.calendar = {"Earnings Date": [future_earnings]}
                self.earnings_history = {
                    "2025-Q1": {"epsActual": math.nan, "epsEstimate": 1.0},
                    "2025-Q2": {"epsActual": 1.2, "epsEstimate": 1.0},
                }

        fake_yfinance = types.SimpleNamespace(Ticker=FakeTicker)
        original_yfinance = sys.modules.get("yfinance")
        sys.modules["yfinance"] = fake_yfinance
        try:
            result = earnings._fetch_earnings("NAN")
        finally:
            if original_yfinance is None:
                sys.modules.pop("yfinance", None)
            else:
                sys.modules["yfinance"] = original_yfinance

        self.assertIsNotNone(result)
        json.dumps(result, allow_nan=False)
        assert result is not None
        self.assertIsNone(result["current_price"])
        self.assertIsNone(result["target_price"])
        self.assertIsNone(result["eps_estimate"])
        self.assertEqual(result["total_quarters"], 1)
        self.assertEqual(len(result["surprise_history"]), 1)


if __name__ == "__main__":
    unittest.main()
