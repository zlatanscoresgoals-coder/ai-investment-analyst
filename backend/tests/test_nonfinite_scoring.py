import math
import unittest

from app.recommendations.ranking import composite_leaderboard_score
from app.scoring.blender import score_all


class NonFiniteScoringTests(unittest.TestCase):
    def test_nonfinite_metrics_do_not_receive_artificial_high_scores(self):
        metrics = {
            "revenue": math.nan,
            "gross_margin": math.nan,
            "operating_margin": math.nan,
            "net_margin": math.nan,
            "fcf": math.nan,
            "roic": math.nan,
            "roe": math.nan,
            "debt_to_ebitda": math.nan,
            "interest_coverage": math.nan,
            "current_ratio": math.nan,
            "valuation_pe": math.nan,
            "revenue_growth_pct": math.nan,
            "gross_margin_trend": math.nan,
            "fcf_cagr_pct": math.nan,
            "operating_margin_trend": math.nan,
            "roe_trend": math.nan,
            "debt_trend": math.nan,
        }

        scores = score_all(metrics)

        for value in scores.values():
            self.assertTrue(math.isfinite(value))
        self.assertLess(scores["final_score"], 50.0)

    def test_nonfinite_final_score_does_not_rank_as_perfect(self):
        self.assertEqual(composite_leaderboard_score(math.nan, None), 0.0)
        self.assertEqual(composite_leaderboard_score(math.inf, None), 0.0)

    def test_nonfinite_news_risk_uses_neutral_risk(self):
        self.assertEqual(composite_leaderboard_score(84.0, math.inf), 84.0)


if __name__ == "__main__":
    unittest.main()
