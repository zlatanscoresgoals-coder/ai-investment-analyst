import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import main
from app.db import Base
from app.models import Company


class AnalysisRouteFilingSyncTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()

    def _add_company(self, ticker: str) -> Company:
        company = Company(ticker=ticker, name=ticker)
        self.db.add(company)
        self.db.commit()
        self.db.refresh(company)
        return company

    def test_run_analysis_syncs_filings_before_scoring(self):
        self._add_company("AAPL")
        calls: list[tuple[str, str]] = []

        def sync_filings(db, company):
            calls.append(("sync", company.ticker))
            return (1, 0, False)

        def score_company(db, company):
            calls.append(("score", company.ticker))

        with (
            patch.object(main, "_store_filings_and_metrics", side_effect=sync_filings),
            patch.object(main, "run_recommendation_for_company", side_effect=score_company),
        ):
            response = main.run_analysis("AAPL", db=self.db)

        self.assertEqual(response.message, "Analysis and scoring completed for AAPL.")
        self.assertEqual(calls, [("sync", "AAPL"), ("score", "AAPL")])

    def test_run_analysis_does_not_score_when_filing_sync_fails(self):
        self._add_company("MSFT")

        with (
            patch.object(main, "_store_filings_and_metrics", side_effect=RuntimeError("SEC unavailable")),
            patch.object(main, "run_recommendation_for_company") as score_company,
        ):
            with self.assertRaises(HTTPException) as ctx:
                main.run_analysis("MSFT", db=self.db)

        self.assertEqual(ctx.exception.status_code, 502)
        score_company.assert_not_called()

    def test_run_recommendations_syncs_each_company_and_reports_failures(self):
        self._add_company("AAPL")
        self._add_company("MSFT")
        calls: list[tuple[str, str]] = []

        def sync_filings(db, company):
            calls.append(("sync", company.ticker))
            if company.ticker == "MSFT":
                raise RuntimeError("SEC unavailable")
            return (1, 0, False)

        def score_company(db, company):
            calls.append(("score", company.ticker))

        with (
            patch.object(main, "_store_filings_and_metrics", side_effect=sync_filings),
            patch.object(main, "run_recommendation_for_company", side_effect=score_company),
        ):
            response = main.run_recommendations(meridian_only=False, db=self.db)

        self.assertEqual(calls, [("sync", "AAPL"), ("score", "AAPL"), ("sync", "MSFT")])
        self.assertEqual(response.failures, ["MSFT: RuntimeError: SEC unavailable"])
        self.assertIn("Recommendations updated for 1 of 2 companies (all DB). Failed: 1.", response.message)


if __name__ == "__main__":
    unittest.main()
