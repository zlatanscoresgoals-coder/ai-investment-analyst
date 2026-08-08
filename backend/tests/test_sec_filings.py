import unittest
from unittest.mock import patch

from app.ingestion import sec_filings


class SecFilingLookupTests(unittest.TestCase):
    def test_xom_uses_primary_exxon_mobil_filer(self):
        with patch.object(sec_filings, "_get_json", side_effect=AssertionError("network should not be used")):
            self.assertEqual(sec_filings.get_cik_for_ticker(" xom "), "0000034088")

    def test_ticker_index_lookup_zero_pads_cik(self):
        payload = {
            "0": {"ticker": "MSFT", "cik_str": 789019, "title": "MICROSOFT CORP"},
        }
        with patch.object(sec_filings, "_get_json", return_value=payload):
            self.assertEqual(sec_filings.get_cik_for_ticker("msft"), "0000789019")


if __name__ == "__main__":
    unittest.main()
