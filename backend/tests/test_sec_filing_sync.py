from datetime import date
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.ingestion.sec_filings import build_10k_list_from_submission, sync_annual_filings_for_company
from app.models import Company, Filing


class SecFilingSyncTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.company = Company(ticker="ACME", name="Acme Corp")
        self.db.add(self.company)
        self.db.commit()
        self.db.refresh(self.company)

    def tearDown(self):
        self.db.close()

    def test_build_10k_list_accepts_amended_annual_filings(self):
        submission = {
            "cik": "123",
            "filings": {
                "recent": {
                    "form": ["10-Q", "10-K/A"],
                    "filingDate": ["2026-05-01", "2026-03-15"],
                    "reportDate": ["2026-03-31", "2025-12-31"],
                    "accessionNumber": ["0000000000-26-000001", "0000000000-26-000002"],
                    "primaryDocument": ["q.htm", "k-a.htm"],
                }
            },
        }

        import app.ingestion.sec_filings as sec_filings

        original_get_text = sec_filings._get_text
        sec_filings._get_text = lambda _url: "amended annual filing text"
        try:
            filings = build_10k_list_from_submission(submission)
        finally:
            sec_filings._get_text = original_get_text

        self.assertEqual(1, len(filings))
        self.assertEqual(2025, filings[0]["fiscal_year"])
        self.assertEqual("amended annual filing text", filings[0]["raw_text"])
        self.assertIn("/123/000000000026000002/k-a.htm", filings[0]["url"])

    def test_sync_refreshes_empty_existing_filing_text(self):
        self.db.add(
            Filing(
                company_id=self.company.id,
                filing_type="10-K",
                filing_date=date(2026, 2, 1),
                fiscal_year=2025,
                source="sec",
                url="https://example.test/old.htm",
                raw_text="",
            )
        )
        self.db.commit()

        inserted, updated = sync_annual_filings_for_company(
            self.db,
            self.company,
            [
                {
                    "filing_type": "10-K",
                    "filing_date": date(2026, 2, 1),
                    "fiscal_year": 2025,
                    "source": "sec",
                    "url": "https://example.test/new.htm",
                    "raw_text": "full 10-k text with risk and debt",
                }
            ],
        )

        row = self.db.query(Filing).filter_by(company_id=self.company.id, fiscal_year=2025).one()
        self.assertEqual(0, inserted)
        self.assertEqual(1, updated)
        self.assertEqual("full 10-k text with risk and debt", row.raw_text)
        self.assertEqual("https://example.test/new.htm", row.url)

    def test_sync_replaces_older_original_with_newer_amendment_text(self):
        self.db.add(
            Filing(
                company_id=self.company.id,
                filing_type="10-K",
                filing_date=date(2026, 2, 1),
                fiscal_year=2025,
                source="sec",
                url="https://example.test/original.htm",
                raw_text="original text",
            )
        )
        self.db.commit()

        inserted, updated = sync_annual_filings_for_company(
            self.db,
            self.company,
            [
                {
                    "filing_type": "10-K",
                    "filing_date": date(2026, 3, 15),
                    "fiscal_year": 2025,
                    "source": "sec",
                    "url": "https://example.test/amended.htm",
                    "raw_text": "amended text with updated litigation risk",
                }
            ],
        )

        row = self.db.query(Filing).filter_by(company_id=self.company.id, fiscal_year=2025).one()
        self.assertEqual(0, inserted)
        self.assertEqual(1, updated)
        self.assertEqual(date(2026, 3, 15), row.filing_date)
        self.assertEqual("https://example.test/amended.htm", row.url)
        self.assertEqual("amended text with updated litigation risk", row.raw_text)


if __name__ == "__main__":
    unittest.main()
