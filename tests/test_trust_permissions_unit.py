"""
Trust Permissions Unit Tests.

Pure unit tests for trust permission pattern matching and merge logic.
No DynamoDB required.

References:
- actingweb/trust_permissions.py - merge_permissions() function
- actingweb/permission_evaluator.py:442-498 - Pattern matching logic
"""

from typing import Any

import pytest


class TestTrustPermissionsPatternMatching:
    """Test pattern matching with wildcards."""

    def test_wildcard_pattern_matches_multiple_properties(self):
        """
        Test that memory_* pattern matches all memory types.

        actingweb_mcp uses memory_* to match all memory property lists.

        Spec: actingweb/permission_evaluator.py:487-497 - Glob to regex conversion
        """
        from actingweb.permission_evaluator import glob_match

        # Test pattern matching logic
        pattern = "memory_*"

        matching_names = [
            "memory_personal",
            "memory_travel",
            "memory_food",
            "memory_health",
            "memory_work",
        ]

        non_matching_names = ["settings_private", "notes_general", "user_profile"]

        # All memory_ names should match
        for name in matching_names:
            assert glob_match(name, pattern), f"{name} should match {pattern}"

        # Non-memory names should not match
        for name in non_matching_names:
            assert not glob_match(name, pattern), f"{name} should not match {pattern}"

    def test_method_pattern_matching(self):
        """
        Test that get_* pattern matches method names.

        actingweb_mcp allows method patterns like get_*, list_*, search_*.

        Spec: actingweb_mcp uses method patterns for permission control
        """
        from actingweb.permission_evaluator import glob_match

        pattern = "get_*"

        matching_methods = ["get_profile", "get_notes", "get_memory", "get_settings"]

        non_matching_methods = [
            "list_items",
            "search_memories",
            "update_profile",
            "delete_note",
        ]

        for method in matching_methods:
            assert glob_match(method, pattern)

        for method in non_matching_methods:
            assert not glob_match(method, pattern)

    def test_multiple_wildcard_patterns(self):
        """
        Test permissions with multiple wildcard patterns.

        actingweb_mcp defines multiple allowed patterns for different categories.

        Spec: actingweb/permission_evaluator.py:442-454 - Matches any pattern
        """
        from actingweb.permission_evaluator import glob_match

        patterns = ["memory_*", "notes_*", "public_*"]

        matching_names = [
            "memory_personal",
            "notes_work",
            "public_profile",
            "memory_travel",
            "notes_2025",
        ]

        non_matching_names = ["private_settings", "user_config", "auth_token"]

        # Should match at least one pattern
        for name in matching_names:
            matched = any(glob_match(name, pattern) for pattern in patterns)
            assert matched, f"{name} should match at least one pattern"

        # Should not match any pattern
        for name in non_matching_names:
            matched = any(glob_match(name, pattern) for pattern in patterns)
            assert not matched, f"{name} should not match any pattern"


class TestMergePermissionsFunction:
    """
    Unit tests for merge_permissions() function.

    These tests verify the merge_base parameter behavior:
    - merge_base=True (default): Union merge for patterns and excluded_patterns
    - merge_base=False: Full replace behavior for all fields

    No DynamoDB required - pure unit tests.
    """

    def test_merge_base_true_unions_patterns(self):
        """
        Test that merge_base=True (default) unions patterns arrays.

        Base patterns should be preserved when override adds new patterns.
        """
        from actingweb.trust_permissions import merge_permissions

        base = {
            "properties": {
                "patterns": ["public/*", "shared/*", "profile/*"],
                "operations": ["read"],
            }
        }
        override = {
            "properties": {"patterns": ["memory_*"], "operations": ["read", "write"]}
        }

        result = merge_permissions(base, override)

        # Patterns should be unioned
        assert result["properties"]["patterns"] == [
            "public/*",
            "shared/*",
            "profile/*",
            "memory_*",
        ]
        # Operations should be replaced
        assert result["properties"]["operations"] == ["read", "write"]

    def test_merge_base_true_unions_excluded_patterns(self):
        """
        Test that merge_base=True unions excluded_patterns arrays.

        Base security exclusions should be preserved when override adds more.
        """
        from actingweb.trust_permissions import merge_permissions

        base = {
            "properties": {
                "patterns": ["*"],
                "excluded_patterns": ["private/*", "security/*", "oauth_*"],
            }
        }
        override = {"properties": {"excluded_patterns": ["memory_personal"]}}

        result = merge_permissions(base, override)

        # Excluded patterns should be unioned
        assert result["properties"]["excluded_patterns"] == [
            "private/*",
            "security/*",
            "oauth_*",
            "memory_personal",
        ]

    def test_merge_base_true_preserves_base_on_empty_override(self):
        """
        Test that empty override arrays don't clear base patterns.

        Security: An override with excluded_patterns=[] should NOT remove
        base security exclusions.
        """
        from actingweb.trust_permissions import merge_permissions

        base = {
            "properties": {
                "patterns": ["public/*", "shared/*"],
                "excluded_patterns": ["private/*", "security/*"],
            }
        }
        override = {
            "properties": {
                "patterns": [],  # Empty - should not clear base
                "excluded_patterns": [],  # Empty - should not clear base
            }
        }

        result = merge_permissions(base, override)

        # Base values should be preserved when override is empty
        assert result["properties"]["patterns"] == ["public/*", "shared/*"]
        assert result["properties"]["excluded_patterns"] == ["private/*", "security/*"]

    def test_merge_base_false_replaces_patterns(self):
        """
        Test that merge_base=False replaces patterns arrays entirely.

        This allows full override when explicitly needed.
        """
        from actingweb.trust_permissions import merge_permissions

        base = {
            "properties": {
                "patterns": ["public/*", "shared/*", "profile/*"],
                "operations": ["read"],
            }
        }
        override = {
            "properties": {"patterns": ["memory_*"], "operations": ["read", "write"]}
        }

        result = merge_permissions(base, override, merge_base=False)

        # Patterns should be replaced
        assert result["properties"]["patterns"] == ["memory_*"]
        # Operations should still be replaced
        assert result["properties"]["operations"] == ["read", "write"]

    def test_merge_base_false_clears_excluded_patterns(self):
        """
        Test that merge_base=False allows clearing excluded_patterns.

        When explicitly set, this enables full override capability.
        """
        from actingweb.trust_permissions import merge_permissions

        base = {
            "properties": {
                "patterns": ["*"],
                "excluded_patterns": ["private/*", "security/*", "oauth_*"],
            }
        }
        override = {"properties": {"excluded_patterns": []}}

        result = merge_permissions(base, override, merge_base=False)

        # Excluded patterns should be cleared
        assert result["properties"]["excluded_patterns"] == []

    def test_merge_base_true_deduplicates_patterns(self):
        """
        Test that merge_base=True deduplicates patterns.

        When override contains patterns already in base, they should not be
        duplicated.
        """
        from actingweb.trust_permissions import merge_permissions

        base = {"properties": {"patterns": ["public/*", "shared/*"]}}
        override = {"properties": {"patterns": ["shared/*", "memory_*"]}}

        result = merge_permissions(base, override)

        # shared/* should appear only once
        assert result["properties"]["patterns"] == ["public/*", "shared/*", "memory_*"]

    def test_merge_base_affects_only_pattern_fields(self):
        """
        Test that merge_base only affects patterns and excluded_patterns.

        Other fields (operations, allowed, denied) should always be replaced.
        """
        from actingweb.trust_permissions import merge_permissions

        base = {
            "methods": {"allowed": ["get_*", "list_*"], "denied": ["admin_*"]},
            "actions": {"allowed": ["search"]},
        }
        override = {
            "methods": {"allowed": ["get_*"], "denied": []},
            "actions": {"allowed": ["search", "export"]},
        }

        result = merge_permissions(base, override, merge_base=True)

        # allowed and denied should be replaced, not merged
        assert result["methods"]["allowed"] == ["get_*"]
        assert result["methods"]["denied"] == []
        assert result["actions"]["allowed"] == ["search", "export"]

    def test_merge_base_with_none_override(self):
        """
        Test that None override returns base permissions unchanged.
        """
        from actingweb.trust_permissions import merge_permissions

        base = {
            "properties": {"patterns": ["public/*"], "excluded_patterns": ["private/*"]}
        }

        result = merge_permissions(base, None)

        assert result == base
        # Should be a copy, not the same object
        assert result is not base

    def test_merge_base_with_category_none_values(self):
        """
        Test that None values in override categories are ignored.

        This allows selective override of only specific categories.
        """
        from actingweb.trust_permissions import merge_permissions

        base = {
            "properties": {"patterns": ["public/*"]},
            "methods": {"allowed": ["get_*"]},
        }
        override = {
            "properties": {"patterns": ["memory_*"]},
            "methods": None,  # Should use base methods
        }

        result = merge_permissions(base, override)

        # Properties should be merged
        assert result["properties"]["patterns"] == ["public/*", "memory_*"]
        # Methods should remain from base
        assert result["methods"]["allowed"] == ["get_*"]

    def test_merge_base_adds_new_categories(self):
        """
        Test that override can add new permission categories.
        """
        from actingweb.trust_permissions import merge_permissions

        base = {"properties": {"patterns": ["public/*"]}}
        override = {"tools": {"allowed": ["search", "export"]}}

        result = merge_permissions(base, override)

        # Original category preserved
        assert result["properties"]["patterns"] == ["public/*"]
        # New category added
        assert result["tools"]["allowed"] == ["search", "export"]


class TestTrustPermissionStoreNotifications:
    """
    Unit tests for TrustPermissionStore notification functionality.

    These tests verify:
    - Peer notification is called when store_permissions() succeeds
    - Notification can be disabled via notify_peer=False
    - Notification failures don't affect storage success
    - Config-based notification control works correctly

    Uses mocks to avoid actual HTTP calls and DynamoDB access.
    """

    def _create_mock_config(self, notify_peer_on_change: bool = True) -> Any:
        """Create a mock config object."""
        from unittest.mock import Mock

        config = Mock()
        config.notify_peer_on_change = notify_peer_on_change
        config.database = "dynamodb"
        return config

    def _create_permissions(self) -> Any:
        """Create a test TrustPermissions object."""
        from actingweb.trust_permissions import TrustPermissions

        return TrustPermissions(
            actor_id="actor123",
            peer_id="peer456",
            trust_type="friend",
            properties={"patterns": ["public/*"]},
        )

    def test_store_permissions_calls_notify_peer_by_default(self):
        """
        Test that store_permissions() calls _notify_peer when storage succeeds.

        Default behavior: notify_peer_on_change=True in config.
        """
        from unittest.mock import patch

        from actingweb.trust_permissions import TrustPermissionStore

        config = self._create_mock_config(notify_peer_on_change=True)
        store = TrustPermissionStore(config)
        permissions = self._create_permissions()

        with (
            patch.object(
                store, "_store_permissions_internal", return_value=True
            ) as mock_store,
            patch.object(store, "_notify_peer") as mock_notify,
        ):
            result = store.store_permissions(permissions)

            assert result is True
            mock_store.assert_called_once_with(permissions)
            mock_notify.assert_called_once_with(permissions)

    def test_store_permissions_skips_notify_when_storage_fails(self):
        """
        Test that _notify_peer is not called when storage fails.
        """
        from unittest.mock import patch

        from actingweb.trust_permissions import TrustPermissionStore

        config = self._create_mock_config(notify_peer_on_change=True)
        store = TrustPermissionStore(config)
        permissions = self._create_permissions()

        with (
            patch.object(
                store, "_store_permissions_internal", return_value=False
            ) as mock_store,
            patch.object(store, "_notify_peer") as mock_notify,
        ):
            result = store.store_permissions(permissions)

            assert result is False
            mock_store.assert_called_once_with(permissions)
            mock_notify.assert_not_called()

    def test_store_permissions_respects_notify_peer_false_override(self):
        """
        Test that notify_peer=False parameter disables notification.
        """
        from unittest.mock import patch

        from actingweb.trust_permissions import TrustPermissionStore

        config = self._create_mock_config(notify_peer_on_change=True)
        store = TrustPermissionStore(config)
        permissions = self._create_permissions()

        with (
            patch.object(store, "_store_permissions_internal", return_value=True),
            patch.object(store, "_notify_peer") as mock_notify,
        ):
            result = store.store_permissions(permissions, notify_peer=False)

            assert result is True
            mock_notify.assert_not_called()

    def test_store_permissions_respects_notify_peer_true_override(self):
        """
        Test that notify_peer=True parameter enables notification even when config disables it.
        """
        from unittest.mock import patch

        from actingweb.trust_permissions import TrustPermissionStore

        config = self._create_mock_config(notify_peer_on_change=False)
        store = TrustPermissionStore(config)
        permissions = self._create_permissions()

        with (
            patch.object(store, "_store_permissions_internal", return_value=True),
            patch.object(store, "_notify_peer") as mock_notify,
        ):
            result = store.store_permissions(permissions, notify_peer=True)

            assert result is True
            mock_notify.assert_called_once_with(permissions)

    def test_store_permissions_skips_notify_when_config_disables(self):
        """
        Test that notification is skipped when config.notify_peer_on_change=False.
        """
        from unittest.mock import patch

        from actingweb.trust_permissions import TrustPermissionStore

        config = self._create_mock_config(notify_peer_on_change=False)
        store = TrustPermissionStore(config)
        permissions = self._create_permissions()

        with (
            patch.object(store, "_store_permissions_internal", return_value=True),
            patch.object(store, "_notify_peer") as mock_notify,
        ):
            result = store.store_permissions(permissions)

            assert result is True
            mock_notify.assert_not_called()

    def test_notification_failure_does_not_affect_storage_result(self):
        """
        Test that _notify_peer exceptions don't affect store_permissions return value.

        This is the fire-and-forget behavior requirement.
        """
        from unittest.mock import patch

        from actingweb.trust_permissions import TrustPermissionStore

        config = self._create_mock_config(notify_peer_on_change=True)
        store = TrustPermissionStore(config)
        permissions = self._create_permissions()

        with (
            patch.object(store, "_store_permissions_internal", return_value=True),
            patch.object(store, "_notify_peer", side_effect=Exception("Network error")),
        ):
            # Should not raise, and should still return True
            result = store.store_permissions(permissions)
            assert result is True

    def test_should_notify_peer_returns_param_when_provided(self):
        """
        Test that _should_notify_peer returns the parameter when explicitly provided.
        """
        from actingweb.trust_permissions import TrustPermissionStore

        config = self._create_mock_config(notify_peer_on_change=True)
        store = TrustPermissionStore(config)

        assert store._should_notify_peer(True) is True
        assert store._should_notify_peer(False) is False

    def test_should_notify_peer_returns_config_when_param_is_none(self):
        """
        Test that _should_notify_peer returns config value when param is None.
        """
        from actingweb.trust_permissions import TrustPermissionStore

        config_enabled = self._create_mock_config(notify_peer_on_change=True)
        store_enabled = TrustPermissionStore(config_enabled)
        assert store_enabled._should_notify_peer(None) is True

        config_disabled = self._create_mock_config(notify_peer_on_change=False)
        store_disabled = TrustPermissionStore(config_disabled)
        assert store_disabled._should_notify_peer(None) is False

    def test_build_callback_data_structure(self):
        """
        Test that _build_callback_data returns the expected payload structure.

        _build_callback_data now sends effective permissions (merged with base
        trust-type defaults). We mock the registry to return no base permissions
        so only the overrides appear.
        """
        from unittest.mock import Mock, patch

        from actingweb.trust_permissions import TrustPermissionStore

        config = self._create_mock_config()
        store = TrustPermissionStore(config)
        permissions = self._create_permissions()

        # Mock the registry to return a trust type with no base permissions
        mock_registry_instance = Mock()
        mock_trust_type = Mock()
        mock_trust_type.base_permissions = {}
        mock_registry_instance.get_type.return_value = mock_trust_type

        with patch(
            "actingweb.trust_type_registry.get_registry",
            return_value=mock_registry_instance,
        ):
            callback_data = store._build_callback_data(permissions)

        assert callback_data["id"] == "actor123"
        assert callback_data["target"] == "permissions"
        assert callback_data["type"] == "permission"
        assert "timestamp" in callback_data
        assert "data" in callback_data
        assert callback_data["data"]["properties"] == {"patterns": ["public/*"]}


class TestTrustPermissionStoreAsyncNotifications:
    """
    Unit tests for async notification functionality.

    Uses pytest-asyncio for async test support.
    """

    def _create_mock_config(self, notify_peer_on_change: bool = True) -> Any:
        """Create a mock config object."""
        from unittest.mock import Mock

        config = Mock()
        config.notify_peer_on_change = notify_peer_on_change
        config.database = "dynamodb"
        return config

    def _create_permissions(self) -> Any:
        """Create a test TrustPermissions object."""
        from actingweb.trust_permissions import TrustPermissions

        return TrustPermissions(
            actor_id="actor123",
            peer_id="peer456",
            trust_type="friend",
            properties={"patterns": ["public/*"]},
        )

    async def test_store_permissions_async_calls_notify_peer_async(self):
        """
        Test that store_permissions_async() calls _notify_peer_async when storage succeeds.
        """
        import asyncio
        from unittest.mock import AsyncMock, patch

        from actingweb.trust_permissions import TrustPermissionStore

        config = self._create_mock_config(notify_peer_on_change=True)
        store = TrustPermissionStore(config)
        permissions = self._create_permissions()

        # Track created tasks so we can await them
        created_tasks = []
        # Save original create_task to avoid recursion
        original_create_task = asyncio.create_task

        def mock_create_task(coro):
            task = original_create_task(coro)
            created_tasks.append(task)
            return task

        with (
            patch.object(store, "_store_permissions_internal", return_value=True),
            patch.object(
                store, "_notify_peer_async", new_callable=AsyncMock
            ) as mock_notify,
            patch("asyncio.create_task", side_effect=mock_create_task),
        ):
            result = await store.store_permissions_async(permissions)

            assert result is True

            # Wait for the background task to complete
            if created_tasks:
                await asyncio.gather(*created_tasks)

            mock_notify.assert_called_once_with(permissions)

    async def test_store_permissions_async_skips_notify_when_storage_fails(self):
        """
        Test that _notify_peer_async is not called when storage fails.
        """
        from unittest.mock import AsyncMock, patch

        from actingweb.trust_permissions import TrustPermissionStore

        config = self._create_mock_config(notify_peer_on_change=True)
        store = TrustPermissionStore(config)
        permissions = self._create_permissions()

        with (
            patch.object(store, "_store_permissions_internal", return_value=False),
            patch.object(
                store, "_notify_peer_async", new_callable=AsyncMock
            ) as mock_notify,
        ):
            result = await store.store_permissions_async(permissions)

            assert result is False
            mock_notify.assert_not_called()

    async def test_store_permissions_async_respects_notify_peer_override(self):
        """
        Test that notify_peer parameter overrides config in async version.
        """
        from unittest.mock import AsyncMock, patch

        from actingweb.trust_permissions import TrustPermissionStore

        config = self._create_mock_config(notify_peer_on_change=True)
        store = TrustPermissionStore(config)
        permissions = self._create_permissions()

        with (
            patch.object(store, "_store_permissions_internal", return_value=True),
            patch.object(
                store, "_notify_peer_async", new_callable=AsyncMock
            ) as mock_notify,
        ):
            result = await store.store_permissions_async(permissions, notify_peer=False)

            assert result is True
            mock_notify.assert_not_called()


class TestThePermissionSenderResendsA503:
    """Verification reverify-2, Issue 1: a receiver answers 503 when it
    cannot store a callback for now; the sender resends the same body (its
    timestamp orders it), a bounded number of times."""

    BODY = {"type": "permission", "timestamp": "2026-11-08T12:00:00+00:00"}

    def _store(self) -> Any:
        from unittest.mock import Mock

        from actingweb.trust_permissions import TrustPermissionStore

        config = Mock()
        config.notify_peer_on_change = True
        config.database = "dynamodb"
        return TrustPermissionStore(config)

    def _permissions(self) -> Any:
        from actingweb.trust_permissions import TrustPermissions

        return TrustPermissions(actor_id="a", peer_id="p", trust_type="friend")

    def test_the_sync_sender_resends_the_same_body(self) -> None:
        from unittest.mock import patch

        store = self._store()
        codes = iter([503, 204])
        with (
            patch("actingweb.aw_proxy.AwProxy") as proxy_class,
            patch.object(store, "_build_callback_data", return_value=dict(self.BODY)),
            patch("actingweb.trust_permissions.time.sleep") as sleep,
        ):
            proxy = proxy_class.return_value
            proxy.trust = {"baseuri": "https://p.example.test/p"}

            def answer(**_kwargs: Any) -> dict[str, Any]:
                proxy.last_response_code = next(codes)
                return {}

            proxy.create_resource.side_effect = answer
            store._notify_peer(self._permissions())  # noqa: SLF001
        bodies = [c.kwargs["params"] for c in proxy.create_resource.call_args_list]
        assert bodies == [self.BODY, self.BODY]
        sleep.assert_called_once()

    def test_the_sync_sender_gives_up_after_two_resends(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Reverify-3, Issue 2: the receiver's 503 has no body, which the
        proxy returns as {}; the final failure is still a WARNING."""
        import logging
        from unittest.mock import patch

        store = self._store()
        with (
            patch("actingweb.aw_proxy.AwProxy") as proxy_class,
            patch.object(store, "_build_callback_data", return_value=dict(self.BODY)),
            patch("actingweb.trust_permissions.time.sleep"),
            caplog.at_level(logging.WARNING, logger="actingweb.trust_permissions"),
        ):
            proxy = proxy_class.return_value
            proxy.trust = {"baseuri": "https://p.example.test/p"}
            proxy.last_response_code = 503
            proxy.create_resource.return_value = {}
            store._notify_peer(self._permissions())  # noqa: SLF001
        assert proxy.create_resource.call_count == 3
        assert any(
            "Failed to notify" in r.getMessage() and "status=503" in r.getMessage()
            for r in caplog.records
        )

    async def test_the_async_sender_resends_after_retry_after(self) -> None:
        from unittest.mock import AsyncMock, Mock, patch

        store = self._store()
        busy = Mock(status_code=503, headers={"Retry-After": "1"})
        done = Mock(status_code=204, headers={})
        client = AsyncMock()
        client.post = AsyncMock(side_effect=[busy, done])
        client.__aenter__.return_value = client
        with (
            patch("actingweb.trust.Trust") as trust_class,
            patch("httpx.AsyncClient", return_value=client),
            patch.object(store, "_build_callback_data", return_value=dict(self.BODY)),
            patch(
                "actingweb.trust_permissions.asyncio.sleep", new_callable=AsyncMock
            ) as sleep,
        ):
            trust_class.return_value.get.return_value = {
                "baseuri": "https://p.example.test/p",
                "secret": "s",
            }
            await store._notify_peer_async(self._permissions())  # noqa: SLF001
        bodies = [c.kwargs["json"] for c in client.post.call_args_list]
        assert bodies == [self.BODY, self.BODY]
        sleep.assert_awaited_once_with(1.0)

    def test_retry_after_is_capped_and_defaulted(self) -> None:
        from actingweb.trust_permissions import _retry_after

        assert _retry_after("30") == 2.0
        assert _retry_after(None) == 1.0
        assert _retry_after("soon") == 1.0
        assert _retry_after("nan") == 1.0
        assert _retry_after("-3") == 0.0


def test_an_update_cannot_change_whose_override_it_is() -> None:
    """Re-run 6 (Issue 1): ``update_permissions`` copied any field the
    request named; the store keys on ``actor_id`` and ``peer_id``, so an
    owner's PUT with ``{"actor_id": "victim", ...}`` wrote a grant into
    another actor's store, with the ``trust_type`` of its choice."""
    from unittest import mock

    from actingweb.trust_permissions import TrustPermissions, TrustPermissionStore

    store = object.__new__(TrustPermissionStore)
    existing = TrustPermissions(
        actor_id="a1",
        peer_id="p1",
        trust_type="viewer",
        properties={"patterns": ["public/*"], "operations": ["read"]},
    )
    written: list[TrustPermissions] = []
    with (
        mock.patch.object(store, "get_permissions", return_value=existing),
        mock.patch.object(
            store,
            "store_permissions",
            side_effect=lambda p, **kw: written.append(p) or True,
        ),
    ):
        assert store.update_permissions(
            "a1",
            "p1",
            {
                "actor_id": "victim",
                "peer_id": "attacker",
                "trust_type": "admin",
                "created_by": "x",
                "notes": "ok",
                "methods": {"allowed": ["m"]},
            },
        )
    assert len(written) == 1
    stored = written[0]
    assert (stored.actor_id, stored.peer_id, stored.trust_type) == (
        "a1",
        "p1",
        "viewer",
    )
    assert stored.created_by == "system"
    assert stored.notes == "ok" and stored.methods == {"allowed": ["m"]}


def test_a_rule_list_that_is_not_a_list_keeps_the_base_value() -> None:
    """Re-run 9 (Issue 1): a ``null`` or a string in a rule list replaced the
    trust type's list on merge, dropping its base exclusions; a row stored
    before the intake check, or through the store API, is covered here."""
    from actingweb.trust_permissions import (
        merge_permissions,
        permission_updates_problem,
    )

    base = {"properties": {"patterns": ["*"], "excluded_patterns": ["private/*"]}}
    for bad in (None, "private/*", [1]):
        merged = merge_permissions(base, {"properties": {"excluded_patterns": bad}})
        assert merged["properties"]["excluded_patterns"] == ["private/*"]
        assert permission_updates_problem({"properties": {"excluded_patterns": bad}})
    assert permission_updates_problem({"properties": {"patterns": ["a"]}}) is None


def test_a_malformed_override_allows_less_never_more() -> None:
    """Re-run 10 (Issue 1): keeping the trust type's value is fail-closed
    only for exclusions; for an allow list, or a category that is not an
    object, it handed out the trust type's wider grant where the override
    used to deny. Through the evaluator."""
    from actingweb.permission_evaluator import (
        PermissionEvaluator,
        PermissionResult,
        PermissionType,
    )
    from actingweb.trust_permissions import merge_permissions

    base = {
        "properties": {
            "patterns": ["*"],
            "operations": ["read", "write"],
            "excluded_patterns": ["private/*"],
        },
        "methods": {"allowed": ["*"]},
        "tools": {"allowed": ["*"]},
    }
    cases = [
        (
            {"properties": {"operations": "read"}},
            PermissionType.PROPERTIES,
            "x",
            "write",
        ),
        ({"methods": {"allowed": None}}, PermissionType.METHODS, "m", "call"),
        ({"methods": {"allowed": "get_x"}}, PermissionType.METHODS, "m", "call"),
        ({"methods": ["x"]}, PermissionType.METHODS, "m", "call"),
        ({"tools": []}, PermissionType.TOOLS, "search", "call"),
        ({"properties": "everything"}, PermissionType.PROPERTIES, "x", "read"),
        (
            {"properties": {"excluded_patterns": "x"}},
            PermissionType.PROPERTIES,
            "x",
            "read",
        ),
    ]
    # (``patterns`` is a union field: no override narrows it, so a malformed
    # one is an empty one, as a valid empty override is.)
    ev = object.__new__(PermissionEvaluator)
    ev.config = None  # type: ignore[misc]
    for override, kind, target, op in cases:
        merged = merge_permissions(base, override)
        ev._get_effective_permissions = lambda a, p, m=merged, **k: m  # type: ignore[method-assign]
        ev._approval = lambda a, p: (False, "friend")  # type: ignore[method-assign]
        result = ev.evaluate_permission("a1", "p1", kind, target, op)
        assert result == PermissionResult.DENIED, (override, result)
    # A category it does not name is the trust type's, as before.
    merged = merge_permissions(base, {"methods": ["x"]})
    assert merged["tools"] == base["tools"]
