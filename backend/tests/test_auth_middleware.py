import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi.testclient import TestClient

from app.config import settings
from app.main import _active_sessions, app


class AuthMiddlewareTests(unittest.TestCase):
    def setUp(self):
        self.previous_auth_enabled = settings.auth_enabled
        settings.auth_enabled = True
        _active_sessions.clear()
        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self):
        settings.auth_enabled = self.previous_auth_enabled
        _active_sessions.clear()

    def test_protected_api_without_session_returns_json_401(self):
        response = self.client.get("/api/opportunities/momentum")

        self.assertEqual(response.status_code, 401)
        self.assertTrue(response.headers["content-type"].startswith("application/json"))
        self.assertEqual(response.json(), {"detail": "Authentication required."})

    def test_browser_page_without_session_redirects_to_login(self):
        response = self.client.get("/dashboard", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")

    def test_health_routes_remain_public(self):
        response = self.client.get("/health/freshness")

        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
