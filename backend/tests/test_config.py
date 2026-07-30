import unittest

from app.config import Settings


class SettingsTests(unittest.TestCase):
    def test_normalizes_legacy_postgres_database_url(self):
        settings = Settings(database_url="postgres://user:pass@example.com:5432/appdb")

        self.assertEqual(
            settings.database_url,
            "postgresql+psycopg2://user:pass@example.com:5432/appdb",
        )

    def test_preserves_supported_database_url_scheme(self):
        settings = Settings(database_url="postgresql://user:pass@example.com:5432/appdb")

        self.assertEqual(settings.database_url, "postgresql://user:pass@example.com:5432/appdb")


if __name__ == "__main__":
    unittest.main()
