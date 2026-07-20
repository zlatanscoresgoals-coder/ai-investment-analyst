import unittest

from app.analysis.financial_ratios import compute_financial_ratios
from app.valuation_math import _estimate_dist_growth, _historical_fcf_growth_pct


class CagrYearSpanTests(unittest.TestCase):
    def test_financial_ratios_fcf_cagr_uses_fiscal_year_span(self) -> None:
        ratios = compute_financial_ratios(
            {"revenue": 144.0},
            prior_metrics={"revenue": 120.0},
            trend_rows=[
                {"fiscal_year": 2022, "fcf": 100.0},
                {"fiscal_year": 2023, "fcf": None},
                {"fiscal_year": 2024, "fcf": 144.0},
            ],
        )

        self.assertAlmostEqual(ratios["fcf_cagr_pct"], 20.0)

    def test_valuation_fcf_growth_uses_fiscal_year_span(self) -> None:
        growth = _historical_fcf_growth_pct(
            [
                {"fiscal_year": 2022, "fcf": 100.0},
                {"fiscal_year": 2023, "fcf": None},
                {"fiscal_year": 2024, "fcf": 144.0},
            ]
        )

        self.assertEqual(growth, 20.0)

    def test_distribution_growth_uses_fiscal_year_span(self) -> None:
        growth = _estimate_dist_growth(
            [
                {"fiscal_year": 2022, "distributions": 100.0},
                {"fiscal_year": 2023, "distributions": None},
                {"fiscal_year": 2024, "distributions": 144.0},
            ]
        )

        self.assertEqual(growth, 20.0)


if __name__ == "__main__":
    unittest.main()
