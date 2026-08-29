import unittest
from datetime import datetime
from unittest import mock

from fastapi import Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.main import list_recommendations, recommendations_leaderboard
from app.models import Company, Recommendation


class RecommendationBulkRouteTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self._seed_recommendations()

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _seed_recommendations(self):
        db = self.SessionLocal()
        try:
            aapl = Company(ticker="AAPL", name="Apple Inc.", sector="Technology")
            msft = Company(ticker="MSFT", name="Microsoft Corporation", sector="Technology")
            db.add_all([aapl, msft])
            db.flush()
            as_of = datetime(2026, 8, 29, 11, 0, 0)
            db.add_all(
                [
                    Recommendation(
                        company_id=aapl.id,
                        status="recommended",
                        final_score=92.0,
                        summary="High quality recommendation",
                        horizon="long",
                        as_of=as_of,
                    ),
                    Recommendation(
                        company_id=msft.id,
                        status="watchlist",
                        final_score=81.0,
                        summary="Watchlist candidate",
                        horizon="long",
                        as_of=as_of,
                    ),
                ]
            )
            db.commit()
        finally:
            db.close()

    def test_recommendations_list_does_not_fetch_live_quotes(self):
        db = self.SessionLocal()
        try:
            with mock.patch("app.main.fetch_live_quote", side_effect=AssertionError("live quote fetched")) as quote:
                rows = list_recommendations(
                    Response(),
                    status="recommended",
                    meridian_universe_only=False,
                    db=db,
                )
        finally:
            db.close()
        self.assertEqual([row.ticker for row in rows], ["AAPL"])
        self.assertIsNone(rows[0].last_price)
        quote.assert_not_called()

    def test_leaderboard_does_not_fetch_live_quotes(self):
        db = self.SessionLocal()
        try:
            with mock.patch("app.main.fetch_live_quote", side_effect=AssertionError("live quote fetched")) as quote:
                rows = recommendations_leaderboard(Response(), limit=2, db=db)
        finally:
            db.close()
        self.assertEqual([row.ticker for row in rows], ["AAPL", "MSFT"])
        self.assertTrue(all(row.last_price is None for row in rows))
        quote.assert_not_called()


if __name__ == "__main__":
    unittest.main()
