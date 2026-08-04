import os
import tempfile
import unittest
from pathlib import Path

from app.config import Settings


class SettingsTest(unittest.TestCase):
    def test_default_sqlite_database_url_is_stable_across_cwd_changes(self):
        backend_dir = Path(__file__).resolve().parents[1]
        expected = f"sqlite:///{(backend_dir / 'investment_analyst.db').as_posix()}"

        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                os.chdir(tmpdir)
                settings_from_tmp = Settings(_env_file=None)
            finally:
                os.chdir(original_cwd)

        settings_from_repo = Settings(_env_file=None)

        self.assertEqual(settings_from_tmp.database_url, expected)
        self.assertEqual(settings_from_repo.database_url, expected)


if __name__ == "__main__":
    unittest.main()
