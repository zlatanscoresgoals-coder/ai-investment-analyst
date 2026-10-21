import unittest

from app.ingestion.sec_xbrl import BUYBACK_TAGS, waterfall_money


def _annual_fact(value):
    return {
        "form": "10-K",
        "fp": "FY",
        "start": "2024-01-01",
        "end": "2024-12-31",
        "filed": "2025-02-15",
        "val": value,
    }


class SecXbrlTests(unittest.TestCase):
    def test_buybacks_ignore_treasury_stock_balance_sheet_values(self):
        us_gaap = {
            "TreasuryStockValueAcquiredCostMethod": {
                "units": {"USD": [_annual_fact(25_000_000_000)]}
            }
        }

        self.assertIsNone(waterfall_money(us_gaap, BUYBACK_TAGS, 2024))

    def test_buybacks_read_cash_flow_repurchase_values(self):
        us_gaap = {
            "PaymentsForRepurchaseOfCommonStock": {
                "units": {"USD": [_annual_fact(-3_500_000_000)]}
            }
        }

        self.assertEqual(waterfall_money(us_gaap, BUYBACK_TAGS, 2024), -3_500_000_000.0)


if __name__ == "__main__":
    unittest.main()
