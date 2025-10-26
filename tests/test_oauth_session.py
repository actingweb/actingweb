"""
Unit tests for OAuth2 session management.

Tests the OAuth2SessionManager used for postponed actor creation when
OAuth providers don't provide email addresses.
"""

import pytest
import time
from typing import Dict, Any
from unittest.mock import Mock, MagicMock, patch


class TestOAuth2SessionManager:
    """Test OAuth2SessionManager for temporary token storage."""

    def setup_method(self):
        """Set up test fixtures."""
        # Import here to avoid module-level imports that might fail
        from actingweb.oauth_session import OAuth2SessionManager
        from actingweb.config import Config

        # Create mock config with database support
        self.config = Mock(spec=Config)

        # Create in-memory storage for testing
        self._test_storage = {}

        # Mock the DbAttribute class to use in-memory storage
        class MockDbAttribute:
            def __init__(test_self):
                test_self.storage = self._test_storage

            def get_bucket(test_self, actor_id, bucket):
                key = f"{actor_id}:{bucket}"
                return test_self.storage.get(key, {})

            def get_attr(test_self, actor_id, bucket, name):
                key = f"{actor_id}:{bucket}"
                bucket_data = test_self.storage.get(key, {})
                return bucket_data.get(name)

            def set_attr(test_self, actor_id, bucket, name, data, timestamp=None):
                key = f"{actor_id}:{bucket}"
                if key not in test_self.storage:
                    test_self.storage[key] = {}
                test_self.storage[key][name] = {"data": data, "timestamp": timestamp}
                return True

            def delete_attr(test_self, actor_id, bucket, name):
                key = f"{actor_id}:{bucket}"
                if key in test_self.storage and name in test_self.storage[key]:
                    del test_self.storage[key][name]
                    return True
                return False

            def delete_bucket(test_self, actor_id, bucket):
                key = f"{actor_id}:{bucket}"
                if key in test_self.storage:
                    del test_self.storage[key]
                    return True
                return False

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
            "expires_in": 3600
        }
        user_info = {
            "sub": "user123",
            "name": "Test User"
        }

        session_id = self.manager.store_session(
            token_data=token_data,
            user_info=user_info,
            state="test_state",
            provider="google"
        )

        assert session_id is not None
        assert len(session_id) > 20  # Should be a secure random token

    def test_get_session_retrieves_stored_data(self):
        """Test that get_session retrieves previously stored data."""
        token_data = {
            "access_token": "test_token",
            "refresh_token": "test_refresh"
        }
        user_info = {"sub": "user123"}

        session_id = self.manager.store_session(
            token_data=token_data,
            user_info=user_info,
            state="test_state",
            provider="github"
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
            provider="google"
        )

        # Manually set created_at to simulate old session (more than 10 minutes ago)
        # Get the session from the bucket, modify it, and save it back
        bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=OAUTH_SESSION_BUCKET,
            config=self.config
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
        with patch('actingweb.oauth2.create_oauth2_authenticator') as mock_create_auth:

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
                "expires_in": 3600
            }
            user_info = {"sub": "user123"}

            session_id = self.manager.store_session(
                token_data=token_data,
                user_info=user_info,
                state="",
                provider="google"
            )

            # Complete the session
            actor_result = self.manager.complete_session(session_id, "user@example.com")

            # Verify
            assert actor_result is not None
            assert actor_result.id == "actor123"
            mock_authenticator.lookup_or_create_actor_by_email.assert_called_once_with("user@example.com")

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
            provider="google"
        )

        # Try to complete with invalid email
        actor_result = self.manager.complete_session(session_id, "invalid_email")
        assert actor_result is None

        actor_result = self.manager.complete_session(session_id, "")
        assert actor_result is None

    def test_complete_session_clears_session(self):
        """Test that complete_session clears the session after use."""
        with patch('actingweb.oauth2.create_oauth2_authenticator') as mock_create_auth:
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
                provider="google"
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
            provider="google"
        )

        session_id2 = self.manager.store_session(
            token_data={"access_token": "test2"},
            user_info={"sub": "user2"},
            state="",
            provider="google"
        )

        # Manually set created_at to simulate old sessions (more than 10 minutes ago)
        bucket = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=OAUTH_SESSION_BUCKET,
            config=self.config
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

    def test_multiple_sessions_independent(self):
        """Test that multiple sessions are independent."""
        session_id1 = self.manager.store_session(
            token_data={"access_token": "token1"},
            user_info={"sub": "user1"},
            state="state1",
            provider="google"
        )

        session_id2 = self.manager.store_session(
            token_data={"access_token": "token2"},
            user_info={"sub": "user2"},
            state="state2",
            provider="github"
        )

        session1 = self.manager.get_session(session_id1)
        session2 = self.manager.get_session(session_id2)

        assert session1["token_data"]["access_token"] == "token1"
        assert session2["token_data"]["access_token"] == "token2"
        assert session1["provider"] == "google"
        assert session2["provider"] == "github"


class TestOAuth2SessionManagerFactory:
    """Test the factory function for OAuth2SessionManager."""

    def test_get_oauth2_session_manager_returns_instance(self):
        """Test that get_oauth2_session_manager returns a manager instance."""
        from actingweb.oauth_session import get_oauth2_session_manager
        from actingweb.config import Config

        config = Mock(spec=Config)
        manager = get_oauth2_session_manager(config)

        assert manager is not None
        assert hasattr(manager, 'store_session')
        assert hasattr(manager, 'get_session')
        assert hasattr(manager, 'complete_session')
