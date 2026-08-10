import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.maintenance import purge_synthetic_fallback_financial_metrics
from app.models import Company, FinancialMetric


class SyntheticFallbackCleanupTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        self.Session = sessionmaker(bind=engine)

    def test_preserves_real_row_with_same_operating_margin(self):
        db = self.Session()
        try:
            company = Company(ticker="AAPL", name="Apple Inc.")
            db.add(company)
            db.flush()
            real_metric = FinancialMetric(
                company_id=company.id,
                fiscal_year=2025,
                revenue=391_035_000_000.0,
                gross_margin=46.2,
                operating_margin=25.0,
                net_margin=24.3,
                fcf=108_807_000_000.0,
                roic=31.5,
                roe=149.8,
                debt_to_ebitda=0.9,
                interest_coverage=29.4,
                current_ratio=0.87,
                valuation_pe=None,
                valuation_ev_ebitda=None,
            )
            db.add(real_metric)
            db.commit()

            deleted = purge_synthetic_fallback_financial_metrics(db)
            db.commit()

            self.assertEqual(deleted, 0)
            self.assertEqual(db.query(FinancialMetric).count(), 1)
        finally:
            db.close()

    def test_deletes_complete_legacy_synthetic_signature(self):
        db = self.Session()
        try:
            company = Company(ticker="AAPL", name="Apple Inc.")
            db.add(company)
            db.flush()
            synthetic_metric = FinancialMetric(
                company_id=company.id,
                fiscal_year=2024,
                revenue=383.3 * 1_000_000_000.0,
                gross_margin=42.0,
                operating_margin=25.0,
                net_margin=21.0,
                fcf=383.3 * 0.18 * 1_000_000_000.0,
                roic=18.0,
                roe=20.0,
                debt_to_ebitda=1.4,
                interest_coverage=9.0,
                current_ratio=1.6,
                shares_outstanding=None,
                valuation_pe=24.0,
                valuation_ev_ebitda=14.0,
            )
            db.add(synthetic_metric)
            db.commit()

            deleted = purge_synthetic_fallback_financial_metrics(db)
            db.commit()

            self.assertEqual(deleted, 1)
            self.assertEqual(db.query(FinancialMetric).count(), 0)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
