"""Tests for subscription permission filtering in callbacks."""

import json
from unittest.mock import Mock, patch

from actingweb.actor import Actor
from actingweb.permission_evaluator import PermissionResult


class TestSubscriptionPermissionFiltering:
    """Test suite for _filter_subscription_data_by_permissions method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_config = Mock()
        self.mock_config.database = Mock()
        self.mock_config.root = "http://localhost"

    def test_filter_removes_excluded_properties(self):
        """Subscription callbacks should respect excluded_patterns."""
        actor = Actor(config=self.mock_config)
        actor.id = "test-actor-id"

        blob = json.dumps({
            "data_public": {"info": "public data"},
            "data_private": {"info": "private data"},
            "data_work": {"info": "work data"},
        })

        with patch("actingweb.actor.get_permission_evaluator") as mock_get_eval:
            mock_evaluator = Mock()
            mock_get_eval.return_value = mock_evaluator

            # data_public and data_work allowed, data_private denied
            def side_effect(actor_id, peer_id, property_path, operation):
                if "private" in property_path:
                    return PermissionResult.DENIED
                return PermissionResult.ALLOWED

            mock_evaluator.evaluate_property_access.side_effect = side_effect

            result = actor._filter_subscription_data_by_permissions(
                peerid="peer-123",
                blob=blob,
                subtarget=None,
            )

            assert result is not None
            result_data = json.loads(result)
            assert "data_public" in result_data
            assert "data_work" in result_data
            assert "data_private" not in result_data

    def test_filter_returns_none_when_all_denied(self):
        """Filter returns None when no properties are permitted."""
        actor = Actor(config=self.mock_config)
        actor.id = "test-actor-id"

        blob = json.dumps({"data_private": {"info": "private data"}})

        with patch("actingweb.actor.get_permission_evaluator") as mock_get_eval:
            mock_evaluator = Mock()
            mock_get_eval.return_value = mock_evaluator
            mock_evaluator.evaluate_property_access.return_value = PermissionResult.DENIED

            result = actor._filter_subscription_data_by_permissions(
                peerid="peer-123",
                blob=blob,
            )

            assert result is None

    def test_filter_fails_closed_on_error(self):
        """Filter returns None (fail-closed) when permission check fails."""
        actor = Actor(config=self.mock_config)
        actor.id = "test-actor-id"

        blob = json.dumps({"data_public": {"info": "some data"}})

        with patch("actingweb.actor.get_permission_evaluator") as mock_get_eval:
            mock_evaluator = Mock()
            mock_get_eval.return_value = mock_evaluator
            mock_evaluator.evaluate_property_access.side_effect = Exception("DB error")

            result = actor._filter_subscription_data_by_permissions(
                peerid="peer-123",
                blob=blob,
            )

            assert result is None

    def test_filter_fails_closed_when_no_evaluator(self):
        """Filter returns None when permission evaluator is not available."""
        actor = Actor(config=self.mock_config)
        actor.id = "test-actor-id"

        blob = json.dumps({"data_public": {"info": "some data"}})

        with patch("actingweb.actor.get_permission_evaluator") as mock_get_eval:
            mock_get_eval.return_value = None

            result = actor._filter_subscription_data_by_permissions(
                peerid="peer-123",
                blob=blob,
            )

            assert result is None

    def test_filter_includes_subtarget_in_path(self):
        """Filter builds correct property path with subtarget."""
        actor = Actor(config=self.mock_config)
        actor.id = "test-actor-id"

        blob = json.dumps({"item1": {"data": "info"}})

        with patch("actingweb.actor.get_permission_evaluator") as mock_get_eval:
            mock_evaluator = Mock()
            mock_get_eval.return_value = mock_evaluator
            mock_evaluator.evaluate_property_access.return_value = PermissionResult.ALLOWED

            actor._filter_subscription_data_by_permissions(
                peerid="peer-123",
                blob=blob,
                subtarget="data_public",
            )

            # Verify the property path includes subtarget
            mock_evaluator.evaluate_property_access.assert_called_with(
                "test-actor-id",
                "peer-123",
                "data_public/item1",
                operation="read",
            )

    def test_filter_fails_closed_when_no_actor_id(self):
        """Filter returns None when actor ID is missing."""
        actor = Actor(config=self.mock_config)
        actor.id = None  # No actor ID

        blob = json.dumps({"data_public": {"info": "some data"}})

        result = actor._filter_subscription_data_by_permissions(
            peerid="peer-123",
            blob=blob,
        )

        assert result is None

    def test_filter_handles_non_dict_data(self):
        """Filter passes through non-dict data unchanged."""
        actor = Actor(config=self.mock_config)
        actor.id = "test-actor-id"

        # Non-dict blob
        blob = json.dumps(["item1", "item2"])

        with patch("actingweb.actor.get_permission_evaluator") as mock_get_eval:
            mock_evaluator = Mock()
            mock_get_eval.return_value = mock_evaluator

            result = actor._filter_subscription_data_by_permissions(
                peerid="peer-123",
                blob=blob,
            )

            # Should return the blob as-is
            assert result == blob


class TestCallbackSubscriptionFiltering:
    """Test that callback_subscription integrates permission filtering."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_config = Mock()
        self.mock_config.database = Mock()
        self.mock_config.root = "http://localhost"
        self.mock_config.module = {"deferred": None}

    def test_callback_filters_property_subscriptions(self):
        """callback_subscription should filter data for property subscriptions."""
        actor = Actor(config=self.mock_config)
        actor.id = "test-actor-id"

        # Mock the trust relationship
        with patch.object(actor, "get_trust_relationship") as mock_get_trust:
            mock_get_trust.return_value = {
                "baseuri": "http://peer.example.com",
                "peerid": "peer-123",
                "secret": "secret123",
            }

            # Mock the filter method
            with patch.object(actor, "_filter_subscription_data_by_permissions") as mock_filter:
                mock_filter.return_value = None  # Simulate all data filtered out

                # Mock requests.post to verify it's not called
                with patch("actingweb.actor.requests.post") as mock_post:
                    actor.callback_subscription(
                        peerid="peer-123",
                        sub_obj=Mock(),
                        sub={"target": "properties", "subscriptionid": "sub-1", "granularity": "high", "subtarget": None, "resource": None},
                        diff={"sequence": 1, "timestamp": "2024-01-01T00:00:00Z"},
                        blob='{"data_private": {}}',
                    )

                    # Filter was called
                    mock_filter.assert_called_once()

                    # HTTP request was NOT made because filter returned None
                    mock_post.assert_not_called()

    def test_callback_skips_filtering_for_non_property_targets(self):
        """callback_subscription should not filter non-property subscriptions."""
        actor = Actor(config=self.mock_config)
        actor.id = "test-actor-id"

        with patch.object(actor, "get_trust_relationship") as mock_get_trust:
            mock_get_trust.return_value = {
                "baseuri": "http://peer.example.com",
                "peerid": "peer-123",
                "secret": "secret123",
            }

            with patch.object(actor, "_filter_subscription_data_by_permissions") as mock_filter:
                with patch("actingweb.actor.requests.post") as mock_post:
                    mock_post.return_value = Mock(status_code=204)

                    actor.callback_subscription(
                        peerid="peer-123",
                        sub_obj=Mock(),
                        sub={"target": "trust", "subscriptionid": "sub-1", "granularity": "high", "subtarget": None, "resource": None},
                        diff={"sequence": 1, "timestamp": "2024-01-01T00:00:00Z"},
                        blob='{"data": "trust change"}',
                    )

                    # Filter was NOT called for non-property target
                    mock_filter.assert_not_called()

                    # HTTP request WAS made
                    mock_post.assert_called_once()

    def test_callback_uses_filtered_blob(self):
        """callback_subscription should use filtered blob in the callback."""
        actor = Actor(config=self.mock_config)
        actor.id = "test-actor-id"

        with patch.object(actor, "get_trust_relationship") as mock_get_trust:
            mock_get_trust.return_value = {
                "baseuri": "http://peer.example.com",
                "peerid": "peer-123",
                "secret": "secret123",
            }

            filtered_data = '{"data_public": {"info": "public"}}'

            with patch.object(actor, "_filter_subscription_data_by_permissions") as mock_filter:
                mock_filter.return_value = filtered_data

                with patch("actingweb.actor.requests.post") as mock_post:
                    mock_post.return_value = Mock(status_code=204)

                    actor.callback_subscription(
                        peerid="peer-123",
                        sub_obj=Mock(),
                        sub={"target": "properties", "subscriptionid": "sub-1", "granularity": "high", "subtarget": None, "resource": None},
                        diff={"sequence": 1, "timestamp": "2024-01-01T00:00:00Z"},
                        blob='{"data_public": {"info": "public"}, "data_private": {"info": "private"}}',
                    )

                    # Verify the POST was called with filtered data
                    assert mock_post.called
                    call_args = mock_post.call_args
                    posted_data = json.loads(call_args.kwargs['data'])
                    # The posted data should contain the filtered blob
                    assert posted_data['data'] == json.loads(filtered_data)
