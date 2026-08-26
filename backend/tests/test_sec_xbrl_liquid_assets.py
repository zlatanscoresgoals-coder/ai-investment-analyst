import unittest

from app.ingestion.sec_xbrl import liquid_assets_for_fy


def _fact(value: float, *, end: str = "2025-12-31") -> dict:
    return {
        "units": {
            "USD": [
                {
                    "form": "10-K",
                    "fp": "FY",
                    "start": "2025-01-01",
                    "end": end,
                    "filed": "2026-02-01",
                    "val": value,
                }
            ]
        }
    }


class LiquidAssetsForFyTests(unittest.TestCase):
    def test_prefers_aggregate_without_double_counting_current_securities(self):
        us_gaap = {
            "CashCashEquivalentsAndShortTermInvestments": _fact(100.0),
            "CashAndCashEquivalentsAtCarryingValue": _fact(10.0),
            "MarketableSecuritiesCurrent": _fact(40.0),
            "MarketableSecuritiesNoncurrent": _fact(25.0),
        }

        self.assertEqual(liquid_assets_for_fy(us_gaap, 2025), 125.0)

    def test_sums_components_when_aggregate_is_absent(self):
        us_gaap = {
            "CashAndCashEquivalentsAtCarryingValue": _fact(10.0),
            "MarketableSecuritiesCurrent": _fact(40.0),
            "MarketableSecuritiesNoncurrent": _fact(25.0),
        }

        self.assertEqual(liquid_assets_for_fy(us_gaap, 2025), 75.0)

    def test_returns_none_when_no_liquid_asset_tags_exist(self):
        self.assertIsNone(liquid_assets_for_fy({}, 2025))


if __name__ == "__main__":
    unittest.main()
