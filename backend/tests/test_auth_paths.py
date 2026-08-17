import unittest

from app.main import _is_auth_path


class AuthPathTests(unittest.TestCase):
    def test_expensive_quote_probe_is_not_public_health(self):
        self.assertFalse(_is_auth_path("/health/quote"))

    def test_static_health_diagnostics_remain_public(self):
        self.assertTrue(_is_auth_path("/health/freshness"))
        self.assertTrue(_is_auth_path("/health/features"))


if __name__ == "__main__":
    unittest.main()
