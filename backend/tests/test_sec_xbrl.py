import unittest

from app.ingestion.sec_xbrl import total_debt_for_fy


def _money_fact(value: float, year: int = 2025) -> dict:
    return {
        "units": {
            "USD": [
                {
                    "form": "10-K",
                    "fp": "FY",
                    "start": f"{year}-01-01",
                    "end": f"{year}-12-31",
                    "filed": f"{year + 1}-02-15",
                    "val": value,
                }
            ]
        }
    }


class TotalDebtForFyTest(unittest.TestCase):
    def test_uses_debt_current_when_component_tags_are_missing(self) -> None:
        us_gaap = {"DebtCurrent": _money_fact(13_800_000_000.0)}

        lt, st, cur, total = total_debt_for_fy(us_gaap, 2025)

        self.assertIsNone(lt)
        self.assertEqual(st, 13_800_000_000.0)
        self.assertIsNone(cur)
        self.assertEqual(total, 13_800_000_000.0)

    def test_debt_current_does_not_double_count_explicit_components(self) -> None:
        us_gaap = {
            "LongTermDebtNoncurrent": _money_fact(1_000.0),
            "ShortTermDebt": _money_fact(100.0),
            "CurrentPortionOfLongTermDebt": _money_fact(50.0),
            "DebtCurrent": _money_fact(2_000.0),
        }

        lt, st, cur, total = total_debt_for_fy(us_gaap, 2025)

        self.assertEqual(lt, 1_000.0)
        self.assertEqual(st, 100.0)
        self.assertEqual(cur, 50.0)
        self.assertEqual(total, 1_150.0)


if __name__ == "__main__":
    unittest.main()
