import os
import unittest
from unittest.mock import patch

from app.config import Settings


class SettingsBoolEnvTests(unittest.TestCase):
    def test_empty_bool_env_values_use_field_defaults(self):
        with patch.dict(
            os.environ,
            {
                "AUTH_ENABLED": "",
                "AUTO_REFRESH_ENABLED": "",
                "CRITICAL_NEWS_STRICT_OUTLETS": "",
            },
            clear=True,
        ):
            settings = Settings()

        self.assertFalse(settings.auth_enabled)
        self.assertTrue(settings.auto_refresh_enabled)
        self.assertTrue(settings.critical_news_strict_outlets)

    def test_non_empty_bool_env_values_still_parse(self):
        with patch.dict(
            os.environ,
            {
                "AUTH_ENABLED": "true",
                "AUTO_REFRESH_ENABLED": "false",
                "CRITICAL_NEWS_STRICT_OUTLETS": "0",
            },
            clear=True,
        ):
            settings = Settings()

        self.assertTrue(settings.auth_enabled)
        self.assertFalse(settings.auto_refresh_enabled)
        self.assertFalse(settings.critical_news_strict_outlets)


if __name__ == "__main__":
    unittest.main()
