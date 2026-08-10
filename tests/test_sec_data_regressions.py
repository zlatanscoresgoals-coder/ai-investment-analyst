import os
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.db import Base
from app.main import _merge_sec_companyfacts_into_key_financials, _store_filings_and_metrics
from app.models import Company, FinancialMetric


class SecIngestMetricsTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()

    def _company(self) -> Company:
        company = Company(ticker="TST", name="Test Co")
        self.db.add(company)
        self.db.commit()
        self.db.refresh(company)
        return company

    def test_store_filings_and_metrics_persists_sec_metric_rows(self):
        company = self._company()

        with (
            patch("app.main.get_submission_json_for_ticker", return_value={"cik": "0000000000"}),
            patch("app.main.merge_sec_company_profile", return_value=False),
            patch(
                "app.main.build_10k_list_from_submission",
                return_value=[
                    {
                        "fiscal_year": 2024,
                        "filing_type": "10-K",
                        "filing_date": date(2025, 2, 1),
                        "source": "sec",
                        "url": "https://www.sec.gov/test-10k",
                    }
                ],
            ),
            patch(
                "app.main.fetch_financial_metrics_last_3y",
                return_value=[
                    {
                        "fiscal_year": 2024,
                        "revenue": 123.0,
                        "gross_margin": 45.0,
                        "operating_margin": 20.0,
                    }
                ],
            ),
        ):
            filing_count, metric_count, used_fallback = _store_filings_and_metrics(self.db, company)

        metric = self.db.query(FinancialMetric).filter_by(company_id=company.id, fiscal_year=2024).one()
        self.assertEqual(filing_count, 1)
        self.assertEqual(metric_count, 1)
        self.assertFalse(used_fallback)
        self.assertEqual(metric.revenue, 123.0)
        self.assertEqual(metric.gross_margin, 45.0)

    def test_store_filings_and_metrics_does_not_overwrite_existing_values_with_none(self):
        company = self._company()
        self.db.add(FinancialMetric(company_id=company.id, fiscal_year=2024, revenue=100.0, gross_margin=40.0))
        self.db.commit()

        with (
            patch("app.main.get_submission_json_for_ticker", return_value={"cik": "0000000000"}),
            patch("app.main.merge_sec_company_profile", return_value=False),
            patch("app.main.build_10k_list_from_submission", return_value=[]),
            patch("app.main.fetch_ir_filing_fallback_urls", return_value=[]),
            patch(
                "app.main.fetch_financial_metrics_last_3y",
                return_value=[{"fiscal_year": 2024, "revenue": None, "gross_margin": 42.0}],
            ),
        ):
            _store_filings_and_metrics(self.db, company)

        metric = self.db.query(FinancialMetric).filter_by(company_id=company.id, fiscal_year=2024).one()
        self.assertEqual(metric.revenue, 100.0)
        self.assertEqual(metric.gross_margin, 42.0)


class RevenueGrowthEnrichmentTests(unittest.TestCase):
    def test_revenue_growth_uses_revenue_history_not_net_income_history(self):
        key_financials = {}
        sec_inputs = {
            "revenue": 1200.0,
            "historical_window": [
                {"fiscal_year": 2023, "revenue": 1000.0, "net_income": 100.0},
                {"fiscal_year": 2024, "revenue": 1200.0, "net_income": 50.0},
            ],
        }

        _merge_sec_companyfacts_into_key_financials(key_financials, sec_inputs)

        self.assertEqual(key_financials["revenue"], 1200.0)
        self.assertEqual(key_financials["revenue_growth_pct"], 20.0)

    def test_revenue_growth_is_not_filled_from_net_income_when_revenue_history_is_missing(self):
        key_financials = {}
        sec_inputs = {
            "historical_window": [
                {"fiscal_year": 2023, "net_income": 100.0},
                {"fiscal_year": 2024, "net_income": 50.0},
            ],
        }

        _merge_sec_companyfacts_into_key_financials(key_financials, sec_inputs)

        self.assertNotIn("revenue_growth_pct", key_financials)


if __name__ == "__main__":
    unittest.main()
