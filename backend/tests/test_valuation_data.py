from unittest import TestCase
from unittest.mock import patch

from app.valuation_data import fetch_latest_valuation_inputs


def _money_fact(value: float, *, unit: str = "USD") -> dict:
    return {
        "units": {
            unit: [
                {
                    "form": "10-K",
                    "fp": "FY",
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                    "filed": "2024-02-01",
                    "val": value,
                }
            ]
        }
    }


def _companyfacts(*, depreciation: float | None = None, direct_ebitda: float | None = None) -> dict:
    us_gaap = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": _money_fact(1_000.0),
        "OperatingIncomeLoss": _money_fact(100.0),
    }
    if depreciation is not None:
        us_gaap["DepreciationDepletionAndAmortization"] = _money_fact(depreciation)
    if direct_ebitda is not None:
        us_gaap["EarningsBeforeInterestTaxesDepreciationAmortization"] = _money_fact(direct_ebitda)
    return {"facts": {"us-gaap": us_gaap}}


class ValuationDataEbitdaTests(TestCase):
    def _fetch(self, payload: dict) -> dict:
        with patch("app.valuation_data.get_cik_for_ticker", return_value="0000320193"), patch(
            "app.valuation_data._get_json", return_value=payload
        ):
            return fetch_latest_valuation_inputs("TEST")

    def test_missing_depreciation_does_not_substitute_operating_income_for_ebitda(self):
        out = self._fetch(_companyfacts())

        self.assertTrue(out["ok"])
        self.assertEqual(out["operating_income"], 100.0)
        self.assertIsNone(out["depreciation"])
        self.assertIsNone(out["ebitda"])

    def test_operating_income_plus_depreciation_derives_ebitda(self):
        out = self._fetch(_companyfacts(depreciation=25.0))

        self.assertEqual(out["operating_income"], 100.0)
        self.assertEqual(out["depreciation"], 25.0)
        self.assertEqual(out["ebitda"], 125.0)

    def test_direct_ebitda_tag_still_wins(self):
        out = self._fetch(_companyfacts(depreciation=25.0, direct_ebitda=150.0))

        self.assertEqual(out["ebitda"], 150.0)
