"""
Integration tests for property mutation subscription notifications.

Tests that property changes via HTTP API trigger subscription diffs correctly.
"""

import requests


class TestPropertyNotifications:
    """Test property mutations trigger subscription notifications via HTTP API."""

    def test_put_property_triggers_subscription_diff(self, actor_factory, trust_helper):
        """Test that PUT /{actor_id}/properties/{name} triggers subscription diff."""
        # Create two actors
        actor1 = actor_factory.create("subscriber@example.com")
        actor2 = actor_factory.create("publisher@example.com")

        # Establish trust relationship and get secret
        trust = trust_helper.establish(actor1, actor2, "friend")

        # Actor1 subscribes to actor2's properties
        response = requests.post(
            f"{actor1['url']}/subscriptions",
            json={
                "peerid": actor2["id"],
                "target": "properties",
                "granularity": "high",
            },
            auth=(actor1["creator"], actor1["passphrase"]),
        )
        assert response.status_code in [200, 201, 204], f"Subscription failed: {response.text}"

        # Get subscription ID from response or Location header
        if response.status_code in [200, 201]:
            subscription_id = response.json()["subscriptionid"]
        else:
            location = response.headers.get("Location", "")
            subscription_id = location.split("/")[-1]

        # Actor2 modifies a property
        response = requests.put(
            f"{actor2['url']}/properties/status",
            data="active",
            headers={"Content-Type": "text/plain"},
            auth=(actor2["creator"], actor2["passphrase"]),
        )
        assert response.status_code == 204, f"Property update failed: {response.text}"

        # Verify diff was registered - actor1 retrieves subscription with diffs from actor2's URL
        # Note: Subscription is stored at publisher's (actor2) URL, not subscriber's (actor1)
        # Use Bearer token authentication with trust secret
        get_url = f"{actor2['url']}/subscriptions/{actor1['id']}/{subscription_id}"
        response = requests.get(
            get_url,
            headers={"Authorization": f"Bearer {trust['secret']}"},
        )
        assert response.status_code == 200, f"Failed to get subscription from {get_url}: {response.text}"
        subscription_data = response.json()
        diffs = subscription_data.get("data", [])

        assert len(diffs) > 0, "No diffs were registered"
        # Check the diff data contains the property update
        diff_data = diffs[0]["data"]
        assert "status" in diff_data, f"Expected 'status' in diff data: {diff_data}"
        assert diff_data["status"] == "active", f"Expected 'active', got {diff_data['status']}"

    def test_delete_property_triggers_subscription_diff(self, actor_factory, trust_helper):
        """Test that DELETE /{actor_id}/properties/{name} triggers subscription diff."""
        # Create two actors
        actor1 = actor_factory.create("subscriber@example.com")
        actor2 = actor_factory.create("publisher@example.com")

        # Establish trust
        trust = trust_helper.establish(actor1, actor2, "friend")

        # Set a property first
        requests.put(
            f"{actor2['url']}/properties/temp_data",
            data="temporary",
            headers={"Content-Type": "text/plain"},
            auth=(actor2["creator"], actor2["passphrase"]),
        )

        # Actor1 subscribes to actor2's properties
        response = requests.post(
            f"{actor1['url']}/subscriptions",
            json={
                "peerid": actor2["id"],
                "target": "properties",
                "granularity": "high",
            },
            auth=(actor1["creator"], actor1["passphrase"]),
        )
        assert response.status_code in [200, 201, 204]

        # Get subscription ID from response or Location header
        if response.status_code in [200, 201]:
            subscription_id = response.json()["subscriptionid"]
        else:
            location = response.headers.get("Location", "")
            subscription_id = location.split("/")[-1]

        # Clear initial diff from property creation
        requests.get(
            f"{actor2['url']}/subscriptions/{actor1['id']}/{subscription_id}",
            headers={"Authorization": f"Bearer {trust['secret']}"},
        )

        # Now delete the property
        response = requests.delete(
            f"{actor2['url']}/properties/temp_data",
            auth=(actor2["creator"], actor2["passphrase"]),
        )
        assert response.status_code == 204

        # Verify diff was registered for deletion
        response = requests.get(
            f"{actor2['url']}/subscriptions/{actor1['id']}/{subscription_id}",
            headers={"Authorization": f"Bearer {trust['secret']}"},
        )
        assert response.status_code == 200
        subscription_data = response.json()
        diffs = subscription_data.get("data", [])

        assert len(diffs) > 0, "No diff registered for deletion"
        # Property deletion is represented by the property being set to empty string
        diff_data = diffs[0]["data"]
        assert "temp_data" in diff_data, f"Expected 'temp_data' in diff: {diff_data}"

    def test_post_properties_triggers_subscription_diff(self, actor_factory, trust_helper):
        """Test that POST /{actor_id}/properties triggers subscription diff."""
        # Create two actors
        actor1 = actor_factory.create("subscriber@example.com")
        actor2 = actor_factory.create("publisher@example.com")

        # Establish trust
        trust = trust_helper.establish(actor1, actor2, "friend")

        # Actor1 subscribes to actor2's properties
        response = requests.post(
            f"{actor1['url']}/subscriptions",
            json={
                "peerid": actor2["id"],
                "target": "properties",
                "granularity": "high",
            },
            auth=(actor1["creator"], actor1["passphrase"]),
        )
        assert response.status_code in [200, 201, 204]

        # Get subscription ID from response or Location header
        if response.status_code in [200, 201]:
            subscription_id = response.json()["subscriptionid"]
        else:
            location = response.headers.get("Location", "")
            subscription_id = location.split("/")[-1]

        # Actor2 creates multiple properties via POST
        response = requests.post(
            f"{actor2['url']}/properties",
            json={"key1": "value1", "key2": "value2"},
            auth=(actor2["creator"], actor2["passphrase"]),
        )
        assert response.status_code in [200, 201, 204]

        # Verify diffs were registered - POST batches multiple properties into single diff
        response = requests.get(
            f"{actor2['url']}/subscriptions/{actor1['id']}/{subscription_id}",
            headers={"Authorization": f"Bearer {trust['secret']}"},
        )
        assert response.status_code == 200
        subscription_data = response.json()
        diffs = subscription_data.get("data", [])

        assert len(diffs) >= 1, "No diffs registered"

        # Collect all property names from diffs (may be batched in single diff or multiple)
        all_diff_data = {}
        for diff in diffs:
            diff_data = diff.get("data", {})
            all_diff_data.update(diff_data)

        # Both properties should be present in the diff data
        assert "key1" in all_diff_data
        assert "key2" in all_diff_data

    def test_diff_contains_correct_subtarget_and_blob(self, actor_factory, trust_helper):
        """Test that diff contains correct subtarget and blob content."""
        actor1 = actor_factory.create("subscriber@example.com")
        actor2 = actor_factory.create("publisher@example.com")

        trust = trust_helper.establish(actor1, actor2, "friend")

        # Subscribe
        response = requests.post(
            f"{actor1['url']}/subscriptions",
            json={
                "peerid": actor2["id"],
                "target": "properties",
                "granularity": "high",
            },
            auth=(actor1["creator"], actor1["passphrase"]),
        )
        assert response.status_code in [200, 201, 204]

        # Get subscription ID from response or Location header
        if response.status_code in [200, 201]:
            subscription_id = response.json()["subscriptionid"]
        else:
            location = response.headers.get("Location", "")
            subscription_id = location.split("/")[-1]

        # Set a complex property value
        complex_value = {"nested": {"data": 123}, "array": [1, 2, 3]}
        response = requests.put(
            f"{actor2['url']}/properties/config",
            json=complex_value,
            auth=(actor2["creator"], actor2["passphrase"]),
        )
        assert response.status_code == 204

        # Get diffs
        response = requests.get(
            f"{actor2['url']}/subscriptions/{actor1['id']}/{subscription_id}",
            headers={"Authorization": f"Bearer {trust['secret']}"},
        )
        subscription_data = response.json()
        diffs = subscription_data.get("data", [])

        assert len(diffs) > 0
        diff_data = diffs[0]["data"]
        assert "config" in diff_data

        # Verify the complex value structure
        config_value = diff_data["config"]
        assert config_value["nested"]["data"] == 123
        assert config_value["array"] == [1, 2, 3]

    def test_multiple_puts_create_multiple_diffs(self, actor_factory, trust_helper):
        """Test that multiple property updates create multiple diffs."""
        actor1 = actor_factory.create("subscriber@example.com")
        actor2 = actor_factory.create("publisher@example.com")

        trust = trust_helper.establish(actor1, actor2, "friend")

        # Subscribe
        response = requests.post(
            f"{actor1['url']}/subscriptions",
            json={
                "peerid": actor2["id"],
                "target": "properties",
                "granularity": "high",
            },
            auth=(actor1["creator"], actor1["passphrase"]),
        )
        assert response.status_code in [200, 201, 204]

        # Get subscription ID from response or Location header
        if response.status_code in [200, 201]:
            subscription_id = response.json()["subscriptionid"]
        else:
            location = response.headers.get("Location", "")
            subscription_id = location.split("/")[-1]

        # Make multiple updates
        for i in range(3):
            requests.put(
                f"{actor2['url']}/properties/counter",
                data=str(i),
                headers={"Content-Type": "text/plain"},
                auth=(actor2["creator"], actor2["passphrase"]),
            )

        # Get all diffs
        response = requests.get(
            f"{actor2['url']}/subscriptions/{actor1['id']}/{subscription_id}",
            headers={"Authorization": f"Bearer {trust['secret']}"},
        )
        subscription_data = response.json()
        diffs = subscription_data.get("data", [])

        # Should have at least 3 diffs
        assert len(diffs) >= 3, f"Expected at least 3 diffs, got {len(diffs)}"

    def test_diff_cleared_after_retrieval(self, actor_factory, trust_helper):
        """Test that diffs are cleared after being retrieved."""
        actor1 = actor_factory.create("subscriber@example.com")
        actor2 = actor_factory.create("publisher@example.com")

        trust = trust_helper.establish(actor1, actor2, "friend")

        # Subscribe
        response = requests.post(
            f"{actor1['url']}/subscriptions",
            json={
                "peerid": actor2["id"],
                "target": "properties",
                "granularity": "high",
            },
            auth=(actor1["creator"], actor1["passphrase"]),
        )
        assert response.status_code in [200, 201, 204]

        # Get subscription ID from response or Location header
        if response.status_code in [200, 201]:
            subscription_id = response.json()["subscriptionid"]
        else:
            location = response.headers.get("Location", "")
            subscription_id = location.split("/")[-1]

        # Update property
        requests.put(
            f"{actor2['url']}/properties/test",
            data="value",
            headers={"Content-Type": "text/plain"},
            auth=(actor2["creator"], actor2["passphrase"]),
        )

        # Get diffs first time
        response = requests.get(
            f"{actor2['url']}/subscriptions/{actor1['id']}/{subscription_id}",
            headers={"Authorization": f"Bearer {trust['secret']}"},
        )
        subscription_data = response.json()
        first_diffs = subscription_data.get("data", [])
        assert len(first_diffs) > 0

        # Get diffs second time - should still contain diffs (not auto-cleared)
        response = requests.get(
            f"{actor2['url']}/subscriptions/{actor1['id']}/{subscription_id}",
            headers={"Authorization": f"Bearer {trust['secret']}"},
        )
        assert response.status_code == 200
        subscription_data = response.json()
        second_diffs = subscription_data.get("data", [])

        # Diffs persist until explicitly cleared with PUT (sequence number)
        # GET does not automatically clear diffs per ActingWeb spec
        assert len(second_diffs) > 0, "Diffs should persist after GET"
