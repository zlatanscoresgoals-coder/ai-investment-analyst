import unittest
from types import SimpleNamespace

from app.risk.company_risks import build_company_risk_json
from app.scoring.personas import _sector_key
from app.universe import resolve_sector_for_display


class SectorResolutionTests(unittest.TestCase):
    def test_universe_sector_preferred_over_sec_bucket(self):
        self.assertEqual(resolve_sector_for_display("AAPL", "Manufacturing"), "Technology")

    def test_non_universe_ticker_keeps_stored_sector(self):
        self.assertEqual(resolve_sector_for_display("ZZZ", "Manufacturing"), "Manufacturing")

    def test_basic_materials_not_classified_as_energy(self):
        self.assertNotEqual(_sector_key("Basic Materials"), "energy")

    def test_risk_json_uses_canonical_sector_specific_risks(self):
        latest = SimpleNamespace(
            debt_to_ebitda=None,
            interest_coverage=None,
            fcf=None,
            revenue=None,
            current_ratio=None,
            gross_margin=None,
            roe=None,
        )
        sector = resolve_sector_for_display("AAPL", "Manufacturing")
        risk_json = build_company_risk_json(
            company_name="Apple Inc.",
            ticker="AAPL",
            sector=sector,
            latest=latest,
            revenue_growth=0.0,
            trend_rows=[],
            keyword_counts={},
            news_rows=[],
        )

        self.assertEqual(risk_json["sector"], "Technology")
        self.assertTrue(
            any("AI regulation" in item["text"] for item in risk_json["risk_items"]),
            "Technology sector risks should be applied instead of generic SEC bucket risks.",
        )


if __name__ == "__main__":
    unittest.main()
