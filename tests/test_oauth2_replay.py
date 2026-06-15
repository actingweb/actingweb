"""Tests for IdTokenReplayCache (actingweb.oauth2_replay)."""

import time
from unittest.mock import Mock

from actingweb.config import Config
from actingweb.oauth2_replay import IdTokenReplayCache


def _make_config() -> Config:
    """Config with an in-memory attribute backend (mirrors test_oauth_session)."""
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


def _claims(**overrides) -> dict:
    now = int(time.time())
    base = {
        "iss": "https://appleid.apple.com",
        "sub": "abc",
        "iat": now,
        "exp": now + 600,
    }
    base.update(overrides)
    return base


class TestIdTokenReplayCache:
    def test_first_sight_accepts(self) -> None:
        cache = IdTokenReplayCache(_make_config())
        assert cache.check_and_record(_claims()) is True

    def test_immediate_replay_rejected(self) -> None:
        cache = IdTokenReplayCache(_make_config())
        claims = _claims(jti="unique-jti-1")
        assert cache.check_and_record(claims) is True
        assert cache.check_and_record(claims) is False

    def test_replay_by_iss_sub_iat_when_no_jti(self) -> None:
        cache = IdTokenReplayCache(_make_config())
        claims = _claims()  # no jti
        assert cache.check_and_record(claims) is True
        assert cache.check_and_record(claims) is False

    def test_distinct_tokens_both_accepted(self) -> None:
        cache = IdTokenReplayCache(_make_config())
        assert cache.check_and_record(_claims(jti="a")) is True
        assert cache.check_and_record(_claims(jti="b")) is True

    def test_expired_record_allows_reuse(self) -> None:
        config = _make_config()
        cache = IdTokenReplayCache(config)
        now = int(time.time())
        # Token already expired long ago: a stale record should not block.
        claims = _claims(iat=now - 2000, exp=now - 1000, jti="old")
        assert cache.check_and_record(claims) is True
        # A second sighting of an already-expired token: the recorded exp is in
        # the past, so it is treated as a fresh (re-issued) acceptance.
        assert cache.check_and_record(claims) is True

    def test_key_differs_by_jti(self) -> None:
        c1 = _claims(jti="x")
        c2 = _claims(jti="y")
        assert IdTokenReplayCache._key_for_claims(
            c1
        ) != IdTokenReplayCache._key_for_claims(c2)

    def test_key_stable_for_same_claims(self) -> None:
        c = _claims(jti="z")
        assert IdTokenReplayCache._key_for_claims(
            c
        ) == IdTokenReplayCache._key_for_claims(dict(c))
