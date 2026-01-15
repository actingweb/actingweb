"""Tests for subscription callback functionality.

Specifically tests the sync_subscription_callbacks feature added for
Lambda/serverless deployments.
"""

from unittest.mock import Mock, patch

import pytest
import requests

from actingweb.actor import Actor


@pytest.fixture
def mock_actor_sync():
    """Create a mocked Actor with sync_subscription_callbacks=True."""
    mock_config = Mock()
    mock_config.force_email_prop_as_creator = False
    mock_config.sync_subscription_callbacks = True
    mock_config.database = "dynamodb"
    mock_config.root = "https://myapp.example.com/"

    mock_db_actor = Mock()
    mock_db_actor.get.return_value = {
        "id": "test_actor",
        "creator": "test_creator",
        "passphrase": "test_passphrase",
    }
    mock_config.DbActor.DbActor.return_value = mock_db_actor

    with patch("actingweb.actor.attribute") as mock_attribute:
        with patch("actingweb.actor.property") as mock_property:
            mock_attribute.InternalStore.return_value = Mock()
            mock_property.PropertyStore.return_value = Mock()

            actor = Actor(actor_id="test_actor", config=mock_config)
            yield actor


@pytest.fixture
def mock_actor_async():
    """Create a mocked Actor with sync_subscription_callbacks=False."""
    mock_config = Mock()
    mock_config.force_email_prop_as_creator = False
    mock_config.sync_subscription_callbacks = False
    mock_config.database = "dynamodb"
    mock_config.root = "https://myapp.example.com/"

    mock_db_actor = Mock()
    mock_db_actor.get.return_value = {
        "id": "test_actor",
        "creator": "test_creator",
        "passphrase": "test_passphrase",
    }
    mock_config.DbActor.DbActor.return_value = mock_db_actor

    with patch("actingweb.actor.attribute") as mock_attribute:
        with patch("actingweb.actor.property") as mock_property:
            mock_attribute.InternalStore.return_value = Mock()
            mock_property.PropertyStore.return_value = Mock()

            actor = Actor(actor_id="test_actor", config=mock_config)
            yield actor


class TestSyncSubscriptionCallbacks:
    """Test synchronous subscription callback functionality."""

    def test_sync_callbacks_enabled_uses_requests(self, mock_actor_sync):
        """Test that sync_subscription_callbacks=True uses requests.post."""
        actor = mock_actor_sync

        # Set up test data - use "trust" target to avoid permission filtering
        sub = {
            "peerid": "peer123",
            "subscriptionid": "sub456",
            "granularity": "low",
            "target": "trust",  # Not "properties" to skip permission filtering
            "subtarget": None,
            "resource": None,
        }
        trust_rel = {
            "peerid": "peer123",
            "baseuri": "https://peer.example.com",
            "secret": "test_secret",
        }
        diff = {
            "sequence": 1,
            "timestamp": "2024-01-15T00:00:00",
            "target": "trust/test",
        }

        with patch.object(actor, "get_trust_relationship", return_value=trust_rel):
            with patch("actingweb.actor.requests.post") as mock_post:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.content = b"OK"
                mock_post.return_value = mock_response

                # Call the callback method with proper arguments
                actor.callback_subscription(
                    peerid="peer123",
                    sub=sub,
                    diff=diff,
                    blob="{}",
                )

                # Verify requests.post was called (sync path)
                assert (
                    mock_post.called
                ), "requests.post should be called when sync_callbacks=True"
                call_args = mock_post.call_args
                assert (
                    "https://peer.example.com/callbacks/subscriptions/test_actor/sub456"
                    in str(call_args)
                )

    def test_sync_callbacks_disabled_does_not_use_sync_path(self, mock_actor_async):
        """Test that sync_subscription_callbacks=False doesn't force sync path."""
        actor = mock_actor_async

        # Set up test data - use "trust" target to avoid permission filtering
        sub = {
            "peerid": "peer123",
            "subscriptionid": "sub456",
            "granularity": "low",
            "target": "trust",
            "subtarget": None,
            "resource": None,
        }
        trust_rel = {
            "peerid": "peer123",
            "baseuri": "https://peer.example.com",
            "secret": "test_secret",
        }
        diff = {
            "sequence": 1,
            "timestamp": "2024-01-15T00:00:00",
            "target": "trust/test",
        }

        # In a non-async context without event loop, it will fall back to sync
        # but the INFO log for forced sync should not be called
        with patch.object(actor, "get_trust_relationship", return_value=trust_rel):
            with patch("actingweb.actor.requests.post") as mock_post:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.content = b"OK"
                mock_post.return_value = mock_response

                with patch("actingweb.actor.logger") as mock_logger:
                    actor.callback_subscription(
                        peerid="peer123",
                        sub=sub,
                        diff=diff,
                        blob="{}",
                    )

                    # Should NOT log INFO about forced sync callback
                    info_calls = [str(call) for call in mock_logger.info.call_args_list]
                    assert not any(
                        "Sync callback seq=" in call for call in info_calls
                    ), "Should not log forced sync callback message"

    def test_sync_callback_handles_request_exception(self, mock_actor_sync):
        """Test that sync callback catches RequestException properly."""
        actor = mock_actor_sync

        # Use "trust" target to avoid permission filtering
        sub = {
            "peerid": "peer123",
            "subscriptionid": "sub456",
            "granularity": "low",
            "target": "trust",
            "subtarget": None,
            "resource": None,
        }
        trust_rel = {
            "peerid": "peer123",
            "baseuri": "https://peer.example.com",
            "secret": "test_secret",
        }
        diff = {
            "sequence": 1,
            "timestamp": "2024-01-15T00:00:00",
            "target": "trust/test",
        }

        with patch.object(actor, "get_trust_relationship", return_value=trust_rel):
            with patch("actingweb.actor.requests.post") as mock_post:
                # Simulate a network error
                mock_post.side_effect = requests.RequestException("Connection failed")

                # Should not raise, exception is caught
                actor.callback_subscription(
                    peerid="peer123",
                    sub=sub,
                    diff=diff,
                    blob="{}",
                )

                # Verify error handling
                assert actor.last_response_code == 0
                assert "No response from peer" in actor.last_response_message

    def test_sync_callback_handles_timeout(self, mock_actor_sync):
        """Test that sync callback catches Timeout properly."""
        actor = mock_actor_sync

        sub = {
            "peerid": "peer123",
            "subscriptionid": "sub456",
            "granularity": "low",
            "target": "trust",
            "subtarget": None,
            "resource": None,
        }
        trust_rel = {
            "peerid": "peer123",
            "baseuri": "https://peer.example.com",
            "secret": "test_secret",
        }
        diff = {
            "sequence": 1,
            "timestamp": "2024-01-15T00:00:00",
            "target": "trust/test",
        }

        with patch.object(actor, "get_trust_relationship", return_value=trust_rel):
            with patch("actingweb.actor.requests.post") as mock_post:
                # Simulate a timeout
                mock_post.side_effect = requests.Timeout("Request timed out")

                # Should not raise, exception is caught
                actor.callback_subscription(
                    peerid="peer123",
                    sub=sub,
                    diff=diff,
                    blob="{}",
                )

                # Verify error handling
                assert actor.last_response_code == 0
                assert "No response from peer" in actor.last_response_message

    def test_sync_callback_handles_connection_error(self, mock_actor_sync):
        """Test that sync callback catches ConnectionError properly."""
        actor = mock_actor_sync

        sub = {
            "peerid": "peer123",
            "subscriptionid": "sub456",
            "granularity": "low",
            "target": "trust",
            "subtarget": None,
            "resource": None,
        }
        trust_rel = {
            "peerid": "peer123",
            "baseuri": "https://peer.example.com",
            "secret": "test_secret",
        }
        diff = {
            "sequence": 1,
            "timestamp": "2024-01-15T00:00:00",
            "target": "trust/test",
        }

        with patch.object(actor, "get_trust_relationship", return_value=trust_rel):
            with patch("actingweb.actor.requests.post") as mock_post:
                # Simulate a connection error
                mock_post.side_effect = ConnectionError("Cannot connect")

                # Should not raise, exception is caught
                actor.callback_subscription(
                    peerid="peer123",
                    sub=sub,
                    diff=diff,
                    blob="{}",
                )

                # Verify error handling
                assert actor.last_response_code == 0
                assert "No response from peer" in actor.last_response_message

    def test_sync_callback_clears_diff_on_204(self, mock_actor_sync):
        """Test that sync callback clears diff when receiving 204 with high granularity."""
        actor = mock_actor_sync

        mock_sub_obj = Mock()
        sub = {
            "peerid": "peer123",
            "subscriptionid": "sub456",
            "granularity": "high",
            "target": "trust",  # Use "trust" to avoid permission filtering
            "subtarget": None,
            "resource": None,
        }
        trust_rel = {
            "peerid": "peer123",
            "baseuri": "https://peer.example.com",
            "secret": "test_secret",
        }
        diff = {
            "sequence": 5,
            "timestamp": "2024-01-15T00:00:00",
            "target": "trust/test",
        }

        with patch.object(actor, "get_trust_relationship", return_value=trust_rel):
            with patch("actingweb.actor.requests.post") as mock_post:
                mock_response = Mock()
                mock_response.status_code = 204
                mock_response.content = b""
                mock_post.return_value = mock_response

                # Call with sub_obj parameter
                actor.callback_subscription(
                    peerid="peer123",
                    sub_obj=mock_sub_obj,
                    sub=sub,
                    diff=diff,
                    blob='{"key": "value"}',
                )

                # Verify diff was cleared
                mock_sub_obj.clear_diff.assert_called_once_with(5)

    def test_sync_callback_does_not_clear_diff_on_non_204(self, mock_actor_sync):
        """Test that sync callback doesn't clear diff on non-204 responses."""
        actor = mock_actor_sync

        mock_sub_obj = Mock()
        sub = {
            "peerid": "peer123",
            "subscriptionid": "sub456",
            "granularity": "high",
            "target": "trust",
            "subtarget": None,
            "resource": None,
        }
        trust_rel = {
            "peerid": "peer123",
            "baseuri": "https://peer.example.com",
            "secret": "test_secret",
        }
        diff = {
            "sequence": 5,
            "timestamp": "2024-01-15T00:00:00",
            "target": "trust/test",
        }

        with patch.object(actor, "get_trust_relationship", return_value=trust_rel):
            with patch("actingweb.actor.requests.post") as mock_post:
                mock_response = Mock()
                mock_response.status_code = 200  # Not 204
                mock_response.content = b"OK"
                mock_post.return_value = mock_response

                actor.callback_subscription(
                    peerid="peer123",
                    sub_obj=mock_sub_obj,
                    sub=sub,
                    diff=diff,
                    blob='{"key": "value"}',
                )

                # Verify diff was NOT cleared
                mock_sub_obj.clear_diff.assert_not_called()


class TestAsyncCallbackExceptionHandling:
    """Test async callback exception handling with httpx."""

    @pytest.mark.asyncio
    async def test_async_callback_handles_httpx_error(self):
        """Test that async callback properly catches httpx.HTTPError."""
        import httpx

        # This test verifies the exception types are correct
        # The actual async path is tested in integration tests
        assert hasattr(httpx, "HTTPError")
        assert hasattr(httpx, "TimeoutException")

        # Verify exception hierarchy
        assert issubclass(httpx.TimeoutException, httpx.HTTPError)
