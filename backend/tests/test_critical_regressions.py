import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import Base, Company, FinancialMetric
from app.opportunities.momentum import scan_momentum
from app.recommendations.engine import _ensure_metric_rows
from app.scoring.personas import score_buffett, score_burry


class PersonaScoringTests(unittest.TestCase):
    def test_lower_debt_scores_higher_than_high_debt(self):
        base_metrics = {
            "revenue": 1_000_000_000.0,
            "gross_margin": 55.0,
            "fcf": 180_000_000.0,
            "roic": 18.0,
            "current_ratio": 2.0,
            "interest_coverage": 8.0,
        }

        low_debt = dict(base_metrics, debt_to_ebitda=0.5)
        high_debt = dict(base_metrics, debt_to_ebitda=4.0)

        self.assertGreater(score_buffett(low_debt), score_buffett(high_debt))
        self.assertGreater(score_burry(low_debt), score_burry(high_debt))

    def test_missing_debt_is_not_scored_as_zero_debt(self):
        base_metrics = {
            "revenue": 1_000_000_000.0,
            "gross_margin": 55.0,
            "fcf": 180_000_000.0,
            "roic": 18.0,
            "current_ratio": 2.0,
            "interest_coverage": 8.0,
        }

        missing_debt = dict(base_metrics)
        zero_debt = dict(base_metrics, debt_to_ebitda=0.0)

        self.assertGreater(score_buffett(zero_debt), score_buffett(missing_debt))
        self.assertGreater(score_burry(zero_debt), score_burry(missing_debt))

    def test_lower_pe_scores_higher_for_burry(self):
        base_metrics = {
            "current_ratio": 2.0,
            "debt_to_ebitda": 1.0,
            "interest_coverage": 8.0,
        }

        cheap = dict(base_metrics, valuation_pe=12.0)
        expensive = dict(base_metrics, valuation_pe=30.0)

        self.assertGreater(score_burry(cheap), score_burry(expensive))


class MomentumScannerTests(unittest.TestCase):
    def test_scan_momentum_handles_nan_rank_inputs(self):
        rows = {
            "AAA": {
                "ticker": "AAA",
                "name": "AAA Corp",
                "sector": "Technology",
                "current_price": 100.0,
                "ret_1m": 1.0,
                "ret_6m": math.nan,
                "ret_12m": 8.0,
                "high_52w": 105.0,
                "dist_high_pct": -4.0,
                "vol_ratio": math.nan,
                "vol_trend": "decreasing",
                "rsi": 55.0,
                "sparkline": [100.0] * 60,
            },
            "BBB": {
                "ticker": "BBB",
                "name": "BBB Corp",
                "sector": "Technology",
                "current_price": 50.0,
                "ret_1m": 2.0,
                "ret_6m": 12.0,
                "ret_12m": math.nan,
                "high_52w": 55.0,
                "dist_high_pct": -9.0,
                "vol_ratio": 1.2,
                "vol_trend": "increasing",
                "rsi": 60.0,
                "sparkline": [50.0] * 60,
            },
        }

        with patch("app.opportunities.momentum._fetch_single", side_effect=lambda ticker: rows[ticker]):
            results = scan_momentum(["AAA", "BBB"], top_n=2)

        self.assertEqual(len(results), 2)
        self.assertTrue(all(math.isfinite(row["momentum_score"]) for row in results))


class SecMetricUpsertTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)

    def test_existing_metric_values_survive_partial_sec_updates(self):
        db = self.Session()
        try:
            company = Company(ticker="TEST", name="Test Co")
            db.add(company)
            db.flush()
            db.add(
                FinancialMetric(
                    company_id=company.id,
                    fiscal_year=2024,
                    revenue=100.0,
                    gross_margin=45.0,
                    operating_margin=20.0,
                    fcf=10.0,
                )
            )
            db.commit()

            sec_rows = [
                {
                    "fiscal_year": 2024,
                    "revenue": 125.0,
                    "gross_margin": None,
                    "operating_margin": 22.0,
                    "fcf": None,
                }
            ]

            with patch("app.recommendations.engine.fetch_financial_metrics_last_3y", return_value=sec_rows):
                rows = _ensure_metric_rows(db, company)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].revenue, 125.0)
            self.assertEqual(rows[0].operating_margin, 22.0)
            self.assertEqual(rows[0].gross_margin, 45.0)
            self.assertEqual(rows[0].fcf, 10.0)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
