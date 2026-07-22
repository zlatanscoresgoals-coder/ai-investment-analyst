import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.market import quotes
from app.schemas import PortfolioAddIn
import app.portfolio_service as portfolio_service


class NonFiniteNumberTests(unittest.TestCase):
    def test_portfolio_schema_rejects_non_finite_values(self) -> None:
        for field in ("entryPrice", "shares"):
            payload = {
                "ticker": "AAPL",
                "entryPrice": 100.0,
                "shares": 1.0,
                "entryDate": "2026-07-22",
            }
            payload[field] = float("inf")
            with self.assertRaises(Exception):
                PortfolioAddIn(**payload)

    def test_portfolio_load_skips_poisoned_non_finite_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "portfolio.json"
            path.write_text(
                """
                {
                  "positions": [
                    {"id": "inf", "ticker": "BAD", "entryPrice": Infinity, "shares": 1, "entryDate": "2026-07-22"},
                    {"id": "overflow", "ticker": "BAD2", "entryPrice": 1e309, "shares": 1, "entryDate": "2026-07-22"},
                    {"id": "ok", "ticker": "AAPL", "entryPrice": 100.0, "shares": 2, "entryDate": "2026-07-22"}
                  ]
                }
                """,
                encoding="utf-8",
            )

            with patch.object(portfolio_service, "PORTFOLIO_PATH", path):
                positions = portfolio_service.load_positions()

        self.assertEqual([p["id"] for p in positions], ["ok"])
        self.assertEqual(positions[0]["entryPrice"], 100.0)
        self.assertEqual(positions[0]["shares"], 2.0)

    def test_portfolio_save_rejects_non_finite_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "portfolio.json"
            with patch.object(portfolio_service, "PORTFOLIO_PATH", path):
                with self.assertRaises(ValueError):
                    portfolio_service.save_positions(
                        [
                            {
                                "id": "bad",
                                "ticker": "BAD",
                                "entryPrice": float("inf"),
                                "shares": 1.0,
                                "entryDate": "2026-07-22",
                            }
                        ]
                    )
                self.assertFalse(path.exists())

    def test_poisoned_portfolio_payload_remains_strict_json_serializable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "portfolio.json"
            path.write_text(
                """
                {
                  "positions": [
                    {"id": "bad", "ticker": "BAD", "entryPrice": Infinity, "shares": 1, "entryDate": "2026-07-22"},
                    {"id": "ok", "ticker": "AAPL", "entryPrice": 100.0, "shares": 2, "entryDate": "2026-07-22"}
                  ]
                }
                """,
                encoding="utf-8",
            )

            with (
                patch.object(portfolio_service, "PORTFOLIO_PATH", path),
                patch.object(portfolio_service, "fetch_live_quote", return_value={"last_price": float("inf")}),
            ):
                payload = portfolio_service.get_portfolio_payload(db=None)

        self.assertEqual([p["id"] for p in payload["positions"]], ["ok"])
        self.assertEqual(payload["positions"][0]["currentPrice"], 100.0)
        json.dumps(payload, allow_nan=False)

    def test_quote_safe_float_rejects_non_finite_values(self) -> None:
        self.assertIsNone(quotes._safe_float(float("inf")))
        self.assertIsNone(quotes._safe_float("1e309"))
        self.assertIsNone(quotes._safe_float(float("nan")))
        self.assertEqual(quotes._safe_float("123.45"), 123.45)


if __name__ == "__main__":
    unittest.main()
