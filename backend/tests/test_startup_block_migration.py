import importlib
import os
import tempfile
import unittest


class StartupBlockMigrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["DATABASE_URL"] = f"sqlite:///{self.tmp.name}/test.db"
        os.environ["AUTO_REFRESH_ENABLED"] = "false"
        self.main = importlib.import_module("app.main")
        self.main.Base.metadata.create_all(bind=self.main.engine)

    def tearDown(self):
        self.tmp.cleanup()

    def _company(self, db, ticker: str):
        company = self.main.Company(ticker=ticker, name=ticker)
        db.add(company)
        db.commit()
        db.refresh(company)
        return company

    def _blocked_rec(self, db, company, *, summary: str, risk_json=None):
        rec = self.main.Recommendation(
            company_id=company.id,
            status="blocked",
            final_score=80.0,
            summary=summary,
            risk_json=risk_json or {},
            horizon="12-36 months",
        )
        db.add(rec)
        db.commit()
        db.refresh(rec)
        return rec

    def test_startup_preserves_active_or_manual_blocks(self):
        db = self.main.SessionLocal()
        try:
            stale_auto = self._company(db, "STALE")
            confirmed = self._company(db, "CONF")
            manual = self._company(db, "MANUAL")

            stale_rec = self._blocked_rec(
                db,
                stale_auto,
                summary="Blocked by critical risk gate due to bankruptcy signal.",
                risk_json={"critical_event": {"event_type": "bankruptcy"}},
            )
            confirmed_rec = self._blocked_rec(
                db,
                confirmed,
                summary="Blocked by critical risk gate due to bankruptcy signal.",
                risk_json={"critical_event": {"event_type": "bankruptcy"}},
            )
            manual_rec = self._blocked_rec(db, manual, summary="Manually blocked by risk review.")

            db.add(
                self.main.CriticalAlert(
                    company_id=confirmed.id,
                    event_type="bankruptcy",
                    severity="critical",
                    source="sec_8k",
                    headline="Confirmed critical event",
                    details_json={"workflow_status": "confirmed"},
                )
            )
            db.commit()
            rec_ids = (stale_rec.id, confirmed_rec.id, manual_rec.id)
        finally:
            db.close()

        self.main.on_startup()

        db = self.main.SessionLocal()
        try:
            statuses = {
                rec.id: rec.status
                for rec in db.query(self.main.Recommendation)
                .filter(self.main.Recommendation.id.in_(rec_ids))
                .all()
            }
            stale_id, confirmed_id, manual_id = rec_ids
            self.assertEqual(statuses[stale_id], "watchlist")
            self.assertEqual(statuses[confirmed_id], "blocked")
            self.assertEqual(statuses[manual_id], "blocked")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
