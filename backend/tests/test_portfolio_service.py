from datetime import date, timedelta
import unittest

from app.portfolio_service import build_daily_value_series


class PortfolioChartSeriesTest(unittest.TestCase):
    def test_short_portfolio_preserves_daily_points(self):
        start = date.today() - timedelta(days=2)

        series = build_daily_value_series(
            [
                {
                    "entryDate": start.isoformat(),
                    "entryPrice": 100,
                    "currentPrice": 130,
                    "shares": 2,
                }
            ],
            max_points=10,
        )

        self.assertEqual([row["date"] for row in series], [(start + timedelta(days=i)).isoformat() for i in range(3)])
        self.assertEqual(series[0]["value"], 200)
        self.assertEqual(series[-1]["value"], 260)

    def test_ancient_entry_date_is_sampled_to_max_points(self):
        series = build_daily_value_series(
            [
                {
                    "entryDate": "0001-01-01",
                    "entryPrice": 100,
                    "currentPrice": 200,
                    "shares": 1,
                }
            ],
            max_points=10,
        )

        self.assertEqual(len(series), 10)
        self.assertEqual(series[0]["date"], "0001-01-01")
        self.assertEqual(series[-1]["date"], date.today().isoformat())
        self.assertEqual(series[0]["value"], 100)
        self.assertEqual(series[-1]["value"], 200)


if __name__ == "__main__":
    unittest.main()
