import unittest

from app.scoring.personas import score_buffett


class BuffettScoringTests(unittest.TestCase):
    def _quality_metrics(self, fcf):
        return {
            "revenue": 100.0,
            "gross_margin": 60.0,
            "roic": 20.0,
            "debt_to_ebitda": 1.0,
            "fcf": fcf,
        }

    def test_missing_fcf_is_not_scored_as_zero_margin(self):
        missing_fcf_score = score_buffett(self._quality_metrics(None), sector="Technology")
        zero_fcf_score = score_buffett(self._quality_metrics(0.0), sector="Technology")

        self.assertAlmostEqual(missing_fcf_score - zero_fcf_score, 10.0)


if __name__ == "__main__":
    unittest.main()
