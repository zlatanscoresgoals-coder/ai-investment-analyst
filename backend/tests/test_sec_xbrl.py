import unittest

from app.ingestion.sec_xbrl import shares_outstanding_for_fy


def _shares_fact(tag: str, value: float, fy: int = 2024) -> dict:
    return {
        tag: {
            "units": {
                "shares": [
                    {
                        "form": "10-K",
                        "fp": "FY",
                        "start": f"{fy}-01-01",
                        "end": f"{fy}-12-31",
                        "filed": f"{fy + 1}-02-15",
                        "val": value,
                    }
                ]
            }
        }
    }


class SharesOutstandingForFyTests(unittest.TestCase):
    def test_prefers_weighted_average_diluted_shares(self):
        facts = {
            **_shares_fact("WeightedAverageNumberOfDilutedSharesOutstanding", 90.0),
            **_shares_fact("CommonStockSharesOutstanding", 80.0),
        }

        self.assertEqual(shares_outstanding_for_fy(facts, 2024), 90.0)

    def test_uses_period_end_outstanding_before_issued(self):
        facts = {
            **_shares_fact("CommonStockSharesOutstanding", 80.0),
            **_shares_fact("CommonStockSharesIssued", 100.0),
            **_shares_fact("TreasuryStockShares", 25.0),
        }

        self.assertEqual(shares_outstanding_for_fy(facts, 2024), 80.0)

    def test_derives_outstanding_from_issued_less_treasury(self):
        facts = {
            **_shares_fact("CommonStockSharesIssued", 100.0),
            **_shares_fact("TreasuryStockShares", 25.0),
        }

        self.assertEqual(shares_outstanding_for_fy(facts, 2024), 75.0)

    def test_does_not_treat_issued_as_outstanding_without_treasury(self):
        facts = _shares_fact("CommonStockSharesIssued", 100.0)

        self.assertIsNone(shares_outstanding_for_fy(facts, 2024))


if __name__ == "__main__":
    unittest.main()
