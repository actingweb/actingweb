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
        """Test is_suspended returns True when suspension record exists."""
        from actingweb.db.dynamodb.subscription_suspension import (
            DbSubscriptionSuspension,
        )

        # Setup mock to return a record
        mock_model.get.return_value = MagicMock()

        db = DbSubscriptionSuspension("actor123")
        result = db.is_suspended("properties", "email")

        assert result is True
        mock_model.get.assert_called_once_with("actor123", "properties:email")

    def test_is_suspended_returns_false_when_not_exists(self, mock_model):
        """Test is_suspended returns False when no suspension record."""
        from actingweb.db.dynamodb.subscription_suspension import (
            DbSubscriptionSuspension,
        )

        # Setup mock to raise DoesNotExist
        mock_model.get.side_effect = DoesNotExist()

        db = DbSubscriptionSuspension("actor123")
        result = db.is_suspended("properties", "email")

        assert result is False

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
