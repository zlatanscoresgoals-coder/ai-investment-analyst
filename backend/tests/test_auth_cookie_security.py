from types import SimpleNamespace
import unittest

from app.main import _request_uses_https


def _request(headers=None, scheme="http"):
    return SimpleNamespace(headers=headers or {}, url=SimpleNamespace(scheme=scheme))


class AuthCookieSecurityTests(unittest.TestCase):
    def test_detects_direct_https_request(self):
        self.assertTrue(_request_uses_https(_request(scheme="https")))

    def test_detects_forwarded_proto_https(self):
        self.assertTrue(_request_uses_https(_request(headers={"x-forwarded-proto": "https"})))

    def test_detects_standard_forwarded_proto_https(self):
        self.assertTrue(_request_uses_https(_request(headers={"forwarded": "for=1.2.3.4;proto=https;host=example.com"})))

    def test_plain_http_is_not_secure(self):
        self.assertFalse(_request_uses_https(_request(scheme="http")))


if __name__ == "__main__":
    unittest.main()
