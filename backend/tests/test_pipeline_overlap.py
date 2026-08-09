import unittest
from unittest.mock import patch

from app.tasks import scheduler


class PipelineOverlapTests(unittest.TestCase):
    def tearDown(self):
        if scheduler._pipeline_lock.locked():
            scheduler._pipeline_lock.release()

    def test_execute_full_pipeline_skips_when_already_running(self):
        self.assertTrue(scheduler._pipeline_lock.acquire(blocking=False))

        result = scheduler.execute_full_pipeline(object(), pool="candidates")

        self.assertTrue(result["skipped"])
        self.assertEqual(result["analyzed"], 0)
        self.assertEqual(result["failures"], [])
        self.assertIn("already in progress", result["message"])

    def test_execute_full_pipeline_releases_lock_after_run(self):
        expected = {
            "message": "done",
            "analyzed": 1,
            "company_count": 1,
            "failures": [],
        }
        with patch.object(scheduler, "_execute_full_pipeline_unlocked", return_value=expected) as run:
            result = scheduler.execute_full_pipeline(object(), pool="all")

        self.assertEqual(result, expected)
        run.assert_called_once()
        self.assertFalse(scheduler._pipeline_lock.locked())


if __name__ == "__main__":
    unittest.main()
