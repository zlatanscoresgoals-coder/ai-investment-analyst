import time
import unittest

from app import main


class AuthSessionTests(unittest.TestCase):
    def setUp(self):
        main._active_sessions.clear()

    def tearDown(self):
        main._active_sessions.clear()

    def test_active_session_accepts_unexpired_token(self):
        now = time.monotonic()
        main._active_sessions["token"] = now - 10

        self.assertTrue(main._is_active_session("token", now=now))
        self.assertIn("token", main._active_sessions)

    def test_active_session_rejects_and_removes_expired_token(self):
        now = time.monotonic()
        main._active_sessions["token"] = now - main.AUTH_SESSION_MAX_AGE_SECONDS

        self.assertFalse(main._is_active_session("token", now=now))
        self.assertNotIn("token", main._active_sessions)

    def test_active_session_rejects_missing_token(self):
        self.assertFalse(main._is_active_session(""))
        self.assertFalse(main._is_active_session("unknown"))

    def test_logout_removes_session_token(self):
        class Request:
            cookies = {main.settings.auth_session_cookie: "token"}

        main._active_sessions["token"] = time.monotonic()

        main.logout(Request())

        self.assertNotIn("token", main._active_sessions)


if __name__ == "__main__":
    unittest.main()
