import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Company, FinancialMetric
from app.recommendations import engine as recommendation_engine


def _metric_payload(fiscal_year: int, revenue: float) -> dict:
    return {
        "fiscal_year": fiscal_year,
        "revenue": revenue,
        "gross_margin": 45.0,
        "operating_margin": 25.0,
        "net_margin": 20.0,
        "fcf": revenue * 0.2,
        "roic": 18.0,
        "roe": 22.0,
        "debt_to_ebitda": 1.1,
        "interest_coverage": 12.0,
        "current_ratio": 1.8,
        "shares_outstanding": None,
        "valuation_pe": None,
        "valuation_ev_ebitda": None,
    }


class EnsureMetricRowsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(bind=self.engine)
        self.db = Session()
        self.company = Company(ticker="TST", name="Test Co")
        self.db.add(self.company)
        self.db.commit()
        self.db.refresh(self.company)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_empty_sec_response_refuses_cached_metrics(self):
        self.db.add(
            FinancialMetric(
                company_id=self.company.id,
                **_metric_payload(fiscal_year=2021, revenue=100.0),
            )
        )
        self.db.commit()

        with patch.object(recommendation_engine, "fetch_financial_metrics_last_3y", return_value=[]) as fetch:
            with self.assertRaisesRegex(ValueError, "Refusing to reuse cached metrics"):
                recommendation_engine._ensure_metric_rows(self.db, self.company)

        fetch.assert_called_once_with("TST")

    def test_fresh_sec_metrics_are_upserted_and_returned(self):
        self.db.add(
            FinancialMetric(
                company_id=self.company.id,
                **_metric_payload(fiscal_year=2022, revenue=100.0),
            )
        )
        self.db.commit()

        fresh_metrics = [
            _metric_payload(fiscal_year=2023, revenue=140.0),
            _metric_payload(fiscal_year=2022, revenue=120.0),
        ]
        with patch.object(recommendation_engine, "fetch_financial_metrics_last_3y", return_value=fresh_metrics):
            rows = recommendation_engine._ensure_metric_rows(self.db, self.company)

        self.assertEqual([row.fiscal_year for row in rows], [2023, 2022])
        self.assertEqual(rows[0].revenue, 140.0)
        self.assertEqual(rows[1].revenue, 120.0)
        self.assertEqual(self.db.query(FinancialMetric).count(), 2)


if __name__ == "__main__":
    unittest.main()
