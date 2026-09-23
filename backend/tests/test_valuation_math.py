import unittest

from app.valuation_math import build_valuation_bundle


class BuildValuationBundleTests(unittest.TestCase):
    def test_zero_effective_tax_rate_is_preserved_in_wacc_default(self):
        bundle = build_valuation_bundle(
            ticker="ZERO",
            company_name="Zero Tax Corp",
            sector="industrial",
            industry=None,
            current_price=10.0,
            sec_inputs={
                "ok": True,
                "fiscal_year": 2025,
                "fcf": 100.0,
                "shares_outstanding": 100.0,
                "total_debt": 1000.0,
                "interest_expense": 100.0,
                "stockholders_equity": 1000.0,
                "effective_tax_rate_pct": 0.0,
                "historical_window": [],
            },
        )

        self.assertEqual(bundle["ggm"]["tax_rate_pct_default"], 0.0)
        self.assertEqual(bundle["defaults"]["wacc"], 12.07)


if __name__ == "__main__":
    unittest.main()
