import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion import sec_filings


def _annual_entry(value: float, year: int = 2024) -> dict:
    return {
        "form": "10-K",
        "fp": "FY",
        "start": f"{year}-01-01",
        "end": f"{year}-12-31",
        "filed": f"{year + 1}-02-01",
        "val": value,
    }


def _money_fact(value: float, year: int = 2024) -> dict:
    return {"units": {"USD": [_annual_entry(value, year)]}}


class SecFinancialMetricsTests(unittest.TestCase):
    def _fetch_metrics(self, us_gaap: dict) -> list[dict]:
        companyfacts = {"facts": {"us-gaap": us_gaap}}
        with (
            patch.object(sec_filings, "get_cik_for_ticker", return_value="0000320193"),
            patch.object(sec_filings, "_get_json", return_value=companyfacts),
        ):
            return sec_filings.fetch_financial_metrics_last_3y("AAPL")

    def test_roic_uses_cash_adjusted_invested_capital(self) -> None:
        us_gaap = {
            "RevenueFromContractWithCustomerExcludingAssessedTax": _money_fact(1_000.0),
            "OperatingIncomeLoss": _money_fact(100.0),
            "NetIncomeLoss": _money_fact(80.0),
            "GrossProfit": _money_fact(400.0),
            "NetCashProvidedByUsedInOperatingActivities": _money_fact(120.0),
            "PaymentsToAcquirePropertyPlantAndEquipment": _money_fact(20.0),
            "StockholdersEquity": _money_fact(200.0),
            "LongTermDebt": _money_fact(50.0),
            "ShortTermBorrowings": _money_fact(10.0),
            "CurrentPortionOfLongTermDebt": _money_fact(5.0),
            "CashAndCashEquivalentsAtCarryingValue": _money_fact(65.0),
            "AssetsCurrent": _money_fact(500.0),
            "LiabilitiesCurrent": _money_fact(100.0),
            "DepreciationDepletionAndAmortization": _money_fact(25.0),
        }

        metrics = self._fetch_metrics(us_gaap)

        self.assertEqual(1, len(metrics))
        expected_roic = (100.0 * 0.79) / (200.0 + 50.0 + 10.0 + 5.0 - 65.0) * 100.0
        self.assertTrue(math.isclose(metrics[0]["roic"], expected_roic))

    def test_roic_is_omitted_when_invested_capital_is_not_positive(self) -> None:
        us_gaap = {
            "RevenueFromContractWithCustomerExcludingAssessedTax": _money_fact(1_000.0),
            "OperatingIncomeLoss": _money_fact(100.0),
            "StockholdersEquity": _money_fact(20.0),
            "LongTermDebt": _money_fact(10.0),
            "CashAndCashEquivalentsAtCarryingValue": _money_fact(50.0),
        }

        metrics = self._fetch_metrics(us_gaap)

        self.assertEqual(1, len(metrics))
        self.assertIsNone(metrics[0]["roic"])


if __name__ == "__main__":
    unittest.main()
