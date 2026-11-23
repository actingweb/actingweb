"""
Tests for conditional_update_attr functionality.

These tests verify the atomic compare-and-swap functionality used for
race-free updates, particularly for OAuth refresh token rotation.
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC
from typing import Any

import pytest

from actingweb.config import Config


@pytest.mark.integration
class TestConditionalUpdateAttrBasic:
    """Basic functional tests for conditional_update_attr."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config = Config(unique_creator=False)
        self.backend = os.getenv("DATABASE_BACKEND", "dynamodb")
        # Create a unique test actor for each test
        self.test_actor_id = f"cond_test_{int(time.time() * 1000000)}"

        # Create test actor
        db_actor = self.config.DbActor.DbActor()  # type: ignore
        success = db_actor.create(
            actor_id=self.test_actor_id,
            creator="test@example.com",
            passphrase="test123",
        )
        assert success, "Failed to create test actor"

    def teardown_method(self):
        """Clean up test fixtures."""
        try:
            # Delete test actor and all associated data
            db_actor = self.config.DbActor.DbActor()  # type: ignore
            db_actor.get(actor_id=self.test_actor_id)
            if db_actor.handle:
                # Clean up attributes first
                buckets = self.config.DbAttribute.DbAttributeBucketList()  # type: ignore
                buckets.delete(actor_id=self.test_actor_id)

                # Then delete actor
                db_actor.delete()
        except Exception:
            pass  # Best effort cleanup

    def test_conditional_update_success_when_match(self):
        """Test conditional update succeeds when old_data matches."""
        db_attr = self.config.DbAttribute.DbAttribute()  # type: ignore

        # Set initial value
        initial_data = {"token": "old_token", "used": False}
        success = db_attr.set_attr(
            actor_id=self.test_actor_id,
            bucket="test_bucket",
            name="test_attr",
            data=initial_data,
        )
        assert success, "Failed to set initial attribute"

        # Conditionally update with correct old_data
        new_data = {"token": "new_token", "used": True}
        result = db_attr.conditional_update_attr(
            actor_id=self.test_actor_id,
            bucket="test_bucket",
            name="test_attr",
            old_data=initial_data,
            new_data=new_data,
        )

        assert result is True, "Conditional update should succeed when old_data matches"

        # Verify the data was actually updated
        retrieved = db_attr.get_attr(
            actor_id=self.test_actor_id,
            bucket="test_bucket",
            name="test_attr",
        )
        assert retrieved is not None
        assert retrieved["data"] == new_data

    def test_conditional_update_fails_when_mismatch(self):
        """Test conditional update fails when old_data doesn't match."""
        db_attr = self.config.DbAttribute.DbAttribute()  # type: ignore

        # Set initial value
        initial_data = {"token": "old_token", "used": False}
        success = db_attr.set_attr(
            actor_id=self.test_actor_id,
            bucket="test_bucket",
            name="test_attr",
            data=initial_data,
        )
        assert success, "Failed to set initial attribute"

        # Try to conditionally update with wrong old_data
        wrong_old_data = {"token": "wrong_token", "used": False}
        new_data = {"token": "new_token", "used": True}
        result = db_attr.conditional_update_attr(
            actor_id=self.test_actor_id,
            bucket="test_bucket",
            name="test_attr",
            old_data=wrong_old_data,
            new_data=new_data,
        )

        assert result is False, (
            "Conditional update should fail when old_data doesn't match"
        )

        # Verify the data was NOT updated
        retrieved = db_attr.get_attr(
            actor_id=self.test_actor_id,
            bucket="test_bucket",
            name="test_attr",
        )
        assert retrieved is not None
        assert retrieved["data"] == initial_data  # Should still be the initial data

    def test_conditional_update_with_timestamp(self):
        """Test conditional update with timestamp parameter."""
        from datetime import datetime

        db_attr = self.config.DbAttribute.DbAttribute()  # type: ignore

        # Set initial value
        initial_data = {"value": 1}
        initial_timestamp = datetime.now(UTC)
        success = db_attr.set_attr(
            actor_id=self.test_actor_id,
            bucket="test_bucket",
            name="test_attr",
            data=initial_data,
            timestamp=initial_timestamp,
        )
        assert success, "Failed to set initial attribute"

        # Conditionally update with new timestamp
        new_data = {"value": 2}
        new_timestamp = datetime.now(UTC)
        result = db_attr.conditional_update_attr(
            actor_id=self.test_actor_id,
            bucket="test_bucket",
            name="test_attr",
            old_data=initial_data,
            new_data=new_data,
            timestamp=new_timestamp,
        )

        assert result is True, "Conditional update with timestamp should succeed"

        # Verify both data and timestamp were updated
        retrieved = db_attr.get_attr(
            actor_id=self.test_actor_id,
            bucket="test_bucket",
            name="test_attr",
        )
        assert retrieved is not None
        assert retrieved["data"] == new_data
        # Note: timestamp comparison may need to account for backend-specific formats

    def test_conditional_update_nonexistent_attribute(self):
        """Test conditional update fails for non-existent attribute."""
        db_attr = self.config.DbAttribute.DbAttribute()  # type: ignore

        # Try to conditionally update an attribute that doesn't exist
        result = db_attr.conditional_update_attr(
            actor_id=self.test_actor_id,
            bucket="test_bucket",
            name="nonexistent_attr",
            old_data={"value": "old"},
            new_data={"value": "new"},
        )

        assert result is False, (
            "Conditional update should fail for non-existent attribute"
        )

    def test_conditional_update_invalid_params(self):
        """Test conditional update fails with invalid parameters."""
        db_attr = self.config.DbAttribute.DbAttribute()  # type: ignore

        # Test with missing actor_id
        result = db_attr.conditional_update_attr(
            actor_id=None,
            bucket="test_bucket",
            name="test_attr",
            old_data={"value": "old"},
            new_data={"value": "new"},
        )
        assert result is False

        # Test with missing bucket
        result = db_attr.conditional_update_attr(
            actor_id=self.test_actor_id,
            bucket=None,
            name="test_attr",
            old_data={"value": "old"},
            new_data={"value": "new"},
        )
        assert result is False

        # Test with missing name
        result = db_attr.conditional_update_attr(
            actor_id=self.test_actor_id,
            bucket="test_bucket",
            name=None,
            old_data={"value": "old"},
            new_data={"value": "new"},
        )
        assert result is False


@pytest.mark.integration
class TestConditionalUpdateAttrJSONComparison:
    """Test JSON comparison reliability across different backends."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config = Config(unique_creator=False)
        self.backend = os.getenv("DATABASE_BACKEND", "dynamodb")
        self.test_actor_id = f"cond_json_{int(time.time() * 1000000)}"

        # Create test actor
        db_actor = self.config.DbActor.DbActor()  # type: ignore
        success = db_actor.create(
            actor_id=self.test_actor_id,
            creator="test@example.com",
            passphrase="test123",
        )
        assert success

    def teardown_method(self):
        """Clean up test fixtures."""
        try:
            db_actor = self.config.DbActor.DbActor()  # type: ignore
            db_actor.get(actor_id=self.test_actor_id)
            if db_actor.handle:
                buckets = self.config.DbAttribute.DbAttributeBucketList()  # type: ignore
                buckets.delete(actor_id=self.test_actor_id)
                db_actor.delete()
        except Exception:
            pass

    def test_json_key_order_independence(self):
        """Test that JSON comparison is independent of key ordering."""
        db_attr = self.config.DbAttribute.DbAttribute()  # type: ignore

        # Set initial value with keys in one order
        initial_data = {"z": 3, "a": 1, "m": 2}
        success = db_attr.set_attr(
            actor_id=self.test_actor_id,
            bucket="test_bucket",
            name="test_attr",
            data=initial_data,
        )
        assert success

        # Try to update with same data but different key order
        # This should match because JSON comparison should be order-independent
        old_data_different_order = {"a": 1, "m": 2, "z": 3}
        new_data = {"value": "updated"}
        result = db_attr.conditional_update_attr(
            actor_id=self.test_actor_id,
            bucket="test_bucket",
            name="test_attr",
            old_data=old_data_different_order,
            new_data=new_data,
        )

        # This should succeed because the data is semantically identical
        assert result is True, "JSON comparison should be order-independent"

    def test_json_nested_structures(self):
        """Test conditional update with nested JSON structures."""
        db_attr = self.config.DbAttribute.DbAttribute()  # type: ignore

        # Set initial value with nested structure
        initial_data = {
            "token": "abc123",
            "metadata": {"issued_at": 1234567890, "scopes": ["read", "write"]},
            "used": False,
        }
        success = db_attr.set_attr(
            actor_id=self.test_actor_id,
            bucket="test_bucket",
            name="test_attr",
            data=initial_data,
        )
        assert success

        # Update with matching nested structure
        new_data = {
            "token": "xyz789",
            "metadata": {"issued_at": 1234567890, "scopes": ["read", "write"]},
            "used": True,
        }
        result = db_attr.conditional_update_attr(
            actor_id=self.test_actor_id,
            bucket="test_bucket",
            name="test_attr",
            old_data=initial_data,
            new_data=new_data,
        )

        assert result is True, "Should handle nested JSON structures correctly"


@pytest.mark.integration
@pytest.mark.slow
class TestConditionalUpdateAttrConcurrency:
    """Test concurrent access patterns (simulating race conditions)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config = Config(unique_creator=False)
        self.backend = os.getenv("DATABASE_BACKEND", "dynamodb")
        self.test_actor_id = f"cond_race_{int(time.time() * 1000000)}"

        # Create test actor
        db_actor = self.config.DbActor.DbActor()  # type: ignore
        success = db_actor.create(
            actor_id=self.test_actor_id,
            creator="test@example.com",
            passphrase="test123",
        )
        assert success

    def teardown_method(self):
        """Clean up test fixtures."""
        try:
            db_actor = self.config.DbActor.DbActor()  # type: ignore
            db_actor.get(actor_id=self.test_actor_id)
            if db_actor.handle:
                buckets = self.config.DbAttribute.DbAttributeBucketList()  # type: ignore
                buckets.delete(actor_id=self.test_actor_id)
                db_actor.delete()
        except Exception:
            pass

    def test_concurrent_updates_only_one_succeeds(self):
        """Test that only one concurrent update succeeds (compare-and-swap behavior)."""
        db_attr = self.config.DbAttribute.DbAttribute()  # type: ignore

        # Set initial value
        initial_data = {"counter": 0, "token": "initial"}
        success = db_attr.set_attr(
            actor_id=self.test_actor_id,
            bucket="test_bucket",
            name="race_attr",
            data=initial_data,
        )
        assert success

        # Function to attempt conditional update
        def attempt_update(worker_id: int) -> bool:
            """Attempt to update the attribute."""
            db = self.config.DbAttribute.DbAttribute()  # type: ignore
            # All workers try to update based on the same old_data
            return db.conditional_update_attr(
                actor_id=self.test_actor_id,
                bucket="test_bucket",
                name="race_attr",
                old_data=initial_data,
                new_data={"counter": worker_id, "token": f"worker_{worker_id}"},
            )

        # Launch multiple concurrent updates
        num_workers = 5
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(attempt_update, i) for i in range(num_workers)]
            results = [future.result() for future in as_completed(futures)]

        # Exactly one should succeed
        success_count = sum(1 for r in results if r is True)
        assert success_count == 1, f"Expected exactly 1 success, got {success_count}"

        # Verify the final state
        final = db_attr.get_attr(
            actor_id=self.test_actor_id,
            bucket="test_bucket",
            name="race_attr",
        )
        assert final is not None
        # The counter should be one of the worker IDs (0-4)
        assert final["data"]["counter"] in range(num_workers)

    def test_sequential_updates_all_succeed(self):
        """Test that sequential conditional updates work correctly."""
        db_attr = self.config.DbAttribute.DbAttribute()  # type: ignore

        # Set initial value
        current_data = {"version": 0}
        success = db_attr.set_attr(
            actor_id=self.test_actor_id,
            bucket="test_bucket",
            name="seq_attr",
            data=current_data,
        )
        assert success

        # Perform multiple sequential updates
        for i in range(1, 6):
            new_data = {"version": i}
            result = db_attr.conditional_update_attr(
                actor_id=self.test_actor_id,
                bucket="test_bucket",
                name="seq_attr",
                old_data=current_data,
                new_data=new_data,
            )
            assert result is True, f"Sequential update {i} should succeed"
            current_data = new_data

        # Verify final state
        final = db_attr.get_attr(
            actor_id=self.test_actor_id,
            bucket="test_bucket",
            name="seq_attr",
        )
        assert final is not None
        assert final["data"]["version"] == 5


@pytest.mark.integration
class TestTryMarkRefreshTokenUsed:
    """Test try_mark_refresh_token_used functionality for OAuth token rotation."""

    def setup_method(self):
        """Set up test fixtures."""
        from actingweb.constants import OAUTH2_SYSTEM_ACTOR

        self.config = Config(unique_creator=False)
        self.backend = os.getenv("DATABASE_BACKEND", "dynamodb")
        self.oauth2_system_actor = OAUTH2_SYSTEM_ACTOR

        # Ensure the OAuth2 system actor exists
        db_actor = self.config.DbActor.DbActor()  # type: ignore
        actor_data = db_actor.get(actor_id=self.oauth2_system_actor)
        if not actor_data:
            db_actor.create(
                actor_id=self.oauth2_system_actor,
                creator="system",
                passphrase="oauth2_system",
            )

    def teardown_method(self):
        """Clean up test fixtures."""
        # Note: We don't delete the OAuth2 system actor as it's shared
        # Just clean up any test tokens
        pass

    def test_mark_unused_token_succeeds(self):
        """Test marking an unused token succeeds."""
        from actingweb.oauth_session import OAuth2SessionManager

        session_mgr = OAuth2SessionManager(config=self.config)

        # Create a fresh token
        token = f"test_token_{int(time.time() * 1000000)}"
        token_data = {
            "actor_id": "test_actor",
            "trust_peerid": "test_peer",
            "expires_at": int(time.time()) + 3600,  # Expires in 1 hour
            "used": False,
        }

        # Create the token
        # We need to directly store it for testing since create_refresh_token generates the token
        from actingweb.attribute import Attributes
        from actingweb.constants import OAUTH2_SYSTEM_ACTOR

        bucket = Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket="spa_refresh_tokens",
            config=self.config,
        )
        success = bucket.set_attr(name=token, data=token_data)
        assert success, "Failed to store test token"

        # Try to mark it as used
        marked, returned_data = session_mgr.try_mark_refresh_token_used(token)

        assert marked is True, "Should successfully mark unused token"
        assert returned_data is not None
        assert returned_data["used"] is True
        assert "used_at" in returned_data
        assert isinstance(returned_data["used_at"], int)

    def test_mark_already_used_token_fails(self):
        """Test marking an already-used token fails with used_at timestamp."""
        from actingweb.attribute import Attributes
        from actingweb.constants import OAUTH2_SYSTEM_ACTOR
        from actingweb.oauth_session import OAuth2SessionManager

        session_mgr = OAuth2SessionManager(config=self.config)

        # Create and mark a token as used
        token = f"test_token_{int(time.time() * 1000000)}"
        token_data = {
            "actor_id": "test_actor",
            "trust_peerid": "test_peer",
            "expires_at": int(time.time()) + 3600,
            "used": False,
        }

        # Store the token
        bucket = Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket="spa_refresh_tokens",
            config=self.config,
        )
        success = bucket.set_attr(name=token, data=token_data)
        assert success

        # Mark it as used (first time should succeed)
        marked, _ = session_mgr.try_mark_refresh_token_used(token)
        assert marked is True

        # Try to mark it again (should fail)
        marked_again, returned_data = session_mgr.try_mark_refresh_token_used(token)

        assert marked_again is False, "Should fail to mark already-used token"
        assert returned_data is not None, "Should return token data"
        assert returned_data["used"] is True
        assert "used_at" in returned_data, "Should include used_at timestamp"

    def test_mark_nonexistent_token_fails(self):
        """Test marking a non-existent token fails."""
        from actingweb.oauth_session import OAuth2SessionManager

        session_mgr = OAuth2SessionManager(config=self.config)

        # Try to mark a token that doesn't exist
        marked, returned_data = session_mgr.try_mark_refresh_token_used(
            "nonexistent_token"
        )

        assert marked is False, "Should fail for non-existent token"
        assert returned_data is None, "Should return None for non-existent token"

    def test_mark_expired_token_fails(self):
        """Test marking an expired token fails and cleans up the token."""
        from actingweb.oauth_session import OAuth2SessionManager

        session_mgr = OAuth2SessionManager(config=self.config)

        # Create an expired token
        token = f"test_token_{int(time.time() * 1000000)}"
        token_data = {
            "actor_id": "test_actor",
            "trust_peerid": "test_peer",
            "expires_at": int(time.time()) - 3600,  # Expired 1 hour ago
        }

        # Store the token directly (bypassing expiration check in store_refresh_token)
        from actingweb.attribute import Attributes
        from actingweb.constants import OAUTH2_SYSTEM_ACTOR

        bucket = Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket="spa_refresh_tokens",
            config=self.config,
        )
        bucket.set_attr(name=token, data=token_data)

        # Try to mark it as used
        marked, returned_data = session_mgr.try_mark_refresh_token_used(token)

        assert marked is False, "Should fail for expired token"
        assert returned_data is None, "Should return None for expired token"

        # Verify the token was deleted - create fresh bucket to avoid cached data
        fresh_bucket = Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket="spa_refresh_tokens",
            config=self.config,
        )
        token_attr = fresh_bucket.get_attr(name=token)
        assert token_attr is None, "Expired token should be cleaned up"

    def test_empty_token_fails(self):
        """Test that empty token fails gracefully."""
        from actingweb.oauth_session import OAuth2SessionManager

        session_mgr = OAuth2SessionManager(config=self.config)

        marked, returned_data = session_mgr.try_mark_refresh_token_used("")

        assert marked is False
        assert returned_data is None


@pytest.mark.integration
@pytest.mark.slow
class TestTryMarkRefreshTokenUsedConcurrency:
    """Test concurrent token marking (race condition simulation)."""

    def setup_method(self):
        """Set up test fixtures."""
        from actingweb.constants import OAUTH2_SYSTEM_ACTOR

        self.config = Config(unique_creator=False)
        self.oauth2_system_actor = OAUTH2_SYSTEM_ACTOR

        # Ensure the OAuth2 system actor exists
        db_actor = self.config.DbActor.DbActor()  # type: ignore
        actor_data = db_actor.get(actor_id=self.oauth2_system_actor)
        if not actor_data:
            db_actor.create(
                actor_id=self.oauth2_system_actor,
                creator="system",
                passphrase="oauth2_system",
            )

    def teardown_method(self):
        """Clean up test fixtures."""
        pass

    def test_concurrent_token_marking_only_one_succeeds(self):
        """
        Test that only one concurrent request succeeds in marking a token.

        This simulates the race condition that occurs when multiple
        requests try to use the same refresh token simultaneously.
        """
        # Create a fresh token
        token = f"race_token_{int(time.time() * 1000000)}"
        token_data = {
            "actor_id": "test_actor",
            "trust_peerid": "test_peer",
            "expires_at": int(time.time()) + 3600,
            "used": False,
        }

        # Store the token
        from actingweb.attribute import Attributes
        from actingweb.constants import OAUTH2_SYSTEM_ACTOR

        bucket = Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket="spa_refresh_tokens",
            config=self.config,
        )
        success = bucket.set_attr(name=token, data=token_data)
        assert success

        # Function to attempt marking the token
        def attempt_mark(worker_id: int) -> tuple[bool, dict | None]:
            """Attempt to mark the token as used."""
            from actingweb.oauth_session import OAuth2SessionManager

            mgr = OAuth2SessionManager(config=self.config)
            return mgr.try_mark_refresh_token_used(token)

        # Launch multiple concurrent attempts
        num_workers = 5
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(attempt_mark, i) for i in range(num_workers)]
            results = [future.result() for future in as_completed(futures)]

        # Exactly one should succeed
        success_count = sum(1 for marked, _ in results if marked is True)
        assert success_count == 1, f"Expected exactly 1 success, got {success_count}"

        # All failures should return the token data with used_at timestamp
        failed_results = [data for marked, data in results if marked is False]
        assert len(failed_results) == num_workers - 1
        for data in failed_results:
            assert data is not None, "Failed attempts should return token data"
            assert data["used"] is True, "Token should be marked as used"
            assert "used_at" in data, "Should include used_at timestamp"

    def test_grace_period_detection(self):
        """
        Test that used_at timestamp enables grace period detection.

        This verifies that the implementation can detect token reuse
        within a short grace period (legitimate concurrent requests)
        vs. token reuse after the grace period (potential theft).
        """
        from actingweb.oauth_session import OAuth2SessionManager

        session_mgr = OAuth2SessionManager(config=self.config)

        # Create and mark a token
        token = f"grace_token_{int(time.time() * 1000000)}"
        token_data = {
            "actor_id": "test_actor",
            "trust_peerid": "test_peer",
            "expires_at": int(time.time()) + 3600,
            "used": False,
        }

        from actingweb.attribute import Attributes
        from actingweb.constants import OAUTH2_SYSTEM_ACTOR

        bucket = Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket="spa_refresh_tokens",
            config=self.config,
        )
        success = bucket.set_attr(name=token, data=token_data)
        assert success

        # Mark it as used
        marked, data = session_mgr.try_mark_refresh_token_used(token)
        assert marked is True
        assert data is not None
        first_used_at = data["used_at"]

        # Immediately try again (simulating concurrent request)
        marked, data = session_mgr.try_mark_refresh_token_used(token)
        assert marked is False
        assert data is not None
        assert "used_at" in data

        # Calculate time difference
        time_diff = int(time.time()) - first_used_at

        # Within 2 seconds = grace period (legitimate concurrent request)
        # Beyond 2 seconds = potential token theft
        # This test just verifies we get the timestamp to enable this check
        assert isinstance(time_diff, int)
        assert time_diff >= 0, "Time difference should be non-negative"


@pytest.mark.integration
class TestStrictConditionalUpdate:
    """``conditional_update_attr(strict=True)`` (4.0.0rc3): a fault raises
    ``DbError``; ``False`` is left to mean "the condition lost".

    The default is unchanged: it answers ``False`` for both, and a caller
    tells them apart with a strict re-read of its own.
    """

    def setup_method(self) -> None:
        from actingweb.attribute import Attributes

        self.config = Config(unique_creator=False)
        self.actor_id = f"cond_strict_{int(time.time() * 1000000)}"
        self.attrs = Attributes(
            actor_id=self.actor_id, bucket="strict_bucket", config=self.config
        )
        assert self.attrs.set_attr(name="row", data={"v": 1})

    def teardown_method(self) -> None:
        try:
            self.config.DbAttribute.DbAttributeBucketList().delete(  # type: ignore
                actor_id=self.actor_id
            )
        except Exception:
            pass

    def _stored(self) -> object:
        from actingweb.db import get_attribute

        row = get_attribute(self.config).get_attr_strict(
            actor_id=self.actor_id, bucket="strict_bucket", name="row"
        )
        return row.get("data") if row else None

    @pytest.mark.parametrize("seam", ["get", "update"])
    def test_strict_raises_on_a_fault(self, seam: str) -> None:
        """AC-16: at the read that precedes the write, and at the write."""
        from actingweb.db.exceptions import DbError
        from tests._adoption_helpers import seam_fault

        with (
            seam_fault(self.config, "attribute", "Attribute", seam),
            pytest.raises(DbError),
        ):
            self.attrs.conditional_update_attr(
                name="row", old_data={"v": 1}, new_data={"v": 2}, strict=True
            )
        assert self._stored() == {"v": 1}

    @pytest.mark.parametrize("seam", ["get", "update"])
    def test_the_default_still_answers_false_on_a_fault(self, seam: str) -> None:
        """AC-18: D10 stands."""
        from tests._adoption_helpers import seam_fault

        with seam_fault(self.config, "attribute", "Attribute", seam):
            assert (
                self.attrs.conditional_update_attr(
                    name="row", old_data={"v": 1}, new_data={"v": 2}
                )
                is False
            )
        assert self._stored() == {"v": 1}

    def test_strict_answers_false_for_a_lost_condition(self) -> None:
        """AC-17: another writer changed the row; nothing is raised."""
        assert (
            self.attrs.conditional_update_attr(
                name="row", old_data={"v": 0}, new_data={"v": 2}, strict=True
            )
            is False
        )
        assert self._stored() == {"v": 1}

    def test_strict_answers_false_for_no_row(self) -> None:
        """AC-17."""
        assert (
            self.attrs.conditional_update_attr(
                name="absent", old_data={"v": 1}, new_data={"v": 2}, strict=True
            )
            is False
        )

    def test_strict_succeeds_as_before(self) -> None:
        assert (
            self.attrs.conditional_update_attr(
                name="row", old_data={"v": 1}, new_data={"v": 2}, strict=True
            )
            is True
        )
        assert self._stored() == {"v": 2}
        assert self.attrs.get_attr(name="row")["data"] == {"v": 2}  # type: ignore[index]

    def test_strict_does_not_claim_another_writers_identical_value(self) -> None:
        """True means THIS call changed the row. A caller that lost to a
        writer of the same value (two increments from one base, a consume
        without a nonce) must not be told it won."""
        from actingweb.db import get_attribute

        assert get_attribute(self.config).conditional_update_attr(
            actor_id=self.actor_id,
            bucket="strict_bucket",
            name="row",
            old_data={"v": 1},
            new_data={"v": 2},
        )
        assert (
            self.attrs.conditional_update_attr(
                name="row", old_data={"v": 1}, new_data={"v": 2}, strict=True
            )
            is False
        )

    def test_a_strict_fault_keeps_its_cause(self) -> None:
        """The backend raises from its own exception, so a fault that a
        retry cannot fix still classifies as permanent."""
        from actingweb.db.exceptions import DbError
        from tests._adoption_helpers import seam_fault

        with (
            seam_fault(self.config, "attribute", "Attribute", "update"),
            pytest.raises(DbError) as raised,
        ):
            self.attrs.conditional_update_attr(
                name="row", old_data={"v": 1}, new_data={"v": 2}, strict=True
            )
        assert isinstance(raised.value.__cause__, RuntimeError)

    def test_strict_compares_as_the_backend_does(self) -> None:
        """No second comparison in Python: a tuple in ``old_data`` matches
        the stored list, as it does without strict."""
        assert self.attrs.set_attr(name="ids", data={"ids": [1, 2]})
        assert (
            self.attrs.conditional_update_attr(
                name="ids",
                old_data={"ids": (1, 2)},
                new_data={"ids": [1, 2, 3]},
                strict=True,
            )
            is True
        )

    def test_a_value_that_cannot_be_compared_is_not_an_outage(self) -> None:
        """A caller's ``old_data`` that JSON cannot order (mixed key types)
        is the caller's error. Strict must not report it as a store fault,
        which would answer 503 and be retried forever."""
        from actingweb.db.exceptions import DbError

        bad: dict[Any, Any] = {1: "a", "b": 2}
        try:
            answer = self.attrs.conditional_update_attr(
                name="row", old_data=bad, new_data={"v": 2}, strict=True
            )
        except DbError:  # pragma: no cover - the defect
            pytest.fail("a value error was reported as a store fault")
        except (TypeError, ValueError):
            return
        assert answer is False

    def test_the_backend_is_passed_the_keyword_only_when_asked(self) -> None:
        """AC-18: a backend written before ``strict`` keeps working for
        every caller that does not ask for it."""
        from unittest.mock import patch

        from actingweb.db import get_attribute

        db = get_attribute(self.config)
        real = db.conditional_update_attr
        seen: list[dict[str, Any]] = []

        def recording(**kwargs: Any) -> bool:
            seen.append(kwargs)
            return real(**kwargs)

        with patch.object(type(db), "conditional_update_attr", staticmethod(recording)):
            for strict in (False, True):
                assert (
                    self.attrs.conditional_update_attr(
                        name="row",
                        old_data={"v": 0},
                        new_data={"v": 2},
                        strict=strict,
                    )
                    is False
                )
        assert "strict" not in seen[0]
        assert seen[1]["strict"] is True
