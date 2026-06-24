import unittest

from app.analysis.financial_ratios import compute_financial_ratios


class ComputeFinancialRatiosTests(unittest.TestCase):
    def test_revenue_growth_uses_latest_and_prior_revenue(self):
        ratios = compute_financial_ratios(
            {"revenue": 125.0},
            prior_metrics={"revenue": 100.0},
        )

        self.assertEqual(ratios["revenue_growth_pct"], 25.0)

    def test_revenue_growth_defaults_when_latest_revenue_is_missing(self):
        ratios = compute_financial_ratios(
            {"revenue": None},
            prior_metrics={"revenue": 100.0},
        )

        self.assertEqual(ratios["revenue_growth_pct"], 0.0)

    def test_revenue_growth_defaults_when_prior_revenue_is_zero(self):
        ratios = compute_financial_ratios(
            {"revenue": 125.0},
            prior_metrics={"revenue": 0.0},
        )

        self.assertEqual(ratios["revenue_growth_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()
