import unittest

from app.scoring.personas import score_wood


class WoodScoringTests(unittest.TestCase):
    def test_wood_gross_margin_uses_sector_bands(self):
        metrics = {
            "revenue_growth_pct": 15.0,
            "gross_margin": 35.0,
            "fcf_cagr_pct": None,
        }

        tech_score = score_wood(metrics, sector="Technology")
        energy_score = score_wood(metrics, sector="Energy")

        self.assertGreater(energy_score, tech_score)


if __name__ == "__main__":
    unittest.main()
