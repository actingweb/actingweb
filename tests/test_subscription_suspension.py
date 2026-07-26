"""Unit tests for Subscription Suspension functionality."""

from unittest.mock import MagicMock, patch

import pytest
from pynamodb.exceptions import DoesNotExist


class TestSubscriptionSuspensionDynamoDB:
    """Test DynamoDB subscription suspension operations."""

    @pytest.fixture
    def mock_model(self):
        """Create mock PynamoDB model."""
        with patch(
            "actingweb.db.dynamodb.subscription_suspension.SubscriptionSuspension"
        ) as mock:
            yield mock

    def test_is_suspended_returns_true_when_exists(self, mock_model):
        """Test is_suspended returns True when suspension record exists.

        The subtarget path queries this target's keys rather than fetching
        one composite key, so a target-level suspension also cascades — see
        test_target_suspension_cascades_to_subtargets.
        """
        from actingweb.db.dynamodb.subscription_suspension import (
            DbSubscriptionSuspension,
        )

        mock_model.query.return_value = [MagicMock(target_key="properties:email")]

        db = DbSubscriptionSuspension("actor123")
        result = db.is_suspended("properties", "email")

        assert result is True
        assert mock_model.query.call_args[0][0] == "actor123"

    def test_is_suspended_returns_false_when_not_exists(self, mock_model):
        """Test is_suspended returns False when no suspension record."""
        from actingweb.db.dynamodb.subscription_suspension import (
            DbSubscriptionSuspension,
        )

        mock_model.query.return_value = []

        db = DbSubscriptionSuspension("actor123")
        result = db.is_suspended("properties", "email")

        assert result is False

    def test_is_suspended_target_only_uses_a_point_read(self, mock_model):
        """No subtarget means no cascade to consider — keep it a GetItem."""
        from actingweb.db.dynamodb.subscription_suspension import (
            DbSubscriptionSuspension,
        )

        mock_model.get.return_value = MagicMock()

        db = DbSubscriptionSuspension("actor123")

        assert db.is_suspended("properties") is True
        mock_model.get.assert_called_once_with("actor123", "properties")
        mock_model.query.assert_not_called()

    def test_suspend_creates_record(self, mock_model):
        """Test suspend creates suspension record."""
        from actingweb.db.dynamodb.subscription_suspension import (
            DbSubscriptionSuspension,
        )

        # First call to is_suspended returns False (not suspended)
        mock_model.get.side_effect = DoesNotExist()

        db = DbSubscriptionSuspension("actor123")
        result = db.suspend("properties", "email")

        assert result is True
        # Verify SubscriptionSuspension was instantiated and saved
        assert mock_model.call_count >= 1

    def test_suspend_returns_false_when_already_suspended(self, mock_model):
        """Test suspend returns False when already suspended."""
        from actingweb.db.dynamodb.subscription_suspension import (
            DbSubscriptionSuspension,
        )

        # First call to is_suspended returns True (already suspended)
        mock_model.get.return_value = MagicMock()

        db = DbSubscriptionSuspension("actor123")
        result = db.suspend("properties", "email")

        assert result is False

    def test_resume_deletes_record(self, mock_model):
        """Test resume deletes suspension record."""
        from actingweb.db.dynamodb.subscription_suspension import (
            DbSubscriptionSuspension,
        )

        # Setup mock to return and delete
        mock_suspension = MagicMock()
        mock_model.get.return_value = mock_suspension

        db = DbSubscriptionSuspension("actor123")
        result = db.resume("properties", "email")

        assert result is True
        mock_suspension.delete.assert_called_once()

    def test_resume_returns_false_when_not_suspended(self, mock_model):
        """Test resume returns False when not suspended."""
        from actingweb.db.dynamodb.subscription_suspension import (
            DbSubscriptionSuspension,
        )

        # Setup mock to raise DoesNotExist
        mock_model.get.side_effect = DoesNotExist()

        db = DbSubscriptionSuspension("actor123")
        result = db.resume("properties", "email")

        assert result is False

    def test_get_all_suspended(self, mock_model):
        """Test get_all_suspended returns all suspension records."""
        from actingweb.db.dynamodb.subscription_suspension import (
            DbSubscriptionSuspension,
        )

        # Setup mock to return multiple records
        mock_record1 = MagicMock(target="properties", subtarget="email")
        mock_record2 = MagicMock(target="properties", subtarget=None)
        mock_model.query.return_value = [mock_record1, mock_record2]

        db = DbSubscriptionSuspension("actor123")
        result = db.get_all_suspended()

        assert result == [("properties", "email"), ("properties", None)]
        mock_model.query.assert_called_once_with("actor123")

    def test_target_suspension_cascades_to_subtargets(self, mock_model):
        """Suspending a target must suppress writes to its subtargets.

        PropertyStore registers every diff with the property name as the
        subtarget, so an exact-match-only check meant
        suspend_subscriptions("properties") — the documented bulk-import
        usage — silently suppressed nothing at all.
        """
        from actingweb.db.dynamodb.subscription_suspension import (
            DbSubscriptionSuspension,
        )

        # Only the target-level row exists.
        target_row = MagicMock(target_key="properties")
        mock_model.query.return_value = [target_row]

        db = DbSubscriptionSuspension("actor123")

        assert db.is_suspended("properties", "email") is True
        assert db.is_suspended("properties", "any_other_name") is True

    def test_cascade_does_not_match_sibling_target_prefixes(self, mock_model):
        """begins_with matches prefixes; the comparison must be exact."""
        from actingweb.db.dynamodb.subscription_suspension import (
            DbSubscriptionSuspension,
        )

        # "properties_v2" shares the "properties" prefix but is a different
        # target and must not suspend it.
        mock_model.query.return_value = [MagicMock(target_key="properties_v2")]

        db = DbSubscriptionSuspension("actor123")

        assert db.is_suspended("properties", "email") is False

    def test_suspend_records_subtarget_under_suspended_target(self, mock_model):
        """A specific suspension must persist even if the target is suspended.

        Otherwise resuming the target silently lifts a suspension the caller
        requested separately.
        """
        from actingweb.db.dynamodb.subscription_suspension import (
            DbSubscriptionSuspension,
        )

        # Target-level row exists (cascade would say "already suspended")...
        mock_model.query.return_value = [MagicMock(target_key="properties")]
        # ...but the exact composite key does not.
        mock_model.get.side_effect = DoesNotExist()

        db = DbSubscriptionSuspension("actor123")

        assert db.suspend("properties", "email") is True
        assert mock_model.call_count >= 1, "the subtarget row must be written"

    def test_target_key_without_subtarget(self, mock_model):
        """Test target key is just target when no subtarget."""
        from actingweb.db.dynamodb.subscription_suspension import (
            DbSubscriptionSuspension,
        )

        mock_model.get.side_effect = DoesNotExist()

        db = DbSubscriptionSuspension("actor123")
        db.is_suspended("properties", None)

        # Should use just "properties" as the key
        mock_model.get.assert_called_once_with("actor123", "properties")


class TestSubscriptionSuspensionPostgreSQL:
    """Test PostgreSQL subscription suspension operations."""

    @pytest.fixture
    def mock_connection(self):
        """Create mock PostgreSQL connection."""
        with patch(
            "actingweb.db.postgresql.subscription_suspension.get_connection"
        ) as mock:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn.cursor.return_value.__enter__ = MagicMock(
                return_value=mock_cursor
            )
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock.return_value = mock_conn
            yield mock, mock_conn, mock_cursor

    def test_is_suspended_returns_true(self, mock_connection):
        """Test is_suspended returns True when record exists."""
        from actingweb.db.postgresql.subscription_suspension import (
            DbSubscriptionSuspension,
        )

        _, _, mock_cursor = mock_connection
        mock_cursor.fetchone.return_value = (1,)

        db = DbSubscriptionSuspension("actor123")
        result = db.is_suspended("properties", "email")

        assert result is True

    def test_is_suspended_returns_false(self, mock_connection):
        """Test is_suspended returns False when no record."""
        from actingweb.db.postgresql.subscription_suspension import (
            DbSubscriptionSuspension,
        )

        _, _, mock_cursor = mock_connection
        mock_cursor.fetchone.return_value = None

        db = DbSubscriptionSuspension("actor123")
        result = db.is_suspended("properties", "email")

        assert result is False

    def test_target_suspension_cascades_to_subtargets(self, mock_connection):
        """PostgreSQL must agree with DynamoDB on the cascade."""
        from actingweb.db.postgresql.subscription_suspension import (
            DbSubscriptionSuspension,
        )

        _, _, mock_cursor = mock_connection
        mock_cursor.fetchone.return_value = (1,)

        db = DbSubscriptionSuspension("actor123")
        assert db.is_suspended("properties", "email") is True

        # The query must accept the target-level row (subtarget '') as a match.
        sql = mock_cursor.execute.call_args[0][0]
        assert "IN (%s, '')" in sql, "target-level suspension is not considered"

    def test_suspend_inserts_record(self, mock_connection):
        """Test suspend inserts a record."""
        from actingweb.db.postgresql.subscription_suspension import (
            DbSubscriptionSuspension,
        )

        _, mock_conn, mock_cursor = mock_connection
        # First fetchone returns None (not suspended), then insert succeeds
        mock_cursor.fetchone.return_value = None

        db = DbSubscriptionSuspension("actor123")
        result = db.suspend("properties", "email")

        assert result is True
        mock_conn.commit.assert_called()

    def test_resume_deletes_record(self, mock_connection):
        """Test resume deletes the record."""
        from actingweb.db.postgresql.subscription_suspension import (
            DbSubscriptionSuspension,
        )

        _, mock_conn, mock_cursor = mock_connection
        mock_cursor.rowcount = 1

        db = DbSubscriptionSuspension("actor123")
        result = db.resume("properties", "email")

        assert result is True
        mock_conn.commit.assert_called()

    def test_resume_returns_false_when_not_found(self, mock_connection):
        """Test resume returns False when no record to delete."""
        from actingweb.db.postgresql.subscription_suspension import (
            DbSubscriptionSuspension,
        )

        _, _, mock_cursor = mock_connection
        mock_cursor.rowcount = 0

        db = DbSubscriptionSuspension("actor123")
        result = db.resume("properties", "email")

        assert result is False


class TestActorSuspensionMethods:
    """Test Actor class suspension methods."""

    @pytest.fixture
    def mock_actor(self):
        """Create a mock Actor with config."""
        actor = MagicMock()
        actor.id = "actor123"
        actor.config = MagicMock()
        actor.config.proto = "https://"
        actor.config.fqdn = "test.example.com"

        # Setup DbSubscriptionSuspension mock
        mock_db = MagicMock()
        actor.config.DbSubscriptionSuspension.DbSubscriptionSuspension.return_value = (
            mock_db
        )

        return actor, mock_db

    def test_is_subscription_suspended_delegates_to_db(self, mock_actor):
        """Test is_subscription_suspended delegates to DB."""
        from actingweb.actor import Actor

        actor, mock_db = mock_actor
        mock_db.is_suspended.return_value = True

        # Create real Actor instance with mocked config
        real_actor = Actor.__new__(Actor)
        real_actor.id = "actor123"
        real_actor.config = actor.config

        result = real_actor.is_subscription_suspended("properties", "email")

        assert result is True
        mock_db.is_suspended.assert_called_once_with("properties", "email")

    def test_is_subscription_suspended_logs_operational_errors(
        self, mock_actor, caplog
    ):
        """A failed suspension check must not look like 'not suspended'.

        With the suspensions table missing (pynamodb raises TableDoesNotExist,
        which is NOT DoesNotExist) or the read denied, every target reads as
        un-suspended: a bulk import's suspend() silently no-ops and per-item
        callbacks fire anyway. The call still degrades to False, but it has to
        be loud about it — rate-limited, since register_diffs() calls this on
        every property write.
        """
        import logging
        import time

        from pynamodb.exceptions import TableDoesNotExist

        from actingweb import actor as actor_module
        from actingweb.actor import Actor

        actor, mock_db = mock_actor
        mock_db.is_suspended.side_effect = TableDoesNotExist("demo_suspensions")

        real_actor = Actor.__new__(Actor)
        real_actor.id = "actor123"
        real_actor.config = actor.config

        # The ERROR is rate-limited per process — clear the window so this
        # test does not depend on being the first failure in the run.
        original = actor_module._suspension_check_error_logged_at
        actor_module._suspension_check_error_logged_at = None
        try:
            with caplog.at_level(logging.DEBUG, logger="actingweb.actor"):
                result = real_actor.is_subscription_suspended("properties", "email")
                errors = [r for r in caplog.records if r.levelno >= logging.ERROR]

                # Inside the window, a repeat must not re-log at ERROR.
                caplog.clear()
                repeat = real_actor.is_subscription_suspended("properties", "email")
                repeat_errors = [
                    r for r in caplog.records if r.levelno >= logging.ERROR
                ]
                throttled_records = list(caplog.records)

                # Once the window elapses it must speak up again: a warm
                # container can outlive the incident, and "once ever" would
                # report a broken table one time and then stay silent.
                caplog.clear()
                actor_module._suspension_check_error_logged_at = (
                    time.monotonic()
                    - actor_module._SUSPENSION_ERROR_LOG_INTERVAL_SECONDS
                    - 1
                )
                real_actor.is_subscription_suspended("properties", "email")
                rearmed_errors = [
                    r for r in caplog.records if r.levelno >= logging.ERROR
                ]
        finally:
            actor_module._suspension_check_error_logged_at = original

        assert result is False
        assert repeat is False
        assert errors, "operational failure was swallowed below ERROR"
        assert "actor123" in errors[0].getMessage()
        assert "verify_tables" in errors[0].getMessage()
        assert not repeat_errors, "repeated failures must not flood at ERROR"
        assert throttled_records, "throttled failures should still reach DEBUG"
        assert rearmed_errors, "ERROR must re-arm after the window elapses"

    def test_register_diffs_skips_suspension_check_without_subscriptions(
        self, mock_actor
    ):
        """No subscriptions on the target means no suspension read at all.

        register_diffs() runs on every property write. The subscription list
        is cached on the actor; the suspension check is an uncached GetItem.
        With nothing to notify, both paths end in the same no-op, so the
        suspension check must not cost a database round trip per write.
        """
        from actingweb.actor import Actor

        actor, _ = mock_actor

        real_actor = Actor.__new__(Actor)
        real_actor.id = "actor123"
        real_actor.config = actor.config
        real_actor.get_subscriptions = MagicMock(return_value=[])
        real_actor.is_subscription_suspended = MagicMock(return_value=False)

        real_actor.register_diffs(target="properties", subtarget="email", blob="{}")

        real_actor.is_subscription_suspended.assert_not_called()

    def test_register_diffs_checks_suspension_when_subscriptions_exist(
        self, mock_actor
    ):
        """With subscribers present, suspension still short-circuits."""
        from actingweb.actor import Actor

        actor, _ = mock_actor

        real_actor = Actor.__new__(Actor)
        real_actor.id = "actor123"
        real_actor.config = actor.config
        real_actor.get_subscriptions = MagicMock(
            return_value=[
                {
                    "peerid": "peer1",
                    "subscriptionid": "sub1",
                    "subtarget": "email",
                    "resource": None,
                }
            ]
        )
        real_actor.is_subscription_suspended = MagicMock(return_value=True)
        real_actor.get_subscription_obj = MagicMock()

        real_actor.register_diffs(target="properties", subtarget="email", blob="{}")

        real_actor.is_subscription_suspended.assert_called_once_with(
            "properties", "email"
        )
        # Suspended: no diff is registered against the subscription.
        real_actor.get_subscription_obj.assert_not_called()

    def test_create_subscription_invalidates_the_cached_list(self, mock_actor):
        """A subscription created mid-instance must be visible to register_diffs.

        Goes through the REAL get_subscriptions() caching path, not a mock of
        it: the bug was that `subs_list` stayed populated after a create, so
        the new subscription silently received no diffs. Mocking
        get_subscriptions() would hide exactly that.
        """
        from actingweb.actor import Actor

        actor, _ = mock_actor

        real_actor = Actor.__new__(Actor)
        real_actor.id = "actor123"
        real_actor.config = actor.config
        # Pre-populate the cache the way a prior read would have.
        real_actor.subs_list = [
            {
                "peerid": "peer1",
                "subscriptionid": "sub1",
                "target": "properties",
                "subtarget": None,
                "resource": None,
                "callback": False,
            }
        ]

        with patch("actingweb.actor.subscription.Subscription") as mock_sub_cls:
            mock_sub_cls.return_value.get.return_value = {"subscriptionid": "sub2"}
            real_actor.create_subscription(peerid="peer2", target="properties")

        assert real_actor.subs_list is None, (
            "create_subscription() must invalidate the cached list, or "
            "register_diffs() never sees the new subscription"
        )

    def test_suspend_subscriptions_delegates_to_db(self, mock_actor):
        """Test suspend_subscriptions delegates to DB."""
        from actingweb.actor import Actor

        actor, mock_db = mock_actor
        mock_db.suspend.return_value = True

        real_actor = Actor.__new__(Actor)
        real_actor.id = "actor123"
        real_actor.config = actor.config

        result = real_actor.suspend_subscriptions("properties", "email")

        assert result is True
        mock_db.suspend.assert_called_once_with("properties", "email")

    def test_resume_subscriptions_sends_resync(self, mock_actor):
        """Test resume_subscriptions sends resync callbacks."""
        from actingweb.actor import Actor

        actor, mock_db = mock_actor
        mock_db.resume.return_value = True

        real_actor = Actor.__new__(Actor)
        real_actor.id = "actor123"
        real_actor.config = actor.config

        # Mock get_subscriptions to return no subscriptions
        real_actor.get_subscriptions = MagicMock(return_value=[])

        result = real_actor.resume_subscriptions("properties", "email")

        assert result == 0
        mock_db.resume.assert_called_once_with("properties", "email")

    def test_resume_subscriptions_returns_zero_if_not_suspended(self, mock_actor):
        """Test resume_subscriptions returns 0 if not suspended."""
        from actingweb.actor import Actor

        actor, mock_db = mock_actor
        mock_db.resume.return_value = False  # Not suspended

        real_actor = Actor.__new__(Actor)
        real_actor.id = "actor123"
        real_actor.config = actor.config

        result = real_actor.resume_subscriptions("properties", "email")

        assert result == 0


class TestSubscriptionManagerSuspension:
    """Test SubscriptionManager suspend/resume methods."""

    @pytest.fixture
    def mock_manager(self):
        """Create a mock SubscriptionManager."""
        from actingweb.interface.subscription_manager import SubscriptionManager

        mock_actor = MagicMock()
        mock_actor.suspend_subscriptions.return_value = True
        mock_actor.resume_subscriptions.return_value = 5
        mock_actor.is_subscription_suspended.return_value = False

        manager = SubscriptionManager.__new__(SubscriptionManager)
        manager._core_actor = mock_actor
        return manager, mock_actor

    def test_suspend_delegates_to_actor(self, mock_manager):
        """Test suspend() delegates to core actor."""
        manager, mock_actor = mock_manager

        result = manager.suspend("properties", "email")

        assert result is True
        mock_actor.suspend_subscriptions.assert_called_once_with("properties", "email")

    def test_resume_delegates_to_actor(self, mock_manager):
        """Test resume() delegates to core actor."""
        manager, mock_actor = mock_manager

        result = manager.resume("properties", "email")

        assert result == 5
        mock_actor.resume_subscriptions.assert_called_once_with("properties", "email")

    def test_is_suspended_delegates_to_actor(self, mock_manager):
        """Test is_suspended() delegates to core actor."""
        manager, mock_actor = mock_manager

        result = manager.is_suspended("properties", "email")

        assert result is False
        mock_actor.is_subscription_suspended.assert_called_once_with(
            "properties", "email"
        )
