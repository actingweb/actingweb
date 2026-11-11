"""
Tests for trust handler permission management functionality.

This test suite verifies that the trust handler properly supports
per-relationship permission management as specified in the ActingWeb spec.
"""

import json
import unittest
from unittest.mock import Mock, patch

from actingweb.handlers.trust import TrustPeerHandler, TrustPermissionHandler
from actingweb.trust_permissions import TrustPermissions


class TestTrustHandlerPermissions(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures."""
        self.config = Mock()
        self.request = Mock()
        self.response = Mock()
        self.response.headers = {}

        # Mock request body
        self.request.body = json.dumps(
            {
                "properties": {"allowed": ["public/*"], "denied": ["private/*"]},
                "methods": {"allowed": ["get_profile"]},
                "notes": "Test permission override",
            }
        ).encode("utf-8")

        # Mock auth response
        self.auth_response = Mock()
        self.auth_response.response = {"code": 200}
        self.auth_response.check_authorisation = Mock(return_value=True)
        self.auth_response.trust = None  # Add trust attribute

        # Mock actor
        self.actor = Mock()
        self.actor.get_trust_relationships = Mock(
            return_value=[
                {
                    "peerid": "test-peer",
                    "relationship": "friend",
                    "approved": True,
                    "verified": True,
                }
            ]
        )
        # The PUT reads the row first (3.16: 404 for a missing row or another
        # relationship).
        self.actor.get_trust_relationship = Mock(
            return_value=self.actor.get_trust_relationships.return_value[0]
        )
        self.actor.modify_trust_and_notify = Mock(return_value=True)

        # Mock permission store
        self.permission_store = Mock()
        self.permission_store.get_permissions = Mock()
        self.permission_store.store_permissions = Mock(return_value=True)
        self.permission_store.update_permissions = Mock(return_value=True)
        self.permission_store.delete_permissions = Mock(return_value=True)

    def _mock_authentication(self, handler):
        """Helper method to mock authentication for handlers."""
        auth_result = Mock()
        auth_result.success = True
        auth_result.actor = self.actor
        auth_result.auth_obj = self.auth_response

        # Mock both possible authentication methods
        handler.authenticate_actor = Mock(return_value=auth_result)
        handler.require_authenticated_actor = Mock(return_value=self.actor)
        return auth_result

    @patch("actingweb.handlers.trust.PERMISSION_SYSTEM_AVAILABLE", True)
    @patch("actingweb.handlers.trust.get_trust_permission_store")
    @patch("actingweb.trust.Trust")
    def test_get_trust_with_permissions_query(self, mock_trust, mock_get_store):
        """Test GET /trust/{relationship}/{peerid}?permissions=true"""
        mock_get_store.return_value = self.permission_store

        # Create test permissions
        test_permissions = TrustPermissions(
            actor_id="test-actor",
            peer_id="test-peer",
            trust_type="friend",
            properties={"allowed": ["public/*"]},
            methods={"allowed": ["get_profile"]},
            notes="Test permissions",
        )
        self.permission_store.get_permissions.return_value = test_permissions

        handler = TrustPeerHandler(config=self.config)
        handler.request = Mock()
        handler.request.get = Mock(
            side_effect=lambda key: "true" if key == "permissions" else None
        )
        handler.response = self.response

        # Mock authentication
        self._mock_authentication(handler)

        handler.get("test-actor", "friend", "test-peer")

        # Verify response includes permission data
        self.response.write.assert_called_once()
        response_data = json.loads(self.response.write.call_args[0][0])
        self.assertIn("permissions", response_data)
        self.assertEqual(
            response_data["permissions"]["properties"], {"allowed": ["public/*"]}
        )
        self.assertEqual(
            response_data["permissions"]["methods"], {"allowed": ["get_profile"]}
        )
        self.assertEqual(response_data["permissions"]["notes"], "Test permissions")

    @patch("actingweb.handlers.trust.PERMISSION_SYSTEM_AVAILABLE", True)
    @patch("actingweb.handlers.trust.get_trust_permission_store")
    @patch("actingweb.handlers.trust.create_permission_override")
    def test_put_trust_with_permissions(self, mock_create_override, mock_get_store):
        """Test PUT /trust/{relationship}/{peerid} with permission updates"""
        mock_get_store.return_value = self.permission_store

        # No existing permissions
        self.permission_store.get_permissions.return_value = None
        self.permission_store.get_permissions_uncached.return_value = None

        # Mock permission creation
        mock_permissions = Mock()
        mock_create_override.return_value = mock_permissions

        handler = TrustPeerHandler(config=self.config)
        handler.request = self.request
        handler.response = self.response

        # Mock authentication
        self._mock_authentication(handler)

        # Mock request body with permissions
        handler.request.body = json.dumps(
            {
                "approved": True,
                "desc": "Test relationship",
                "permissions": {
                    "properties": {"allowed": ["public/*"], "denied": ["private/*"]},
                    "methods": {"allowed": ["get_profile"]},
                },
            }
        ).encode("utf-8")

        handler.put("test-actor", "friend", "test-peer")

        # Verify trust update and permission creation
        self.actor.modify_trust_and_notify.assert_called_once()
        mock_create_override.assert_called_once_with(
            actor_id="test-actor",
            peer_id="test-peer",
            trust_type="friend",
            permission_updates={
                "properties": {"allowed": ["public/*"], "denied": ["private/*"]},
                "methods": {"allowed": ["get_profile"]},
            },
        )
        # Stored silently; the peer is told once the trust write landed (3.16).
        self.permission_store.store_permissions.assert_called_once_with(
            mock_permissions, notify_peer=False
        )
        self.permission_store.notify_stored_grant.assert_called_once_with(
            "test-actor", "test-peer"
        )

    @patch("actingweb.handlers.trust.PERMISSION_SYSTEM_AVAILABLE", True)
    @patch("actingweb.handlers.trust.get_trust_permission_store")
    def test_get_trust_permissions_handler(self, mock_get_store):
        """Test GET /trust/{relationship}/{peerid}/permissions"""
        mock_get_store.return_value = self.permission_store

        # Mock existing permissions
        test_permissions = TrustPermissions(
            actor_id="test-actor",
            peer_id="test-peer",
            trust_type="friend",
            properties={"allowed": ["public/*"]},
            methods={"allowed": ["get_profile"]},
            notes="Test permissions",
        )
        self.permission_store.get_permissions.return_value = test_permissions

        handler = TrustPermissionHandler(config=self.config)
        handler.request = Mock()
        handler.response = self.response

        # Mock authentication
        self._mock_authentication(handler)

        handler.get("test-actor", "friend", "test-peer")

        # Verify response
        self.response.write.assert_called_once()
        response_data = json.loads(self.response.write.call_args[0][0])

        self.assertEqual(response_data["actor_id"], "test-actor")
        self.assertEqual(response_data["peer_id"], "test-peer")
        self.assertEqual(response_data["trust_type"], "friend")
        self.assertEqual(response_data["properties"], {"allowed": ["public/*"]})
        self.assertEqual(response_data["methods"], {"allowed": ["get_profile"]})
        self.assertEqual(response_data["notes"], "Test permissions")


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# 3.16 (plan grant-enforcement-per-route, Phase 4): the PUT writes the grant
# first, then the trust; a failure leaves both as they were. Real storage.
# ---------------------------------------------------------------------------

import base64  # noqa: E402
from typing import Any  # noqa: E402
from unittest import mock  # noqa: E402

import pytest  # noqa: E402

from actingweb.actor import Actor  # noqa: E402
from actingweb.aw_web_request import AWWebObj  # noqa: E402
from actingweb.db.exceptions import DbError  # noqa: E402
from actingweb.trust_permissions import (  # noqa: E402
    TrustPermissionStore,
    get_trust_permission_store,
)
from tests._adoption_helpers import aid  # noqa: E402
from tests.test_trust_re_pair import PASSPHRASE, Receiver  # noqa: E402

NEW_GRANT = {"properties": {"patterns": ["new/*"], "operations": ["read"]}}


def _put(w: Receiver, body: dict[str, Any]) -> int:
    token = base64.b64encode(f"{w.a.creator}:{PASSPHRASE}".encode()).decode()
    webobj = AWWebObj(
        url="https://test.example.com/x",
        body=json.dumps(body),
        headers={"Authorization": f"Basic {token}"},
    )
    TrustPeerHandler(webobj, w.config).put(aid(w.a), "friend", w.b)
    return webobj.response.status_code


def _patterns(w: Receiver) -> Any:
    grant = get_trust_permission_store(w.config).get_permissions_uncached(aid(w.a), w.b)
    return grant.properties if grant else None


class TestThePutOrder:
    def test_a_failed_grant_write_leaves_the_row_unapproved_and_untold(self) -> None:
        w = Receiver(approved=False)
        with (
            mock.patch.object(Actor, "reverify_pending_trust", return_value=True),
            mock.patch.object(
                TrustPermissionStore, "update_permissions", return_value=False
            ),
            mock.patch("actingweb.actor.requests.post") as told,
        ):
            assert _put(w, {"approved": True, "permissions": NEW_GRANT}) == 500
        assert w.row(w.b)["approved"] is False
        told.assert_not_called()

    def test_a_failed_modify_restores_the_previous_grant(self) -> None:
        w = Receiver()
        before = _patterns(w)
        with mock.patch.object(Actor, "modify_trust_and_notify", return_value=False):
            assert _put(w, {"desc": "x", "permissions": NEW_GRANT}) == 400
        assert _patterns(w) == before

    def test_a_faulting_modify_restores_the_previous_grant(self) -> None:
        w = Receiver()
        before = _patterns(w)
        with (
            mock.patch.object(
                Actor,
                "modify_trust_and_notify",
                side_effect=DbError("trust write", aid(w.a)),
            ),
            pytest.raises(DbError),
        ):
            _put(w, {"desc": "x", "permissions": NEW_GRANT})
        assert _patterns(w) == before

    def test_a_failed_modify_restores_what_the_store_holds_not_the_cache(
        self,
    ) -> None:
        """Verification 2026-11-10, Issue 8: another process changed the
        override; this one's cache is stale."""
        w = Receiver()
        before = _patterns(w)
        store = get_trust_permission_store(w.config)
        stale = store.get_permissions_uncached(aid(w.a), w.b)
        assert stale is not None
        stale_copy = TrustPermissions.from_dict(
            {**stale.to_dict(), "properties": {"patterns": ["stale/*"]}}
        )
        store._cache[f"{aid(w.a)}:{w.b}"] = stale_copy
        with mock.patch.object(Actor, "modify_trust_and_notify", return_value=False):
            assert _put(w, {"desc": "x", "permissions": NEW_GRANT}) == 400
        assert _patterns(w) == before

    def test_a_restore_that_faults_raises_and_the_row_stays_unapproved(
        self,
    ) -> None:
        """Verification 2026-11-10: the restore-itself-faults branch. The new
        override is left on a row the failed write left unapproved, which
        grants nothing (peer-authorisation A1)."""
        w = Receiver(approved=False)
        real_store = TrustPermissionStore.store_permissions

        def store_then_fault(
            self: Any, permissions: Any, notify_peer: Any = None
        ) -> Any:
            if notify_peer is False and "kept/*" in repr(permissions.properties):
                raise DbError("permissions write", aid(w.a))  # the restore
            return real_store(self, permissions, notify_peer=notify_peer)

        with (
            mock.patch.object(Actor, "reverify_pending_trust", return_value=True),
            mock.patch.object(Actor, "modify_trust_and_notify", return_value=False),
            mock.patch.object(
                TrustPermissionStore, "store_permissions", store_then_fault
            ),
            pytest.raises(DbError),
        ):
            _put(w, {"approved": True, "permissions": NEW_GRANT})
        assert w.row(w.b)["approved"] is False

    def test_a_failed_modify_removes_a_grant_it_created(self) -> None:
        w = Receiver()
        assert get_trust_permission_store(w.config).delete_permissions(aid(w.a), w.b)
        with mock.patch.object(Actor, "modify_trust_and_notify", return_value=False):
            assert _put(w, {"desc": "x", "permissions": NEW_GRANT}) == 400
        assert _patterns(w) is None

    def test_the_peer_is_told_only_once_the_trust_write_landed(self) -> None:
        w = Receiver()
        with (
            mock.patch.object(TrustPermissionStore, "_notify_peer") as told,
            mock.patch.object(Actor, "modify_trust_and_notify", return_value=False),
        ):
            assert _put(w, {"desc": "x", "permissions": NEW_GRANT}) == 400
        told.assert_not_called()

        with mock.patch.object(TrustPermissionStore, "_notify_peer") as told:
            assert _put(w, {"desc": "x", "permissions": NEW_GRANT}) == 204
        told.assert_called_once()
        assert "new/*" in repr(told.call_args.args[0].properties)

    def test_a_successful_put_keeps_the_new_grant(self) -> None:
        w = Receiver()
        assert _put(w, {"desc": "x", "permissions": NEW_GRANT}) == 204
        assert "new/*" in repr(_patterns(w))
