import unittest

from app.ingestion.sec_xbrl import total_debt_for_fy


def _money_fact(tag: str, fy: int, value: float) -> dict:
    return {
        tag: {
            "units": {
                "USD": [
                    {
                        "form": "10-K",
                        "fp": "FY",
                        "fy": fy,
                        "end": f"{fy}-12-31",
                        "filed": f"{fy + 1}-02-15",
                        "val": value,
                    }
                ]
            }
        }
    }


def _companyfacts(*facts: dict) -> dict:
    merged = {}
    for fact in facts:
        merged.update(fact)
    return merged


class TotalDebtForFiscalYearTests(unittest.TestCase):
    def test_long_term_debt_total_is_not_double_counted_with_current_portion(self):
        us_gaap = _companyfacts(
            _money_fact("LongTermDebt", 2024, 1_000.0),
            _money_fact("LongTermDebtNoncurrent", 2024, 800.0),
            _money_fact("LongTermDebtCurrent", 2024, 200.0),
            _money_fact("ShortTermBorrowings", 2024, 50.0),
        )

        lt, st, cur, total = total_debt_for_fy(us_gaap, 2024)

        self.assertEqual(lt, 800.0)
        self.assertEqual(st, 50.0)
        self.assertEqual(cur, 200.0)
        self.assertEqual(total, 1_050.0)

    def test_standard_current_maturities_tag_is_included_when_no_total_exists(self):
        us_gaap = _companyfacts(
            _money_fact("LongTermDebtNoncurrent", 2024, 800.0),
            _money_fact("LongTermDebtCurrent", 2024, 200.0),
        )

        lt, st, cur, total = total_debt_for_fy(us_gaap, 2024)

        self.assertEqual(lt, 800.0)
        self.assertIsNone(st)
        self.assertEqual(cur, 200.0)
        self.assertEqual(total, 1_000.0)

    def test_noncurrent_debt_is_derived_from_total_when_available(self):
        us_gaap = _companyfacts(
            _money_fact("LongTermDebt", 2024, 1_000.0),
            _money_fact("LongTermDebtCurrent", 2024, 200.0),
        )

        lt, st, cur, total = total_debt_for_fy(us_gaap, 2024)

        self.assertEqual(lt, 800.0)
        self.assertIsNone(st)
        self.assertEqual(cur, 200.0)
        self.assertEqual(total, 1_000.0)


if __name__ == "__main__":
    unittest.main()
