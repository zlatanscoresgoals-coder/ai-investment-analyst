import unittest

from app.scoring.personas import score_ackman, score_burry


class PersonaInterestCoverageTests(unittest.TestCase):
    def test_missing_interest_coverage_is_neutral_for_ackman(self):
        metrics = {
            "operating_margin": 18.0,
            "roic": 12.0,
            "interest_coverage": None,
        }

        without_coverage = score_ackman(metrics)
        zero_coverage = score_ackman({**metrics, "interest_coverage": 0.0})

        self.assertGreater(without_coverage, zero_coverage)
        self.assertEqual(without_coverage, score_ackman({k: v for k, v in metrics.items() if k != "interest_coverage"}))

    def test_missing_interest_coverage_is_neutral_for_burry(self):
        metrics = {
            "current_ratio": 1.8,
            "debt_to_ebitda": 0.4,
            "valuation_pe": 15.0,
            "interest_coverage": None,
        }

        without_coverage = score_burry(metrics)
        zero_coverage = score_burry({**metrics, "interest_coverage": 0.0})

        self.assertGreater(without_coverage, zero_coverage)
        self.assertEqual(without_coverage, score_burry({k: v for k, v in metrics.items() if k != "interest_coverage"}))


if __name__ == "__main__":
    unittest.main()
