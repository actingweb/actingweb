"""Tests that token-exchange error logs never leak sensitive fields."""

import logging
from unittest.mock import MagicMock, patch

from actingweb.config import Config
from actingweb.oauth2 import (
    GoogleOAuth2Provider,
    OAuth2Authenticator,
    _redact_token_response,
)

SENSITIVE = ["client_assertion", "assertion", "id_token", "client_secret"]


class TestRedactTokenResponse:
    def test_redacts_json_fields(self) -> None:
        body = (
            '{"error":"invalid_grant","client_secret":"SUPERSECRETJWT",'
            '"id_token":"eyLEAK","assertion":"AAAA","client_assertion":"BBBB"}'
        )
        out = _redact_token_response(body)
        assert "SUPERSECRETJWT" not in out
        assert "eyLEAK" not in out
        assert "AAAA" not in out
        assert "BBBB" not in out
        assert "<redacted>" in out
        # Non-sensitive content preserved.
        assert "invalid_grant" in out

    def test_redacts_form_fields(self) -> None:
        body = "error=invalid_grant&client_secret=SECRETVAL&assertion=ASSERTVAL"
        out = _redact_token_response(body)
        assert "SECRETVAL" not in out
        assert "ASSERTVAL" not in out
        assert "invalid_grant" in out

    def test_truncates(self) -> None:
        out = _redact_token_response("x" * 5000, limit=500)
        assert len(out) <= 500

    def test_empty(self) -> None:
        assert _redact_token_response("") == ""


class TestTokenExchangeErrorLogging:
    def test_failed_exchange_does_not_log_secrets(self, caplog) -> None:
        config = Config(fqdn="test.example.com", database="dynamodb")
        config.oauth = {"client_id": "cid", "client_secret": "csec"}
        auth = OAuth2Authenticator(config, GoogleOAuth2Provider(config))

        leaky_body = (
            '{"error":"invalid_client","client_secret":"LEAK_SECRET_123",'
            '"id_token":"LEAK_IDTOKEN_456"}'
        )
        with patch("actingweb.oauth2.requests.post") as mock_post:
            resp = MagicMock()
            resp.status_code = 400
            resp.text = leaky_body
            mock_post.return_value = resp
            with caplog.at_level(logging.ERROR, logger="actingweb.oauth2"):
                result = auth.exchange_code_for_token(code="abc")

        assert result is None
        joined = " ".join(r.getMessage() for r in caplog.records)
        assert "LEAK_SECRET_123" not in joined
        assert "LEAK_IDTOKEN_456" not in joined
