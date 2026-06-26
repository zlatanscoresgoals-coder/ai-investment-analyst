import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import portfolio_service


class PortfolioStoreTests(unittest.TestCase):
    def test_load_positions_returns_empty_for_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "portfolio.json"
            path.write_text("{", encoding="utf-8")

            with patch.object(portfolio_service, "PORTFOLIO_PATH", path):
                self.assertEqual(portfolio_service.load_positions(), [])

    def test_load_positions_returns_empty_for_unexpected_json_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "portfolio.json"
            path.write_text(json.dumps(["not", "a", "store"]), encoding="utf-8")

            with patch.object(portfolio_service, "PORTFOLIO_PATH", path):
                self.assertEqual(portfolio_service.load_positions(), [])

    def test_save_positions_replaces_file_with_valid_store(self) -> None:
        position = {
            "id": "abc",
            "ticker": "AAPL",
            "company": "Apple Inc.",
            "entryPrice": 100.0,
            "entryDate": "2026-01-01",
            "shares": 2.0,
            "notes": "",
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "portfolio.json"

            with patch.object(portfolio_service, "PORTFOLIO_PATH", path):
                portfolio_service.save_positions([position])

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"positions": [position]})
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
