"""
Unit tests for OAuth2 session management.

Tests the OAuth2SessionManager used for postponed actor creation when
OAuth providers don't provide email addresses.
"""

import time
from unittest.mock import Mock, patch


class TestOAuth2SessionManager:
    """Test OAuth2SessionManager for temporary token storage."""

    def setup_method(self):
        """Set up test fixtures."""
        # Import here to avoid module-level imports that might fail
        from actingweb.config import Config
        from actingweb.oauth_session import OAuth2SessionManager

        # Create mock config with database support
        self.config = Mock(spec=Config)

        # Create in-memory storage for testing
        self._test_storage = {}

        # Mock the DbAttribute class to use in-memory storage
        # Capture reference to storage for use in nested class
        test_storage = self._test_storage

        class MockDbAttribute:
            def __init__(self):  # type: ignore
                self.storage = test_storage

            def get_bucket(self, actor_id, bucket):  # type: ignore
                key = f"{actor_id}:{bucket}"
                return self.storage.get(key, {})

            def get_attr(self, actor_id, bucket, name):  # type: ignore
                key = f"{actor_id}:{bucket}"
                bucket_data = self.storage.get(key, {})
                return bucket_data.get(name)

            def set_attr(
                self,
                actor_id,
                bucket,
                name,
                data,
                timestamp=None,
                ttl_seconds=None,
            ):  # type: ignore
                key = f"{actor_id}:{bucket}"
                if key not in self.storage:
                    self.storage[key] = {}
                self.storage[key][name] = {
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
                key = f"{actor_id}:{bucket}"
                if key in self.storage:
                    del self.storage[key]
                    return True
                return False

            def conditional_update_attr(  # type: ignore
                self, actor_id, bucket, name, old_data, new_data, timestamp=None
            ):
                key = f"{actor_id}:{bucket}"
                current = self.storage.get(key, {}).get(name)
                if current is None or current.get("data") != old_data:
                    return False
                current["data"] = new_data
                current["timestamp"] = timestamp
                return True

            def delete_expired(self, now_epoch=None, buckets=None):  # type: ignore
                import time as _time

                if now_epoch is None:
                    now_epoch = int(_time.time())
                deleted = 0
                for key, items in list(self.storage.items()):
                    bucket_part = key.split(":", 1)[1] if ":" in key else ""
                    if buckets and bucket_part not in buckets:
                        continue
                    for name, rec in list(items.items()):
                        ttl_seconds = rec.get("ttl_seconds")
                        if ttl_seconds is None:
                            continue
                        # Mirror the backends: an explicit ttl is stored as an
                        # absolute ttl_timestamp = written_at + ttl. The mock has
                        # no written_at, so treat any record whose stored
                        # ttl_seconds marks it expired relative to now. Tests set
                        # ttl_seconds to a negative sentinel to force expiry.
                        if ttl_seconds < 0:
                            del items[name]
                            deleted += 1
                return deleted

            def delete_by_chain(self, actor_id=None, buckets=None, chain_id=None):  # type: ignore
                if not actor_id or not chain_id or not buckets:
                    return 0
                deleted = 0
                for bucket in buckets:
                    items = self.storage.get(f"{actor_id}:{bucket}", {})
                    for name, rec in list(items.items()):
                        data = rec.get("data") or {}
                        if isinstance(data, dict) and data.get("chain_id") == chain_id:
                            del items[name]
                            deleted += 1
                return deleted

        # Set up the mock DbAttribute
        mock_db_module = Mock()
        mock_db_module.DbAttribute = MockDbAttribute
        self.config.DbAttribute = mock_db_module

        self.manager = OAuth2SessionManager(self.config)

    def test_store_session_returns_session_id(self):
        """Test that store_session returns a valid session ID."""
        token_data = {
            "access_token": "test_token",
            "refresh_token": "test_refresh",
            "expires_in": 3600,
        }
        user_info = {"sub": "user123", "name": "Test User"}

        session_id = self.manager.store_session(
            token_data=token_data,
            user_info=user_info,
            state="test_state",
            provider="google",
        )

        assert session_id is not None
        assert len(session_id) > 20  # Should be a secure random token

    def test_get_session_retrieves_stored_data(self):
        """Test that get_session retrieves previously stored data."""
        token_data = {"access_token": "test_token", "refresh_token": "test_refresh"}
        user_info = {"sub": "user123"}

        session_id = self.manager.store_session(
            token_data=token_data,
            user_info=user_info,
            state="test_state",
            provider="github",
        )

        session = self.manager.get_session(session_id)

        assert session is not None
        assert session["token_data"] == token_data
        assert session["user_info"] == user_info
        assert session["state"] == "test_state"
        assert session["provider"] == "github"
        assert "created_at" in session

    def test_get_session_nonexistent_returns_none(self):
        """Test that get_session returns None for nonexistent session."""
        session = self.manager.get_session("nonexistent_session_id")
        assert session is None

    def test_get_session_expired_returns_none(self):
        """Test that get_session returns None for expired sessions."""
        from actingweb import attribute
        from actingweb.constants import OAUTH2_SYSTEM_ACTOR, OAUTH_SESSION_BUCKET

        # Store a session
        session_id = self.manager.store_session(
            token_data={"access_token": "test"},
            user_info={"sub": "user"},
            state="",
            provider="google",
        )

        # Manually set created_at to simulate old session (more than 10 minutes ago)
        # Get the session from the bucket, modify it, and save it back
        bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=OAUTH_SESSION_BUCKET,
            config=self.config,
        )
        session_attr = bucket.get_attr(name=session_id)
        if session_attr and "data" in session_attr:
            session_data = session_attr["data"]
            old_time = int(time.time()) - 700  # 11+ minutes ago (TTL is 600 seconds)
            session_data["created_at"] = old_time
            bucket.set_attr(name=session_id, data=session_data)

        # Try to get expired session
        session = self.manager.get_session(session_id)
        assert session is None  # Should be expired and auto-removed

    def test_complete_session_creates_actor(self):
        """Test that complete_session creates an actor with provided email."""
        # Mock the imports inside the function
        with patch("actingweb.oauth2.create_oauth2_authenticator") as mock_create_auth:
            # Setup mocks
            mock_authenticator = Mock()
            mock_actor = Mock()
            mock_actor.id = "actor123"
            mock_actor.store = Mock()

            mock_create_auth.return_value = mock_authenticator
            mock_authenticator.lookup_or_create_actor_by_email.return_value = mock_actor

            # Store a session
            token_data = {
                "access_token": "test_token",
                "refresh_token": "test_refresh",
                "expires_in": 3600,
            }
            user_info = {"sub": "user123"}

            session_id = self.manager.store_session(
                token_data=token_data, user_info=user_info, state="", provider="google"
            )

            # Complete the session
            actor_result = self.manager.complete_session(session_id, "user@example.com")

            # Verify
            assert actor_result is not None
            assert actor_result.id == "actor123"
            mock_authenticator.lookup_or_create_actor_by_email.assert_called_once_with(
                "user@example.com"
            )

            # Verify OAuth tokens were stored
            assert mock_actor.store.oauth_token == "test_token"
            assert mock_actor.store.oauth_refresh_token == "test_refresh"
            assert mock_actor.store.oauth_provider == "google"

    def test_complete_session_invalid_email_returns_none(self):
        """Test that complete_session returns None for invalid email."""
        # Store a session
        session_id = self.manager.store_session(
            token_data={"access_token": "test"},
            user_info={"sub": "user"},
            state="",
            provider="google",
        )

        # Try to complete with invalid email
        actor_result = self.manager.complete_session(session_id, "invalid_email")
        assert actor_result is None

        actor_result = self.manager.complete_session(session_id, "")
        assert actor_result is None

    def test_complete_session_clears_session(self):
        """Test that complete_session clears the session after use."""
        with patch("actingweb.oauth2.create_oauth2_authenticator") as mock_create_auth:
            mock_authenticator = Mock()
            mock_actor = Mock()
            mock_actor.id = "actor123"
            mock_actor.store = Mock()

            mock_create_auth.return_value = mock_authenticator
            mock_authenticator.lookup_or_create_actor_by_email.return_value = mock_actor

            # Store a session
            session_id = self.manager.store_session(
                token_data={"access_token": "test"},
                user_info={"sub": "user"},
                state="",
                provider="google",
            )

            # Complete the session
            self.manager.complete_session(session_id, "user@example.com")

            # Session should be cleared
            session = self.manager.get_session(session_id)
            assert session is None

    def test_clear_expired_sessions(self):
        """Test that clear_expired_sessions removes old sessions."""
        from actingweb import attribute
        from actingweb.constants import OAUTH2_SYSTEM_ACTOR, OAUTH_SESSION_BUCKET

        # Store two sessions
        session_id1 = self.manager.store_session(
            token_data={"access_token": "test1"},
            user_info={"sub": "user1"},
            state="",
            provider="google",
        )

        session_id2 = self.manager.store_session(
            token_data={"access_token": "test2"},
            user_info={"sub": "user2"},
            state="",
            provider="google",
        )

        # Manually set created_at to simulate old sessions (more than 10 minutes ago)
        bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=OAUTH_SESSION_BUCKET,
            config=self.config,
        )
        old_time = int(time.time()) - 700  # 11+ minutes ago (TTL is 600 seconds)

        for session_id in [session_id1, session_id2]:
            session_attr = bucket.get_attr(name=session_id)
            if session_attr and "data" in session_attr:
                session_data = session_attr["data"]
                session_data["created_at"] = old_time
                bucket.set_attr(name=session_id, data=session_data)

        # Clear expired sessions
        cleared_count = self.manager.clear_expired_sessions()

        # Both sessions should have been cleared
        assert cleared_count == 2
        # Verify sessions are gone
        assert self.manager.get_session(session_id1) is None
        assert self.manager.get_session(session_id2) is None

    def test_revoke_all_tokens_does_not_crash_on_concurrent_delete(self):
        """Regression: ``revoke_all_tokens`` deletes matching tokens while
        iterating the bucket dict. Without snapshotting the items first, this
        raised ``RuntimeError: dictionary changed size during iteration`` (the
        live SPA refresh-token-reuse path hit this with a 500). Seed multiple
        matching tokens in both buckets so a delete happens mid-iteration."""
        from actingweb import attribute
        from actingweb.constants import OAUTH2_SYSTEM_ACTOR
        from actingweb.oauth_session import (
            _ACCESS_TOKEN_BUCKET,
            _REFRESH_TOKEN_BUCKET,
        )

        actor_id = "victim-actor"
        seeded_per_bucket = 3
        access_bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=_ACCESS_TOKEN_BUCKET,
            config=self.config,
        )
        refresh_bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=_REFRESH_TOKEN_BUCKET,
            config=self.config,
        )
        # Several tokens for the target actor (all revoked) plus one for a
        # different actor (must survive).
        for i in range(seeded_per_bucket):
            access_bucket.set_attr(name=f"at{i}", data={"actor_id": actor_id})
            refresh_bucket.set_attr(name=f"rt{i}", data={"actor_id": actor_id})
        access_bucket.set_attr(name="keep_at", data={"actor_id": "other-actor"})
        refresh_bucket.set_attr(name="keep_rt", data={"actor_id": "other-actor"})

        revoked = self.manager.revoke_all_tokens(actor_id)

        # Derived from what we seeded (access + refresh) rather than hardcoded.
        # ``self._test_storage`` is isolated per test instance, so only the
        # victim's seeded tokens are present.
        assert revoked == seeded_per_bucket * 2
        # Read the shared backing store directly (the per-instance Attributes
        # caches above are stale after revoke's own instances deleted).
        access_store = self._test_storage[
            f"{OAUTH2_SYSTEM_ACTOR}:{_ACCESS_TOKEN_BUCKET}"
        ]
        refresh_store = self._test_storage[
            f"{OAUTH2_SYSTEM_ACTOR}:{_REFRESH_TOKEN_BUCKET}"
        ]
        # The other actor's tokens are untouched.
        assert "keep_at" in access_store
        assert "keep_rt" in refresh_store
        # The victim's tokens are gone.
        assert not any(k.startswith("at") for k in access_store)
        assert not any(k.startswith("rt") for k in refresh_store)

    def test_create_refresh_token_stamps_chain_id(self):
        """A fresh login token starts its own chain; a rotated token can inherit
        the parent's chain_id so the family can be revoked together."""
        root = self.manager.create_refresh_token("actor-1", "user@example.com")
        root_data = self.manager.validate_refresh_token(root)
        assert root_data is not None
        chain_id = root_data["chain_id"]
        assert chain_id  # non-empty

        # Rotation inherits the chain.
        rotated = self.manager.create_refresh_token(
            "actor-1", "user@example.com", chain_id=chain_id
        )
        rotated_data = self.manager.validate_refresh_token(rotated)
        assert rotated_data is not None
        assert rotated_data["chain_id"] == chain_id

        # A separate login starts a new chain.
        other = self.manager.create_refresh_token("actor-1", "user@example.com")
        other_data = self.manager.validate_refresh_token(other)
        assert other_data is not None
        assert other_data["chain_id"] != chain_id

    def test_revoke_token_chain_scopes_to_family(self):
        """``revoke_token_chain`` deletes only the refresh tokens in the given
        family, leaving the actor's other chains (other devices/sessions) and
        access tokens intact — the surgical replacement for the mass-logout that
        produced the SPA white-screen."""
        from actingweb.constants import OAUTH2_SYSTEM_ACTOR
        from actingweb.oauth_session import (
            _ACCESS_TOKEN_BUCKET,
            _REFRESH_TOKEN_BUCKET,
        )

        actor_id = "multi-device-actor"

        # Chain A: a root token rotated once (two tokens, same family).
        a_root = self.manager.create_refresh_token(actor_id, "u@example.com")
        a_chain = self.manager.validate_refresh_token(a_root)["chain_id"]  # type: ignore[index]
        self.manager.create_refresh_token(actor_id, "u@example.com", chain_id=a_chain)

        # Chain B: the actor's other device — must survive.
        b_root = self.manager.create_refresh_token(actor_id, "u@example.com")
        b_chain = self.manager.validate_refresh_token(b_root)["chain_id"]  # type: ignore[index]

        # An access token for the actor — must survive (self-expires).
        self.manager.store_access_token("acc-1", actor_id, "u@example.com")

        revoked = self.manager.revoke_token_chain(actor_id, a_chain)
        assert revoked == 2  # only chain A's two refresh tokens

        refresh_store = self._test_storage[
            f"{OAUTH2_SYSTEM_ACTOR}:{_REFRESH_TOKEN_BUCKET}"
        ]
        access_store = self._test_storage[
            f"{OAUTH2_SYSTEM_ACTOR}:{_ACCESS_TOKEN_BUCKET}"
        ]
        # Chain A gone, chain B intact, access token intact.
        assert not any(
            (v.get("data") or {}).get("chain_id") == a_chain
            for v in refresh_store.values()
        )
        assert any(
            (v.get("data") or {}).get("chain_id") == b_chain
            for v in refresh_store.values()
        )
        assert "acc-1" in access_store

    def test_revoke_token_chain_also_revokes_chain_tagged_access_tokens(self):
        """Access tokens minted from the chain (tagged with its chain_id) are
        revoked with the family; untagged or other-chain access tokens survive."""
        from actingweb.constants import OAUTH2_SYSTEM_ACTOR
        from actingweb.oauth_session import _ACCESS_TOKEN_BUCKET

        actor_id = "actor-at"
        rt = self.manager.create_refresh_token(actor_id, "u@example.com")
        chain_id = self.manager.validate_refresh_token(rt)["chain_id"]  # type: ignore[index]

        self.manager.store_access_token(
            "at-in-chain", actor_id, "u@example.com", chain_id=chain_id
        )
        self.manager.store_access_token(
            "at-other-chain", actor_id, "u@example.com", chain_id="different"
        )
        self.manager.store_access_token("at-untagged", actor_id, "u@example.com")

        revoked = self.manager.revoke_token_chain(actor_id, chain_id)
        # 1 refresh token + 1 chain-tagged access token.
        assert revoked == 2

        access_store = self._test_storage[
            f"{OAUTH2_SYSTEM_ACTOR}:{_ACCESS_TOKEN_BUCKET}"
        ]
        assert "at-in-chain" not in access_store
        assert "at-other-chain" in access_store
        assert "at-untagged" in access_store

    def test_marking_token_used_shortens_ttl(self):
        """Rotating (marking used) a refresh token shrinks its storage TTL from
        the full refresh TTL to the bounded reuse window, so used tokens are
        purged promptly instead of lingering for two weeks."""
        from actingweb.constants import (
            OAUTH2_SYSTEM_ACTOR,
            SPA_REFRESH_TOKEN_REUSE_WINDOW,
            SPA_REFRESH_TOKEN_TTL,
        )
        from actingweb.oauth_session import _REFRESH_TOKEN_BUCKET

        token = self.manager.create_refresh_token("actor-ttl", "u@example.com")
        key = f"{OAUTH2_SYSTEM_ACTOR}:{_REFRESH_TOKEN_BUCKET}"
        # Created with the full refresh TTL.
        assert self._test_storage[key][token]["ttl_seconds"] == SPA_REFRESH_TOKEN_TTL

        marked, _ = self.manager.try_mark_refresh_token_used(token)
        assert marked is True
        # After rotation the used token is retained only for the reuse window.
        assert (
            self._test_storage[key][token]["ttl_seconds"]
            == SPA_REFRESH_TOKEN_REUSE_WINDOW
        )

    def test_purge_expired_tokens_delegates_to_backend(self):
        """``purge_expired_tokens`` issues a backend-level expired-row delete,
        scoped to the SPA token buckets."""
        from actingweb.constants import OAUTH2_SYSTEM_ACTOR
        from actingweb.oauth_session import (
            _ACCESS_TOKEN_BUCKET,
            _REFRESH_TOKEN_BUCKET,
        )

        refresh_key = f"{OAUTH2_SYSTEM_ACTOR}:{_REFRESH_TOKEN_BUCKET}"
        access_key = f"{OAUTH2_SYSTEM_ACTOR}:{_ACCESS_TOKEN_BUCKET}"
        # Negative ttl_seconds is the mock's "already expired" sentinel.
        self._test_storage.setdefault(refresh_key, {})["expired-rt"] = {
            "data": {"actor_id": "a"},
            "ttl_seconds": -1,
        }
        self._test_storage[refresh_key]["fresh-rt"] = {
            "data": {"actor_id": "a"},
            "ttl_seconds": 1000,
        }
        self._test_storage.setdefault(access_key, {})["expired-at"] = {
            "data": {"actor_id": "a"},
            "ttl_seconds": -1,
        }

        deleted = self.manager.purge_expired_tokens()
        assert deleted == 2
        assert "expired-rt" not in self._test_storage[refresh_key]
        assert "fresh-rt" in self._test_storage[refresh_key]
        assert "expired-at" not in self._test_storage[access_key]

    def test_maybe_purge_is_throttled_per_process(self):
        """``maybe_purge_expired_tokens`` purges once then is throttled until the
        interval elapses, so the token endpoint can call it on every request."""
        import actingweb.oauth_session as oauth_session_mod
        from actingweb.constants import OAUTH2_SYSTEM_ACTOR
        from actingweb.oauth_session import _REFRESH_TOKEN_BUCKET

        # Reset the process-local throttle so this test is deterministic.
        oauth_session_mod._last_purge_attempt = 0.0

        refresh_key = f"{OAUTH2_SYSTEM_ACTOR}:{_REFRESH_TOKEN_BUCKET}"
        self._test_storage.setdefault(refresh_key, {})["expired-rt"] = {
            "data": {"actor_id": "a"},
            "ttl_seconds": -1,
        }

        # First call runs the purge.
        assert self.manager.maybe_purge_expired_tokens() == 1
        assert "expired-rt" not in self._test_storage[refresh_key]

        # Second call within the interval is throttled (no work).
        self._test_storage[refresh_key]["expired-rt-2"] = {
            "data": {"actor_id": "a"},
            "ttl_seconds": -1,
        }
        assert self.manager.maybe_purge_expired_tokens() == 0
        assert "expired-rt-2" in self._test_storage[refresh_key]

    def test_multiple_sessions_independent(self):
        """Test that multiple sessions are independent."""
        session_id1 = self.manager.store_session(
            token_data={"access_token": "token1"},
            user_info={"sub": "user1"},
            state="state1",
            provider="google",
        )

        session_id2 = self.manager.store_session(
            token_data={"access_token": "token2"},
            user_info={"sub": "user2"},
            state="state2",
            provider="github",
        )

        session1 = self.manager.get_session(session_id1)
        session2 = self.manager.get_session(session_id2)

        assert session1["token_data"]["access_token"] == "token1"  # type: ignore
        assert session2["token_data"]["access_token"] == "token2"  # type: ignore
        assert session1["provider"] == "google"  # type: ignore
        assert session2["provider"] == "github"  # type: ignore


class TestOAuth2SessionManagerFactory:
    """Test the factory function for OAuth2SessionManager."""

    def test_get_oauth2_session_manager_returns_instance(self):
        """Test that get_oauth2_session_manager returns a manager instance."""
        from actingweb.config import Config
        from actingweb.oauth_session import get_oauth2_session_manager

        config = Mock(spec=Config)
        manager = get_oauth2_session_manager(config)

        assert manager is not None
        assert hasattr(manager, "store_session")
        assert hasattr(manager, "get_session")
        assert hasattr(manager, "complete_session")
