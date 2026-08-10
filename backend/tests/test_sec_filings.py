import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion.sec_filings import SEC_COMPANYFACTS_URL, SEC_TICKER_URL, fetch_financial_metrics_last_3y


def _annual_fact(value: float, year: int) -> dict:
    return {
        "units": {
            "USD": [
                {
                    "form": "10-K",
                    "fp": "FY",
                    "start": f"{year}-01-01",
                    "end": f"{year}-12-31",
                    "filed": f"{year + 1}-02-01",
                    "val": value,
                }
            ]
        }
    }


def _companyfacts(us_gaap: dict) -> dict:
    return {"facts": {"us-gaap": us_gaap}}


class FetchFinancialMetricsTests(unittest.TestCase):
    def _fetch_with_us_gaap(self, us_gaap: dict) -> list[dict]:
        def fake_get_json(url: str) -> dict:
            if url == SEC_TICKER_URL:
                return {"0": {"ticker": "TST", "cik_str": 1234567}}
            if url == SEC_COMPANYFACTS_URL.format(cik="0001234567"):
                return _companyfacts(us_gaap)
            raise AssertionError(f"unexpected URL {url}")

        with patch("app.ingestion.sec_filings._get_json", side_effect=fake_get_json):
            return fetch_financial_metrics_last_3y("TST")

    def test_derives_gross_margin_from_cost_of_goods_when_gross_profit_missing(self) -> None:
        rows = self._fetch_with_us_gaap(
            {
                "RevenueFromContractWithCustomerExcludingAssessedTax": _annual_fact(1000.0, 2024),
                "CostOfGoodsAndServicesSold": _annual_fact(375.0, 2024),
            }
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["fiscal_year"], 2024)
        self.assertEqual(rows[0]["gross_margin"], 62.5)

    def test_prefers_reported_gross_profit_over_derived_cost_fallback(self) -> None:
        rows = self._fetch_with_us_gaap(
            {
                "RevenueFromContractWithCustomerExcludingAssessedTax": _annual_fact(1000.0, 2024),
                "GrossProfit": _annual_fact(700.0, 2024),
                "CostOfRevenue": _annual_fact(375.0, 2024),
            }
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["gross_margin"], 70.0)


if __name__ == "__main__":
    unittest.main()
