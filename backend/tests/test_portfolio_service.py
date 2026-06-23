from __future__ import annotations

import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import portfolio_service


class PortfolioServiceConcurrencyTest(unittest.TestCase):
    def test_concurrent_adds_preserve_every_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            portfolio_path = Path(tmp) / "portfolio.json"

            def add_one(i: int) -> str:
                pos = portfolio_service.add_position(
                    db=None,
                    ticker=f"T{i}",
                    entry_price=100.0 + i,
                    shares=1.0,
                    entry_date="2026-06-23",
                )
                return str(pos["id"])

            with patch.object(portfolio_service, "PORTFOLIO_PATH", portfolio_path):
                with ThreadPoolExecutor(max_workers=12) as pool:
                    ids = list(pool.map(add_one, range(48)))

                positions = portfolio_service.load_positions()

        self.assertEqual(len(ids), 48)
        self.assertEqual(len(set(ids)), 48)
        self.assertEqual(len(positions), 48)
        self.assertEqual({p["ticker"] for p in positions}, {f"T{i}" for i in range(48)})

    def test_delete_updates_are_written_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            portfolio_path = Path(tmp) / "portfolio.json"
            with patch.object(portfolio_service, "PORTFOLIO_PATH", portfolio_path):
                kept = portfolio_service.add_position(
                    db=None,
                    ticker="KEEP",
                    entry_price=10.0,
                    shares=2.0,
                    entry_date="2026-06-23",
                )
                removed = portfolio_service.add_position(
                    db=None,
                    ticker="DROP",
                    entry_price=20.0,
                    shares=1.0,
                    entry_date="2026-06-23",
                )

                self.assertTrue(portfolio_service.delete_position(str(removed["id"])))
                self.assertFalse(portfolio_service.delete_position("missing"))
                positions = portfolio_service.load_positions()

        self.assertEqual([p["id"] for p in positions], [kept["id"]])
        self.assertEqual(positions[0]["ticker"], "KEEP")


if __name__ == "__main__":
    unittest.main()
