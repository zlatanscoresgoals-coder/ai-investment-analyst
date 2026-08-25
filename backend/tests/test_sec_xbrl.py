import unittest

from app.ingestion.sec_xbrl import CAPEX_TAGS, waterfall_money


def _money_fact(value):
    return {
        "units": {
            "USD": [
                {
                    "form": "10-K",
                    "fp": "FY",
                    "start": "2025-01-01",
                    "end": "2025-12-31",
                    "filed": "2026-02-15",
                    "val": value,
                }
            ]
        }
    }


class CapexWaterfallTest(unittest.TestCase):
    def test_cash_other_productive_assets_precedes_accrued_capex_fallback(self):
        us_gaap = {
            "PaymentsToAcquireOtherProductiveAssets": _money_fact(17_000_000_000),
            "CapitalExpendituresIncurredButNotYetPaid": _money_fact(3_800_000_000),
        }

        self.assertLess(
            CAPEX_TAGS.index("PaymentsToAcquireOtherProductiveAssets"),
            CAPEX_TAGS.index("CapitalExpendituresIncurredButNotYetPaid"),
        )
        self.assertEqual(waterfall_money(us_gaap, CAPEX_TAGS, 2025), 17_000_000_000.0)


if __name__ == "__main__":
    unittest.main()
