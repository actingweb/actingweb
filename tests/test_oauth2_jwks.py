"""Tests for the JWKS fetch + cache module (actingweb.oauth2_jwks)."""

import time
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from actingweb import oauth2_jwks


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    oauth2_jwks._reset_cache()
    yield
    oauth2_jwks._reset_cache()


def _jwks(*kids: str) -> dict:
    return {"keys": [{"kid": k, "kty": "RSA", "n": "x", "e": "AQAB"} for k in kids]}


def _resp(status: int, body: dict | None) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body
    return r


class TestFetchJwks:
    def test_fetch_success_and_cache_hit(self) -> None:
        with patch("actingweb.oauth2_jwks.requests.get") as mock_get:
            mock_get.return_value = _resp(200, _jwks("a"))
            first = oauth2_jwks.fetch_jwks("https://idp/keys")
            second = oauth2_jwks.fetch_jwks("https://idp/keys")
        assert first is not None and "keys" in first
        assert second == first
        # Only one network call — second served from cache.
        assert mock_get.call_count == 1

    def test_positive_ttl_expiry_refetches(self) -> None:
        with patch("actingweb.oauth2_jwks.requests.get") as mock_get:
            mock_get.return_value = _resp(200, _jwks("a"))
            oauth2_jwks.fetch_jwks("https://idp/keys")
            # Force the cached entry to look old.
            ts, jwks = oauth2_jwks._JWKS_CACHE["https://idp/keys"]
            oauth2_jwks._JWKS_CACHE["https://idp/keys"] = (
                ts - oauth2_jwks.JWKS_POSITIVE_TTL - 1,
                jwks,
            )
            oauth2_jwks.fetch_jwks("https://idp/keys")
        assert mock_get.call_count == 2

    def test_negative_cache_suppresses_refetch(self) -> None:
        with patch("actingweb.oauth2_jwks.requests.get") as mock_get:
            mock_get.return_value = _resp(500, None)
            first = oauth2_jwks.fetch_jwks("https://idp/keys")
            second = oauth2_jwks.fetch_jwks("https://idp/keys")
        assert first is None
        assert second is None
        # Second call suppressed by negative cache.
        assert mock_get.call_count == 1

    def test_negative_cache_expiry_allows_retry(self) -> None:
        with patch("actingweb.oauth2_jwks.requests.get") as mock_get:
            mock_get.return_value = _resp(500, None)
            oauth2_jwks.fetch_jwks("https://idp/keys")
            oauth2_jwks._JWKS_NEGATIVE_CACHE["https://idp/keys"] = (
                time.time() - oauth2_jwks.JWKS_NEGATIVE_TTL - 1
            )
            oauth2_jwks.fetch_jwks("https://idp/keys")
        assert mock_get.call_count == 2

    def test_fetch_failure_returns_stale_cache(self) -> None:
        with patch("actingweb.oauth2_jwks.requests.get") as mock_get:
            mock_get.return_value = _resp(200, _jwks("a"))
            oauth2_jwks.fetch_jwks("https://idp/keys")
            # Now force a refetch that fails — stale cache should be returned.
            mock_get.return_value = _resp(503, None)
            result = oauth2_jwks.fetch_jwks("https://idp/keys", force=True)
        assert result is not None
        assert result["keys"][0]["kid"] == "a"

    def test_missing_keys_field_is_failure(self) -> None:
        with patch("actingweb.oauth2_jwks.requests.get") as mock_get:
            mock_get.return_value = _resp(200, {"not_keys": []})
            assert oauth2_jwks.fetch_jwks("https://idp/keys") is None


class TestGetKeyForKid:
    def test_kid_hit(self) -> None:
        with patch("actingweb.oauth2_jwks.requests.get") as mock_get:
            mock_get.return_value = _resp(200, _jwks("a", "b"))
            key = oauth2_jwks.get_key_for_kid("https://idp/keys", "b")
        assert key is not None
        assert key["kid"] == "b"

    def test_kid_miss_forces_refetch(self) -> None:
        with patch("actingweb.oauth2_jwks.requests.get") as mock_get:
            # First fetch returns only "a"; after rotation includes "b".
            mock_get.side_effect = [
                _resp(200, _jwks("a")),
                _resp(200, _jwks("a", "b")),
            ]
            key = oauth2_jwks.get_key_for_kid("https://idp/keys", "b")
        assert key is not None
        assert key["kid"] == "b"
        assert mock_get.call_count == 2

    def test_kid_miss_after_refetch_returns_none(self) -> None:
        with patch("actingweb.oauth2_jwks.requests.get") as mock_get:
            mock_get.return_value = _resp(200, _jwks("a"))
            key = oauth2_jwks.get_key_for_kid("https://idp/keys", "zzz")
        assert key is None

    def test_force_refetch_debounced(self) -> None:
        with patch("actingweb.oauth2_jwks.requests.get") as mock_get:
            mock_get.return_value = _resp(200, _jwks("a"))
            # Prime cache.
            oauth2_jwks.fetch_jwks("https://idp/keys")
            # Two consecutive kid-misses: the forced refetch is debounced so the
            # second miss does not trigger a third network call.
            oauth2_jwks.get_key_for_kid("https://idp/keys", "miss1")
            calls_after_first = mock_get.call_count
            oauth2_jwks.get_key_for_kid("https://idp/keys", "miss2")
        # The debounce prevents a second forced refetch within the window.
        assert mock_get.call_count == calls_after_first
