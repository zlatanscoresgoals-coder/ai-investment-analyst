import unittest

from app.opportunities.earnings import _assign_flag


class EarningsFlagTests(unittest.TestCase):
    def test_missing_meridian_score_cannot_receive_green_flag(self):
        item = {
            "ticker": "BAC",
            "beats": 3,
            "misses": 0,
            "total_quarters": 3,
            "days_until": 7,
        }

        flagged = _assign_flag(item, meridian_scores={})

        self.assertEqual(flagged["flag"], "amber")
        self.assertEqual(flagged["flag_label"], "Monitor")
        self.assertIsNone(flagged["meridian_score"])
        self.assertNotIn("setup", flagged)

    def test_high_meridian_score_with_consistent_beats_receives_green_flag(self):
        item = {
            "ticker": "AAPL",
            "beats": 3,
            "misses": 0,
            "total_quarters": 3,
            "days_until": 7,
        }

        flagged = _assign_flag(item, meridian_scores={"AAPL": 72.4})

        self.assertEqual(flagged["flag"], "green")
        self.assertEqual(flagged["meridian_score"], 72.4)
        self.assertIn("setup", flagged)


if __name__ == "__main__":
    unittest.main()
