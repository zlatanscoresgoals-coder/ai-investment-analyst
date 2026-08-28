import unittest
from types import SimpleNamespace

from app.analysis.financial_ratios import compute_financial_ratios
from app.recommendations.engine import _adjacent_prior_metric_row
from app.scoring.personas import score_wood


class RevenueGrowthAdjacencyTests(unittest.TestCase):
    def test_non_adjacent_metric_row_is_not_prior_year(self):
        latest = SimpleNamespace(fiscal_year=2025)
        skipped_year = SimpleNamespace(fiscal_year=2023)

        self.assertIsNone(_adjacent_prior_metric_row([latest, skipped_year]))

    def test_adjacent_metric_row_is_used_as_prior_year(self):
        latest = SimpleNamespace(fiscal_year=2025)
        prior = SimpleNamespace(fiscal_year=2024)
        older = SimpleNamespace(fiscal_year=2023)

        self.assertIs(_adjacent_prior_metric_row([latest, prior, older]), prior)

    def test_growth_is_unknown_without_comparable_revenues(self):
        ratios = compute_financial_ratios({"revenue": 120.0}, prior_metrics=None)

        self.assertIsNone(ratios["revenue_growth_pct"])

    def test_growth_is_calculated_for_adjacent_comparable_revenues(self):
        ratios = compute_financial_ratios({"revenue": 120.0}, prior_metrics={"revenue": 100.0})

        self.assertEqual(ratios["revenue_growth_pct"], 20.0)

    def test_missing_growth_is_neutral_for_wood_score(self):
        missing_growth = score_wood({"revenue_growth_pct": None, "gross_margin": 45.0})
        zero_growth = score_wood({"revenue_growth_pct": 0.0, "gross_margin": 45.0})

        self.assertEqual(missing_growth, 35.0)
        self.assertEqual(zero_growth, 15.0)


if __name__ == "__main__":
    unittest.main()
