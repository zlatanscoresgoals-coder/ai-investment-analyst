import sys
import types
import unittest
from datetime import datetime, timedelta, timezone

from app.opportunities import earnings


class _FakeTicker:
    def __init__(self, calendar):
        self.info = {
            "shortName": "Test Co",
            "currentPrice": 100.0,
            "targetMeanPrice": 110.0,
            "forwardEps": 5.0,
        }
        self.calendar = calendar
        self.earnings_history = None


class EarningsRadarTests(unittest.TestCase):
    def test_date_only_same_day_earnings_are_not_actionable_after_midnight(self):
        today = datetime.now(timezone.utc).date().isoformat()
        fake_yfinance = types.SimpleNamespace(
            Ticker=lambda _ticker: _FakeTicker({"Earnings Date": [today]})
        )
        old_yfinance = sys.modules.get("yfinance")
        sys.modules["yfinance"] = fake_yfinance
        try:
            self.assertIsNone(earnings._fetch_earnings("TEST"))
        finally:
            if old_yfinance is None:
                sys.modules.pop("yfinance", None)
            else:
                sys.modules["yfinance"] = old_yfinance

    def test_future_intraday_earnings_still_return_days_until(self):
        future = datetime.now(timezone.utc) + timedelta(days=3, hours=2)
        fake_yfinance = types.SimpleNamespace(
            Ticker=lambda _ticker: _FakeTicker({"Earnings Date": [future]})
        )
        old_yfinance = sys.modules.get("yfinance")
        sys.modules["yfinance"] = fake_yfinance
        try:
            row = earnings._fetch_earnings("TEST")
        finally:
            if old_yfinance is None:
                sys.modules.pop("yfinance", None)
            else:
                sys.modules["yfinance"] = old_yfinance
        self.assertIsNotNone(row)
        self.assertEqual(row["earnings_date"], future.date().isoformat())
        self.assertGreaterEqual(row["days_until"], 2)

    def test_negative_days_do_not_get_pre_earnings_setup(self):
        row = earnings._assign_flag(
            {"ticker": "TEST", "beats": 4, "misses": 0, "total_quarters": 4, "days_until": -1},
            {"TEST": 90.0},
        )
        self.assertEqual(row["flag"], "green")
        self.assertNotIn("setup", row)


if __name__ == "__main__":
    unittest.main()
