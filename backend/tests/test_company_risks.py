import unittest

from app.risk.company_risks import preserve_persisted_risk_gate_metadata


class PreserveRiskGateMetadataTest(unittest.TestCase):
    def test_preserves_critical_gate_fields_on_live_risk_payload(self):
        live = {"risk_items": [], "overall_risk_level": "LOW"}
        persisted = {
            "critical_event": {"event_type": "bankruptcy", "headline": "Company files Chapter 11"},
            "critical_gate_cleared_at": "2026-09-22T11:00:00+00:00",
            "key_risks": ["stale persisted risk"],
        }

        merged = preserve_persisted_risk_gate_metadata(live, persisted)

        self.assertIs(merged, live)
        self.assertEqual(merged["critical_event"], persisted["critical_event"])
        self.assertEqual(merged["critical_gate_cleared_at"], persisted["critical_gate_cleared_at"])
        self.assertNotEqual(merged.get("key_risks"), persisted["key_risks"])

    def test_ignores_missing_persisted_risk_payload(self):
        live = {"risk_items": []}

        self.assertEqual(preserve_persisted_risk_gate_metadata(live, None), live)


if __name__ == "__main__":
    unittest.main()
