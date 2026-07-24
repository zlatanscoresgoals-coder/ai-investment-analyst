import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import portfolio_service
from app.db import Base


class PortfolioServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.addCleanup(self.db.close)

    def test_positions_persist_in_database_across_sessions(self) -> None:
        with patch.object(portfolio_service, "fetch_live_quote", return_value=None):
            created = portfolio_service.add_position(
                db=self.db,
                ticker="aapl",
                entry_price=100.0,
                shares=2.0,
                entry_date="2026-07-24",
                notes="core holding",
            )

            first_payload = portfolio_service.get_portfolio_payload(self.db)
            self.assertEqual([p["id"] for p in first_payload["positions"]], [created["id"]])

            new_db = self.Session()
            self.addCleanup(new_db.close)
            second_payload = portfolio_service.get_portfolio_payload(new_db)

        self.assertEqual([p["id"] for p in second_payload["positions"]], [created["id"]])
        self.assertEqual(second_payload["positions"][0]["ticker"], "AAPL")
        self.assertEqual(second_payload["summary"]["totalInvested"], 200.0)

    def test_legacy_json_positions_are_migrated_once_to_database(self) -> None:
        portfolio_path = Path(self.tmpdir.name) / "portfolio.json"
        portfolio_path.write_text(
            json.dumps(
                {
                    "positions": [
                        {
                            "id": "legacy-position",
                            "ticker": "msft",
                            "company": "Microsoft",
                            "entryPrice": 50.0,
                            "entryDate": "2026-07-20",
                            "shares": 3.0,
                            "notes": "import me",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        with (
            patch.object(portfolio_service, "PORTFOLIO_PATH", portfolio_path),
            patch.object(portfolio_service, "fetch_live_quote", return_value=None),
        ):
            migrated = portfolio_service.load_positions(self.db)
            self.assertEqual([p["id"] for p in migrated], ["legacy-position"])
            self.assertEqual(json.loads(portfolio_path.read_text(encoding="utf-8")), {"positions": []})

            portfolio_path.unlink()
            new_db = self.Session()
            self.addCleanup(new_db.close)
            persisted = portfolio_service.load_positions(new_db)

        self.assertEqual([p["id"] for p in persisted], ["legacy-position"])
        self.assertEqual(persisted[0]["ticker"], "MSFT")


if __name__ == "__main__":
    unittest.main()
