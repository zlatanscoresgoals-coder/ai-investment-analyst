import unittest
from unittest.mock import patch

from app.ingestion.sec_filings import build_10k_list_from_submission


class Build10KListFromSubmissionTests(unittest.TestCase):
    def test_uses_report_date_when_filing_date_is_missing(self):
        submission = {
            "cik": "0000320193",
            "filings": {
                "recent": {
                    "form": ["10-K"],
                    "filingDate": [None],
                    "reportDate": ["2024-12-31"],
                    "accessionNumber": ["0000320193-25-000008"],
                    "primaryDocument": ["aapl-20241231.htm"],
                }
            },
        }

        with patch("app.ingestion.sec_filings._get_text", return_value="filing text"):
            rows = build_10k_list_from_submission(submission)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["fiscal_year"], 2024)
        self.assertEqual(rows[0]["filing_date"].isoformat(), "2024-12-31")
        self.assertEqual(rows[0]["raw_text"], "filing text")


if __name__ == "__main__":
    unittest.main()
