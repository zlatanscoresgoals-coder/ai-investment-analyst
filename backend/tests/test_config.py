import os
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.config import Settings


class SettingsDatabaseGuardTests(unittest.TestCase):
    def test_allows_sqlite_for_local_development(self) -> None:
        settings = Settings(app_env="dev", database_url="sqlite:///local.db", _env_file=None)

        self.assertEqual(settings.database_url, "sqlite:///local.db")

    def test_rejects_sqlite_for_production_app_env(self) -> None:
        with self.assertRaises(ValidationError) as raised:
            Settings(app_env="production", database_url="sqlite+pysqlite:///prod.db", _env_file=None)

        self.assertIn("DATABASE_URL must be set", str(raised.exception))

    def test_rejects_default_sqlite_on_railway(self) -> None:
        with patch.dict(os.environ, {"RAILWAY_ENVIRONMENT_NAME": "production"}, clear=True):
            with self.assertRaises(ValidationError) as raised:
                Settings(_env_file=None)

        self.assertIn("DATABASE_URL must be set", str(raised.exception))

    def test_allows_persistent_database_on_railway(self) -> None:
        env = {
            "RAILWAY_ENVIRONMENT_NAME": "production",
            "DATABASE_URL": "postgresql+psycopg2://user:pass@example.invalid/app",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)

        self.assertEqual(settings.database_url, env["DATABASE_URL"])


if __name__ == "__main__":
    unittest.main()
