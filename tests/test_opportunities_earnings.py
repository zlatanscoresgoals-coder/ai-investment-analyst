import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


_TMP = tempfile.TemporaryDirectory()
_REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_TMP.name) / 'test.db'}"
os.environ["AUTO_REFRESH_ENABLED"] = "false"
sys.path.insert(0, str(_REPO_ROOT / "backend"))

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import api_earnings  # noqa: E402
from app.models import Company, Recommendation  # noqa: E402


class EarningsOpportunitiesTests(unittest.TestCase):
    def setUp(self) -> None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

    def tearDown(self) -> None:
        Base.metadata.drop_all(bind=engine)

    def test_earnings_endpoint_uses_latest_screen_universe_scores(self) -> None:
        db = SessionLocal()
        now = datetime.now(timezone.utc)
        try:
            aapl = Company(ticker="AAPL", name="Apple Inc.")
            msft = Company(ticker="MSFT", name="Microsoft Corp.")
            outside = Company(ticker="ZZZ", name="Outside Universe")
            db.add_all([aapl, msft, outside])
            db.flush()

            # Historical rows accumulate on every auto-refresh run. The endpoint
            # should only read the latest row per screen-universe company.
            for i in range(20):
                db.add(
                    Recommendation(
                        company_id=aapl.id,
                        as_of=now - timedelta(days=i + 1),
                        status="recommended",
                        final_score=10.0 + i,
                        summary="old AAPL recommendation",
                    )
                )
            db.add_all(
                [
                    Recommendation(
                        company_id=aapl.id,
                        as_of=now,
                        status="recommended",
                        final_score=91.5,
                        summary="latest AAPL recommendation",
                    ),
                    Recommendation(
                        company_id=msft.id,
                        as_of=now - timedelta(minutes=1),
                        status="watchlist",
                        final_score=72.0,
                        summary="latest MSFT recommendation",
                    ),
                    Recommendation(
                        company_id=outside.id,
                        as_of=now,
                        status="recommended",
                        final_score=99.0,
                        summary="outside screen universe",
                    ),
                ]
            )
            db.commit()
        finally:
            db.close()

        captured: dict[str, dict[str, float]] = {}

        def fake_scan(universe: list[str], meridian_scores: dict[str, float]):
            captured["scores"] = dict(meridian_scores)
            return []

        db = SessionLocal()
        try:
            with patch("app.opportunities.earnings.scan_earnings", side_effect=fake_scan):
                response = api_earnings(db=db)
        finally:
            db.close()

        self.assertEqual(response, [])
        self.assertEqual(captured["scores"], {"AAPL": 91.5, "MSFT": 72.0})


if __name__ == "__main__":
    unittest.main()
