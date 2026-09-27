import unittest

from app.risk.company_risks import build_company_risk_json


def _risk_texts_for_headline(title: str) -> list[str]:
    result = build_company_risk_json(
        company_name="Example Corp",
        ticker="EXM",
        sector="Technology",
        latest=None,
        revenue_growth=0.0,
        trend_rows=[],
        keyword_counts={},
        news_rows=[{"title": title, "description": "", "url": "#", "source_name": "Test"}],
    )
    return [
        item["text"]
        for item in result["risk_items"]
        if item.get("category") == "News & Market"
    ]


class CompanyRiskHeadlineTests(unittest.TestCase):
    def test_keyword_boundaries_do_not_flag_benign_substrings(self) -> None:
        texts = _risk_texts_for_headline("Antifraud platform revenue grows 30%")

        self.assertFalse(any("fraud allegation" in text for text in texts))

    def test_negated_guidance_headline_does_not_create_high_risk(self) -> None:
        texts = _risk_texts_for_headline("Analysts say no guidance cut expected after investor day")

        self.assertFalse(any("earnings miss or guidance reduction" in text for text in texts))

    def test_real_class_action_headline_still_matches(self) -> None:
        texts = _risk_texts_for_headline("Example faces securities fraud class action")

        self.assertTrue(any("class-action" in text for text in texts))

    def test_resignation_inflection_still_matches(self) -> None:
        texts = _risk_texts_for_headline("Example CEO resigns unexpectedly")

        self.assertTrue(any("Senior management departure" in text for text in texts))


if __name__ == "__main__":
    unittest.main()
