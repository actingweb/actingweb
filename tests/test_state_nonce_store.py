"""Tests for StateNonceStore and AppleTicketStore (actingweb.oauth_state_store)."""

from unittest.mock import Mock

from actingweb.config import Config
from actingweb.oauth_state_store import (
    AppleTicketStore,
    StateNonceStore,
    looks_like_state_nonce,
)


def _make_config() -> Config:
    config = Mock(spec=Config)
    test_storage: dict = {}

    class MockDbAttribute:
        def __init__(self):  # type: ignore
            self.storage = test_storage

        def get_bucket(self, actor_id, bucket):  # type: ignore
            return self.storage.get(f"{actor_id}:{bucket}", {})

        def get_attr(self, actor_id, bucket, name):  # type: ignore
            return self.storage.get(f"{actor_id}:{bucket}", {}).get(name)

        def set_attr(
            self, actor_id, bucket, name, data, timestamp=None, ttl_seconds=None
        ):  # type: ignore
            key = f"{actor_id}:{bucket}"
            self.storage.setdefault(key, {})[name] = {
                "data": data,
                "timestamp": timestamp,
                "ttl_seconds": ttl_seconds,
            }
            return True

        def delete_attr(self, actor_id, bucket, name):  # type: ignore
            key = f"{actor_id}:{bucket}"
            if key in self.storage and name in self.storage[key]:
                del self.storage[key][name]
                return True
            return False

        def delete_bucket(self, actor_id, bucket):  # type: ignore
            return self.storage.pop(f"{actor_id}:{bucket}", None) is not None

    mock_db_module = Mock()
    mock_db_module.DbAttribute = MockDbAttribute
    config.DbAttribute = mock_db_module
    return config


class TestStateNonceStore:
    def test_create_returns_opaque_nonce(self) -> None:
        store = StateNonceStore(_make_config())
        nonce = store.create({"provider": "apple", "csrf": "x"})
        assert isinstance(nonce, str)
        assert len(nonce) > 20
        assert "{" not in nonce

    def test_consume_returns_payload(self) -> None:
        store = StateNonceStore(_make_config())
        payload = {"provider": "apple", "redirect_url": "https://app/x", "n": 1}
        nonce = store.create(payload)
        assert store.consume(nonce) == payload

    def test_consume_is_single_use(self) -> None:
        store = StateNonceStore(_make_config())
        nonce = store.create({"provider": "apple"})
        assert store.consume(nonce) is not None
        assert store.consume(nonce) is None  # replay rejected

    def test_consume_unknown_returns_none(self) -> None:
        store = StateNonceStore(_make_config())
        assert store.consume("does-not-exist") is None

    def test_consume_empty_returns_none(self) -> None:
        store = StateNonceStore(_make_config())
        assert store.consume("") is None

    def test_nonces_are_unique(self) -> None:
        store = StateNonceStore(_make_config())
        nonces = {store.create({"i": i}) for i in range(50)}
        assert len(nonces) == 50


class TestAppleTicketStore:
    def test_create_and_consume(self) -> None:
        store = AppleTicketStore(_make_config())
        ticket = store.create(
            code="apple-code",
            redirect_uri="https://x/oauth/callback/apple",
            provider="apple-mobile",
        )
        payload = store.consume(ticket)
        assert payload is not None
        assert payload["code"] == "apple-code"
        assert payload["redirect_uri"] == "https://x/oauth/callback/apple"
        assert payload["provider"] == "apple-mobile"

    def test_ticket_single_use(self) -> None:
        store = AppleTicketStore(_make_config())
        ticket = store.create(
            code="c", redirect_uri="https://x", provider="apple-mobile"
        )
        assert store.consume(ticket) is not None
        assert store.consume(ticket) is None

    def test_consume_unknown(self) -> None:
        store = AppleTicketStore(_make_config())
        assert store.consume("nope") is None


class TestLooksLikeStateNonce:
    def test_json_is_not_a_nonce(self) -> None:
        assert looks_like_state_nonce('{"provider": "apple"}') is False

    def test_token_urlsafe_is_a_nonce(self) -> None:
        import secrets

        assert looks_like_state_nonce(secrets.token_urlsafe(32)) is True

    def test_empty_is_not_a_nonce(self) -> None:
        assert looks_like_state_nonce("") is False
