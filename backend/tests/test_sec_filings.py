import unittest
from datetime import date
from unittest.mock import patch

from app.ingestion import sec_filings


class Build10KListFromSubmissionTests(unittest.TestCase):
    def test_skips_incomplete_recent_entries_without_crashing(self):
        submission = {
            "cik": "1234567",
            "filings": {
                "recent": {
                    "form": ["8-K", "10-K", "10-K"],
                    "filingDate": ["2026-01-05"],
                    "reportDate": ["2026-01-04"],
                    "accessionNumber": ["0001234567-26-000001"],
                    "primaryDocument": [],
                }
            },
        }

        with patch.object(sec_filings, "_get_text") as get_text:
            rows = sec_filings.build_10k_list_from_submission(submission)

        self.assertEqual(rows, [])
        get_text.assert_not_called()

    def test_builds_valid_10k_entries_from_aligned_recent_arrays(self):
        submission = {
            "cik": "1234567",
            "filings": {
                "recent": {
                    "form": ["10-Q", "10-K"],
                    "filingDate": ["2026-05-01", "2026-02-15"],
                    "reportDate": ["2026-03-31", "2025-12-31"],
                    "accessionNumber": ["0001234567-26-000010", "0001234567-26-000001"],
                    "primaryDocument": ["q1.htm", "annual.htm"],
                }
            },
        }

        with patch.object(sec_filings, "_get_text", return_value="filing body"):
            rows = sec_filings.build_10k_list_from_submission(submission)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["filing_type"], "10-K")
        self.assertEqual(rows[0]["fiscal_year"], 2025)
        self.assertEqual(rows[0]["filing_date"], date(2026, 2, 15))
        self.assertEqual(
            rows[0]["url"],
            "https://www.sec.gov/Archives/edgar/data/1234567/000123456726000001/annual.htm",
        )
        self.assertEqual(rows[0]["raw_text"], "filing body")


if __name__ == "__main__":
    unittest.main()
