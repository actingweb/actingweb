"""
Unit tests for SubscriptionManager developer API methods.

Tests the newly added methods that support subscription handler refactoring:
- create_local_subscription()
- get_subscription_with_diffs()
- SubscriptionWithDiffs wrapper class
"""

from typing import Any

from actingweb.interface.subscription_manager import (
    SubscriptionManager,
    SubscriptionWithDiffs,
)


class FakeConfig:
    """Minimal Config mock for testing."""

    def __init__(self) -> None:
        self.root = "https://example.com/"


class FakeCoreSubscription:
    """Mock core Subscription object."""

    def __init__(
        self,
        peerid: str,
        subid: str,
        target: str,
        subtarget: str | None = None,
        resource: str | None = None,
        granularity: str = "high",
    ):
        self.peerid = peerid
        self.subid = subid
        self.target = target
        self.subtarget = subtarget
        self.resource = resource
        self.granularity = granularity
        self._diffs: list[dict[str, Any]] = []

    def get(self) -> dict[str, Any]:
        """Return subscription data as dict (required by SubscriptionWithDiffs)."""
        return {
            "peerid": self.peerid,
            "subscriptionid": self.subid,  # Note: uses "subscriptionid" not "subid"
            "target": self.target,
            "subtarget": self.subtarget,
            "resource": self.resource,
            "granularity": self.granularity,
        }

    def get_diffs(self) -> list[dict[str, Any]]:
        """Get all pending diffs."""
        return self._diffs.copy()

    def get_diff(self, seqnr: int) -> dict[str, Any] | None:
        """Get specific diff by sequence number."""
        for diff in self._diffs:
            if diff.get("seqnr") == seqnr:
                return diff
        return None

    def clear_diffs(self, seqnr: int = 0) -> None:
        """Clear all diffs up to sequence number."""
        if seqnr == 0:
            self._diffs.clear()
        else:
            self._diffs = [d for d in self._diffs if d.get("seqnr", 0) > seqnr]

    def clear_diff(self, seqnr: int) -> bool:
        """Clear specific diff by sequence number."""
        for i, diff in enumerate(self._diffs):
            if diff.get("seqnr") == seqnr:
                self._diffs.pop(i)
                return True
        return False


class FakeCoreActor:
    """Minimal core Actor mock for testing."""

    def __init__(self) -> None:
        self.id = "actor_1"
        self.config = FakeConfig()
        self._subscriptions: dict[tuple[str, str], FakeCoreSubscription] = {}

    def create_subscription(
        self,
        peerid: str,
        target: str,
        subtarget: str | None = None,
        resource: str | None = None,
        granularity: str = "high",
        callback: bool = False,
    ) -> dict[str, Any] | None:
        """Mock create_subscription for local subscription creation."""
        # Generate subscription ID
        subid = f"sub_{len(self._subscriptions) + 1}"

        # Create subscription object
        sub = FakeCoreSubscription(
            peerid=peerid,
            subid=subid,
            target=target,
            subtarget=subtarget,
            resource=resource,
            granularity=granularity,
        )

        # Store it
        self._subscriptions[(peerid, subid)] = sub

        # Return subscription data
        return {
            "peerid": peerid,
            "subid": subid,
            "target": target,
            "subtarget": subtarget,
            "resource": resource,
            "granularity": granularity,
        }

    def get_subscription_obj(
        self, peerid: str, subid: str, callback: bool = False
    ) -> FakeCoreSubscription | None:
        """Mock get_subscription_obj."""
        # For callback subscriptions, check if the stored sub has callback=True
        sub = self._subscriptions.get((peerid, subid))
        if sub:
            sub_data = sub.get()
            if callback and sub_data.get("callback") == callback:
                return sub
            elif not callback and sub_data.get("callback", False) == callback:
                return sub
        return None

    def get_subscription(
        self, peerid: str, subid: str, callback: bool = False
    ) -> dict[str, Any] | None:
        """Mock get_subscription - returns dict."""
        sub = self.get_subscription_obj(peerid=peerid, subid=subid, callback=callback)
        if sub:
            data = sub.get()
            data["callback"] = callback  # Ensure callback flag is set
            return data
        return None

    def delete_subscription(
        self, peerid: str, subid: str, callback: bool = False
    ) -> bool:
        """Mock delete_subscription."""
        key = (peerid, subid)
        if key in self._subscriptions:
            sub_data = self._subscriptions[key].get()
            # Only delete if callback flag matches
            if sub_data.get("callback", False) == callback:
                del self._subscriptions[key]
                return True
        return False


class TestSubscriptionManagerCreateLocal:
    """Tests for SubscriptionManager.create_local_subscription()."""

    def test_create_local_subscription_basic(self):
        """Test creating a basic local subscription."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        result = manager.create_local_subscription(
            peer_id="peer_1",
            target="properties",
            subtarget="config",
            resource="",
            granularity="high",
        )

        assert result is not None
        assert result["peerid"] == "peer_1"
        assert result["target"] == "properties"
        assert result["subtarget"] == "config"
        assert result["granularity"] == "high"
        assert "subid" in result

    def test_create_local_subscription_with_empty_subtarget(self):
        """Test creating subscription with empty subtarget."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        result = manager.create_local_subscription(
            peer_id="peer_2", target="properties", subtarget="", granularity="low"
        )

        assert result is not None
        assert result["peerid"] == "peer_2"
        assert result["target"] == "properties"
        assert result["subtarget"] is None  # Empty string converted to None

    def test_create_local_subscription_with_resource(self):
        """Test creating subscription with specific resource."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        result = manager.create_local_subscription(
            peer_id="peer_3",
            target="properties",
            subtarget="data",
            resource="temperature",
            granularity="high",
        )

        assert result is not None
        assert result["resource"] == "temperature"

    def test_create_local_subscription_multiple_peers(self):
        """Test creating subscriptions for multiple peers."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        sub1 = manager.create_local_subscription(
            peer_id="peer_1", target="properties", granularity="high"
        )
        sub2 = manager.create_local_subscription(
            peer_id="peer_2", target="properties", granularity="low"
        )

        assert sub1 is not None
        assert sub2 is not None
        assert sub1["peerid"] == "peer_1"
        assert sub2["peerid"] == "peer_2"
        assert sub1["subid"] != sub2["subid"]


class TestSubscriptionManagerGetWithDiffs:
    """Tests for SubscriptionManager.get_subscription_with_diffs()."""

    def test_get_subscription_with_diffs_exists(self):
        """Test getting existing subscription with diffs."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        # Create a subscription first
        result = manager.create_local_subscription(
            peer_id="peer_1", target="properties", granularity="high"
        )
        assert result is not None
        subid = result["subid"]

        # Get it with diffs
        sub_with_diffs = manager.get_subscription_with_diffs(
            peer_id="peer_1", subscription_id=subid
        )

        assert sub_with_diffs is not None
        assert isinstance(sub_with_diffs, SubscriptionWithDiffs)

    def test_get_subscription_with_diffs_not_found(self):
        """Test getting non-existent subscription returns None."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        sub_with_diffs = manager.get_subscription_with_diffs(
            peer_id="peer_999", subscription_id="sub_999"
        )

        assert sub_with_diffs is None


class TestSubscriptionWithDiffs:
    """Tests for SubscriptionWithDiffs wrapper class."""

    def test_subscription_info_property(self):
        """Test accessing subscription info."""
        core_sub = FakeCoreSubscription(
            peerid="peer_1",
            subid="sub_1",
            target="properties",
            subtarget="config",
            granularity="high",
        )

        wrapper = SubscriptionWithDiffs(core_sub)  # type: ignore[arg-type]
        info = wrapper.subscription_info

        assert info is not None
        assert info.peer_id == "peer_1"
        assert info.subscription_id == "sub_1"
        assert info.target == "properties"
        assert info.subtarget == "config"
        assert info.granularity == "high"

    def test_get_diffs_empty(self):
        """Test getting diffs when none exist."""
        core_sub = FakeCoreSubscription(
            peerid="peer_1", subid="sub_1", target="properties"
        )

        wrapper = SubscriptionWithDiffs(core_sub)  # type: ignore[arg-type]
        diffs = wrapper.get_diffs()

        assert diffs == []

    def test_get_diffs_with_data(self):
        """Test getting diffs when they exist."""
        core_sub = FakeCoreSubscription(
            peerid="peer_1", subid="sub_1", target="properties"
        )
        # Add some diffs
        core_sub._diffs = [
            {"seqnr": 1, "target": "properties", "blob": {"key": "value1"}},
            {"seqnr": 2, "target": "properties", "blob": {"key": "value2"}},
        ]

        wrapper = SubscriptionWithDiffs(core_sub)  # type: ignore[arg-type]
        diffs = wrapper.get_diffs()

        assert len(diffs) == 2
        assert diffs[0]["seqnr"] == 1
        assert diffs[1]["seqnr"] == 2

    def test_get_diff_by_seqnr(self):
        """Test getting specific diff by sequence number."""
        core_sub = FakeCoreSubscription(
            peerid="peer_1", subid="sub_1", target="properties"
        )
        core_sub._diffs = [
            {"seqnr": 1, "blob": {"key": "value1"}},
            {"seqnr": 2, "blob": {"key": "value2"}},
        ]

        wrapper = SubscriptionWithDiffs(core_sub)  # type: ignore[arg-type]

        diff1 = wrapper.get_diff(1)
        assert diff1 is not None
        assert diff1["seqnr"] == 1
        assert diff1["blob"]["key"] == "value1"

        diff2 = wrapper.get_diff(2)
        assert diff2 is not None
        assert diff2["seqnr"] == 2

        diff_missing = wrapper.get_diff(999)
        assert diff_missing is None

    def test_clear_diffs_all(self):
        """Test clearing all diffs."""
        core_sub = FakeCoreSubscription(
            peerid="peer_1", subid="sub_1", target="properties"
        )
        core_sub._diffs = [
            {"seqnr": 1, "blob": {}},
            {"seqnr": 2, "blob": {}},
            {"seqnr": 3, "blob": {}},
        ]

        wrapper = SubscriptionWithDiffs(core_sub)  # type: ignore[arg-type]
        wrapper.clear_diffs()

        assert wrapper.get_diffs() == []

    def test_clear_diffs_up_to_seqnr(self):
        """Test clearing diffs up to specific sequence number."""
        core_sub = FakeCoreSubscription(
            peerid="peer_1", subid="sub_1", target="properties"
        )
        core_sub._diffs = [
            {"seqnr": 1, "blob": {}},
            {"seqnr": 2, "blob": {}},
            {"seqnr": 3, "blob": {}},
            {"seqnr": 4, "blob": {}},
        ]

        wrapper = SubscriptionWithDiffs(core_sub)  # type: ignore[arg-type]
        wrapper.clear_diffs(seqnr=2)

        remaining = wrapper.get_diffs()
        assert len(remaining) == 2
        assert remaining[0]["seqnr"] == 3
        assert remaining[1]["seqnr"] == 4

    def test_clear_diff_specific(self):
        """Test clearing specific diff by sequence number."""
        core_sub = FakeCoreSubscription(
            peerid="peer_1", subid="sub_1", target="properties"
        )
        core_sub._diffs = [
            {"seqnr": 1, "blob": {}},
            {"seqnr": 2, "blob": {}},
            {"seqnr": 3, "blob": {}},
        ]

        wrapper = SubscriptionWithDiffs(core_sub)  # type: ignore[arg-type]
        result = wrapper.clear_diff(2)

        assert result is True
        remaining = wrapper.get_diffs()
        assert len(remaining) == 2
        assert remaining[0]["seqnr"] == 1
        assert remaining[1]["seqnr"] == 3

    def test_clear_diff_not_found(self):
        """Test clearing non-existent diff returns False."""
        core_sub = FakeCoreSubscription(
            peerid="peer_1", subid="sub_1", target="properties"
        )
        core_sub._diffs = [{"seqnr": 1, "blob": {}}]

        wrapper = SubscriptionWithDiffs(core_sub)  # type: ignore[arg-type]
        result = wrapper.clear_diff(999)

        assert result is False
        assert len(wrapper.get_diffs()) == 1  # Original diff still there


class TestSubscriptionManagerIntegration:
    """Integration tests combining multiple SubscriptionManager operations."""

    def test_create_and_get_subscription_with_diffs(self):
        """Test creating subscription and then getting it with diffs."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        # Create subscription
        result = manager.create_local_subscription(
            peer_id="peer_1", target="properties", granularity="high"
        )
        assert result is not None
        subid = result["subid"]

        # Get it with diffs
        sub_with_diffs = manager.get_subscription_with_diffs(
            peer_id="peer_1", subscription_id=subid
        )
        assert sub_with_diffs is not None

        # Verify info matches
        info = sub_with_diffs.subscription_info
        assert info is not None
        assert info.peer_id == "peer_1"
        assert info.subscription_id == subid

    def test_subscription_diff_workflow(self):
        """Test complete diff workflow: create, add diffs, clear."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        # Create subscription
        result = manager.create_local_subscription(
            peer_id="peer_1", target="properties", granularity="high"
        )
        assert result is not None
        subid = result["subid"]

        # Get subscription with diffs
        sub_with_diffs = manager.get_subscription_with_diffs(
            peer_id="peer_1", subscription_id=subid
        )
        assert sub_with_diffs is not None

        # Simulate adding diffs (in real code, property changes would do this)
        core_sub = actor.get_subscription_obj(peerid="peer_1", subid=subid)
        assert core_sub is not None
        core_sub._diffs.append(
            {"seqnr": 1, "target": "properties", "blob": {"key": "value"}}
        )

        # Get diffs
        diffs = sub_with_diffs.get_diffs()
        assert len(diffs) == 1

        # Clear diffs
        sub_with_diffs.clear_diffs()
        assert sub_with_diffs.get_diffs() == []


class TestSubscriptionManagerCallbackMethods:
    """Tests for SubscriptionManager callback subscription methods."""

    def test_get_callback_subscription_exists(self):
        """Test getting existing callback subscription."""
        actor = FakeCoreActor()

        # Create a callback subscription directly (simulating outbound subscription)
        actor._subscriptions[("peer_1", "sub_callback_1")] = FakeCoreSubscription(
            peerid="peer_1",
            subid="sub_callback_1",
            target="properties",
        )
        # Mark it as callback subscription in the data
        sub_data = actor._subscriptions[("peer_1", "sub_callback_1")].get()
        sub_data["callback"] = True

        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        # Patch the core actor's get_subscription to return the data with callback=True
        original_get_sub = actor.get_subscription

        def mock_get_subscription(peerid, subid, callback=False):
            if callback and peerid == "peer_1" and subid == "sub_callback_1":
                return sub_data
            return (
                original_get_sub(peerid, subid) if callable(original_get_sub) else None
            )

        actor.get_subscription = mock_get_subscription  # type: ignore[assignment]

        result = manager.get_callback_subscription(
            peer_id="peer_1", subscription_id="sub_callback_1"
        )

        assert result is not None
        assert result.peer_id == "peer_1"
        assert result.subscription_id == "sub_callback_1"
        assert result.is_callback is True

    def test_get_callback_subscription_not_found(self):
        """Test getting non-existent callback subscription."""
        actor = FakeCoreActor()
        actor.get_subscription = lambda peerid, subid, callback=False: None  # type: ignore[assignment]

        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        result = manager.get_callback_subscription(
            peer_id="peer_999", subscription_id="sub_999"
        )

        assert result is None

    def test_delete_callback_subscription_success(self):
        """Test deleting existing callback subscription."""
        actor = FakeCoreActor()
        deleted = False

        def mock_delete_subscription(peerid, subid, callback=False):
            nonlocal deleted
            if callback and peerid == "peer_1" and subid == "sub_1":
                deleted = True
                return True
            return False

        actor.delete_subscription = mock_delete_subscription  # type: ignore[assignment]

        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        result = manager.delete_callback_subscription(
            peer_id="peer_1", subscription_id="sub_1"
        )

        assert result is True
        assert deleted is True

    def test_delete_callback_subscription_not_found(self):
        """Test deleting non-existent callback subscription."""
        actor = FakeCoreActor()
        actor.delete_subscription = lambda peerid, subid, callback=False: False  # type: ignore[assignment]

        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        result = manager.delete_callback_subscription(
            peer_id="peer_999", subscription_id="sub_999"
        )

        assert result is False

    def test_delete_callback_subscription_no_peer_notification(self):
        """Test that delete_callback_subscription doesn't notify peer."""
        actor = FakeCoreActor()
        delete_params = {}

        def mock_delete_subscription(peerid, subid, callback=False):
            # Capture parameters to verify callback=True was passed
            delete_params["peerid"] = peerid
            delete_params["subid"] = subid
            delete_params["callback"] = callback
            return True

        actor.delete_subscription = mock_delete_subscription  # type: ignore[assignment]

        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        manager.delete_callback_subscription(peer_id="peer_1", subscription_id="sub_1")

        # Verify it called delete_subscription with callback=True
        assert delete_params["callback"] is True
        assert delete_params["peerid"] == "peer_1"
        assert delete_params["subid"] == "sub_1"

    def test_get_callback_vs_regular_subscription(self):
        """Test that callback and regular subscriptions are distinct."""
        actor = FakeCoreActor()

        # Create one callback subscription and one regular subscription with same IDs
        callback_data = {
            "peerid": "peer_1",
            "subscriptionid": "sub_1",
            "target": "properties",
            "callback": True,
        }
        regular_data = {
            "peerid": "peer_1",
            "subscriptionid": "sub_1",
            "target": "properties",
            "callback": False,
        }

        def mock_get_subscription(peerid, subid, callback=False):
            if callback:
                return callback_data
            return regular_data

        actor.get_subscription = mock_get_subscription  # type: ignore[assignment]

        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        # Get callback subscription
        callback_sub = manager.get_callback_subscription(
            peer_id="peer_1", subscription_id="sub_1"
        )
        assert callback_sub is not None
        assert callback_sub.is_callback is True

        # Get regular subscription
        regular_sub = manager.get_subscription(
            peer_id="peer_1", subscription_id="sub_1"
        )
        assert regular_sub is not None
        assert regular_sub.is_callback is False


class TestBaselineTransformation:
    """Test suite for _transform_baseline_list_properties() method."""

    def test_transform_baseline_list_metadata(self):
        """Test transforming list metadata to items."""
        actor = FakeCoreActor()

        # Mock proxy that returns list items
        class MockProxy:
            def __init__(self):
                self.trust = {"verified": True}  # Mock trust object

            def get_resource(self, path: str) -> Any:
                # Return list items for properties/memory_travel
                if path == "properties/memory_travel":
                    return [
                        {"id": "1", "location": "Paris"},
                        {"id": "2", "location": "Tokyo"},
                        {"id": "3", "location": "NYC"},
                    ]
                return None

        def mock_get_peer_proxy(peer_id: str) -> MockProxy:
            return MockProxy()

        manager = SubscriptionManager(actor)  # type: ignore[arg-type]
        manager._get_peer_proxy = mock_get_peer_proxy  # type: ignore[assignment]

        # Baseline data with list metadata
        baseline_data = {
            "scalar_prop": {"value": "test"},
            "memory_travel": {"_list": True, "count": 3},
        }

        # Transform
        result = manager._transform_baseline_list_properties(
            baseline_data=baseline_data, peer_id="peer_1", target="properties"
        )

        # Verify scalar property unchanged
        assert result["scalar_prop"] == {"value": "test"}

        # Verify list property transformed
        assert result["memory_travel"]["_list"] is True
        assert "items" in result["memory_travel"]
        assert len(result["memory_travel"]["items"]) == 3
        assert result["memory_travel"]["items"][0]["location"] == "Paris"

    def test_transform_baseline_mixed_properties(self):
        """Test mix of scalar and list properties."""
        actor = FakeCoreActor()

        class MockProxy:
            def __init__(self):
                self.trust = {"verified": True}

            def get_resource(self, path: str) -> Any:
                if path == "properties/list1":
                    return [{"id": "1"}]
                elif path == "properties/list2":
                    return [{"id": "2"}, {"id": "3"}]
                return None

        def mock_get_peer_proxy(peer_id: str) -> MockProxy:
            return MockProxy()

        manager = SubscriptionManager(actor)  # type: ignore[arg-type]
        manager._get_peer_proxy = mock_get_peer_proxy  # type: ignore[assignment]

        baseline_data = {
            "scalar1": {"value": "test1"},
            "list1": {"_list": True, "count": 1},
            "scalar2": {"value": "test2"},
            "list2": {"_list": True, "count": 2},
        }

        result = manager._transform_baseline_list_properties(
            baseline_data=baseline_data, peer_id="peer_1", target="properties"
        )

        # Verify scalars unchanged
        assert result["scalar1"] == {"value": "test1"}
        assert result["scalar2"] == {"value": "test2"}

        # Verify lists transformed
        assert len(result["list1"]["items"]) == 1
        assert len(result["list2"]["items"]) == 2

    def test_transform_baseline_empty_list(self):
        """Test handling empty lists."""
        actor = FakeCoreActor()

        class MockProxy:
            def __init__(self):
                self.trust = {"verified": True}

            def get_resource(self, path: str) -> Any:
                if path == "properties/empty_list":
                    return []
                return None

        def mock_get_peer_proxy(peer_id: str) -> MockProxy:
            return MockProxy()

        manager = SubscriptionManager(actor)  # type: ignore[arg-type]
        manager._get_peer_proxy = mock_get_peer_proxy  # type: ignore[assignment]

        baseline_data = {"empty_list": {"_list": True, "count": 0}}

        result = manager._transform_baseline_list_properties(
            baseline_data=baseline_data, peer_id="peer_1", target="properties"
        )

        # Verify empty list stored correctly
        assert result["empty_list"]["_list"] is True
        assert result["empty_list"]["items"] == []

    def test_transform_baseline_permission_denied(self):
        """Test handling 403 from remote peer."""
        actor = FakeCoreActor()

        class MockProxy:
            def __init__(self):
                self.trust = {"verified": True}

            def get_resource(self, path: str) -> Any:
                # Return error response for permission denied
                if path == "properties/restricted":
                    return {"error": "Permission denied"}
                return None

        def mock_get_peer_proxy(peer_id: str) -> MockProxy:
            return MockProxy()

        manager = SubscriptionManager(actor)  # type: ignore[arg-type]
        manager._get_peer_proxy = mock_get_peer_proxy  # type: ignore[assignment]

        baseline_data = {
            "public_prop": {"value": "test"},
            "restricted": {"_list": True, "count": 5},
        }

        result = manager._transform_baseline_list_properties(
            baseline_data=baseline_data, peer_id="peer_1", target="properties"
        )

        # Verify public property unchanged
        assert result["public_prop"] == {"value": "test"}

        # Verify restricted list kept as metadata (not transformed)
        assert result["restricted"] == {"_list": True, "count": 5}
        assert "items" not in result["restricted"]

    def test_transform_baseline_fetch_error(self):
        """Test handling network/protocol errors."""
        actor = FakeCoreActor()

        class MockProxy:
            def __init__(self):
                self.trust = {"verified": True}

            def get_resource(self, path: str) -> Any:
                # Simulate network error
                if path == "properties/failing_list":
                    raise Exception("Network timeout")
                return None

        def mock_get_peer_proxy(peer_id: str) -> MockProxy:
            return MockProxy()

        manager = SubscriptionManager(actor)  # type: ignore[arg-type]
        manager._get_peer_proxy = mock_get_peer_proxy  # type: ignore[assignment]

        baseline_data = {
            "good_prop": {"value": "test"},
            "failing_list": {"_list": True, "count": 10},
        }

        result = manager._transform_baseline_list_properties(
            baseline_data=baseline_data, peer_id="peer_1", target="properties"
        )

        # Verify good property unchanged
        assert result["good_prop"] == {"value": "test"}

        # Verify failing list kept as metadata (graceful failure)
        assert result["failing_list"] == {"_list": True, "count": 10}
        assert "items" not in result["failing_list"]

    def test_transform_baseline_no_trust(self):
        """Test handling when no trust relationship exists."""
        actor = FakeCoreActor()

        class MockProxy:
            def __init__(self):
                self.trust = None  # No trust

            def get_resource(self, path: str) -> Any:
                return None

        def mock_get_peer_proxy(peer_id: str) -> MockProxy:
            return MockProxy()

        manager = SubscriptionManager(actor)  # type: ignore[arg-type]
        manager._get_peer_proxy = mock_get_peer_proxy  # type: ignore[assignment]

        baseline_data = {"list_prop": {"_list": True, "count": 3}}

        result = manager._transform_baseline_list_properties(
            baseline_data=baseline_data, peer_id="peer_1", target="properties"
        )

        # Should return original data unchanged
        assert result == baseline_data

    def test_transform_baseline_already_has_items(self):
        """Test that lists with items already present are not refetched."""
        actor = FakeCoreActor()

        class MockProxy:
            def __init__(self):
                self.trust = {"verified": True}

            def get_resource(self, path: str) -> Any:
                # Should not be called
                raise Exception("Should not fetch when items already present")

        def mock_get_peer_proxy(peer_id: str) -> MockProxy:
            return MockProxy()

        manager = SubscriptionManager(actor)  # type: ignore[arg-type]
        manager._get_peer_proxy = mock_get_peer_proxy  # type: ignore[assignment]

        baseline_data = {
            "list_with_items": {"_list": True, "items": [{"id": "1"}]},
        }

        # Should not raise exception since it shouldn't call get_resource
        result = manager._transform_baseline_list_properties(
            baseline_data=baseline_data, peer_id="peer_1", target="properties"
        )

        # Should return original data unchanged
        assert result == baseline_data
