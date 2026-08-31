import threading
import time
import unittest
from unittest.mock import patch

from app import portfolio_service


class PortfolioPayloadTests(unittest.TestCase):
    def test_quote_enrichment_runs_concurrently_and_preserves_order(self):
        positions = [
            {"id": "1", "ticker": "AAA", "entryPrice": 10.0, "shares": 1.0, "entryDate": "2026-01-01"},
            {"id": "2", "ticker": "BBB", "entryPrice": 20.0, "shares": 2.0, "entryDate": "2026-01-01"},
            {"id": "3", "ticker": "CCC", "entryPrice": 30.0, "shares": 3.0, "entryDate": "2026-01-01"},
            {"id": "4", "ticker": "DDD", "entryPrice": 40.0, "shares": 4.0, "entryDate": "2026-01-01"},
        ]
        active = 0
        max_active = 0
        lock = threading.Lock()

        def slow_quote(ticker):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return {"last_price": 100.0, "source": f"test-{ticker}"}

        with (
            patch.object(portfolio_service, "load_positions", return_value=positions),
            patch.object(portfolio_service, "fetch_live_quote", side_effect=slow_quote),
        ):
            payload = portfolio_service.get_portfolio_payload(None)

        self.assertGreater(max_active, 1)
        self.assertEqual([p["ticker"] for p in payload["positions"]], ["AAA", "BBB", "CCC", "DDD"])
        self.assertEqual([p["quoteSource"] for p in payload["positions"]], ["test-AAA", "test-BBB", "test-CCC", "test-DDD"])


if __name__ == "__main__":
    unittest.main()
