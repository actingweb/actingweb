"""An existing OAuth2/MCP client's row at its next authorisation (3.16,
verification 2026-11-10 of the grant-enforcement plan, Issues 6 and 10).

No code without the trust: a row deleted between the read and the write
answers False (it answered True, and a code was issued for a row that no
longer stood). A re-type removes the override written for the old type
before the row changes, so a failed removal leaves the row as it was. The
default description follows the client's name at every authorisation, not
only at a re-type. Real storage; both backends through ``DATABASE_BACKEND``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest import mock

import pytest

from actingweb.db import get_trust
from actingweb.interface.actor_interface import ActorInterface
from actingweb.trust import Trust
from actingweb.trust_permissions import (
    TrustPermissions,
    TrustPermissionStore,
    get_trust_permission_store,
    initialize_trust_permission_store,
)
from tests._adoption_helpers import aid, create_core_actor, make_config, uuid_email

EMAIL = "user@example.test"


@pytest.fixture(autouse=True)
def no_registry() -> Iterator[None]:
    """The trust type names are used as given (no registry fallback)."""
    with mock.patch(
        "actingweb.trust_type_registry.get_registry", side_effect=RuntimeError
    ):
        yield


class World:
    def __init__(self) -> None:
        self.config = make_config()
        initialize_trust_permission_store(self.config)
        self.actor = create_core_actor(self.config, uuid_email())
        self.trust = ActorInterface(self.actor).trust

    def authorise(self, trust_type: str, client_name: str = "Claude") -> bool:
        return self.trust.create_or_update_oauth_trust(
            EMAIL,
            trust_type,
            established_via="oauth2_client",
            client_id="mcp_0123456789abcdef",
            client_name=client_name,
        )

    def row(self) -> dict[str, Any]:
        rows = [
            r
            for r in self.actor.get_trust_relationships()
            if str(r.get("peerid", "")).startswith("oauth2_client:")
        ]
        assert len(rows) == 1
        return rows[0]


def test_a_row_deleted_during_the_update_issues_no_code() -> None:
    w = World()
    assert w.authorise("mcp_client")
    with mock.patch.object(type(get_trust(w.config)), "modify", return_value=False):
        assert w.authorise("mcp_client") is False


def test_a_row_gone_before_the_update_issues_no_code() -> None:
    w = World()
    assert w.authorise("mcp_client")
    real_get = type(get_trust(w.config)).get
    calls = {"n": 0}

    def gone_on_second_read(self: Any, *a: Any, **kw: Any) -> Any:
        calls["n"] += 1
        # The manager's existence check reads first; the update branch's
        # own read then finds nothing (the row went in between).
        return None if calls["n"] >= 2 else real_get(self, *a, **kw)

    with mock.patch.object(type(get_trust(w.config)), "get", gone_on_second_read):
        assert w.authorise("mcp_client") is False


def test_a_failed_override_removal_still_re_types() -> None:
    """Owner decision 2026-11-11 (re-run 3, Issue 2): the override for the
    old type is inert once the row changed, so a removal that fails is
    cleanup left for the next authorisation, not a reason to roll back (each
    rollback raced a concurrent authorisation)."""
    w = World()
    assert w.authorise("friend")
    peer = str(w.row()["peerid"])
    store = get_trust_permission_store(w.config)
    assert store.store_permissions(
        TrustPermissions(
            actor_id=aid(w.actor),
            peer_id=peer,
            trust_type="friend",
            properties={"patterns": ["*"], "operations": ["read"]},
        ),
        notify_peer=False,
    )
    with mock.patch.object(
        TrustPermissionStore, "delete_permissions", return_value=False
    ):
        assert w.authorise("viewer")
    assert w.row()["relationship"] == "viewer"
    assert store.get_permissions_uncached(aid(w.actor), peer) is not None
    assert w.authorise("viewer")
    assert store.get_permissions_uncached(aid(w.actor), peer) is None


def test_the_description_follows_the_name_without_a_re_type() -> None:
    w = World()
    assert w.authorise("mcp_client")
    peer = str(w.row()["peerid"])
    assert Trust(actor_id=aid(w.actor), peerid=peer, config=w.config).modify(
        desc=f"OAuth2 client: {EMAIL}"
    )
    assert w.authorise("mcp_client", client_name="Claude Desktop")
    assert w.row()["desc"] == "OAuth2 client: Claude Desktop"


def test_a_re_type_evicts_the_actors_mcp_caches() -> None:
    """Verification 2026-11-10 ("the next tools/list reflects the re-type"):
    the MCP caches holding the old level are evicted once the row changed,
    and not when it did not."""
    w = World()
    assert w.authorise("friend")
    with mock.patch("actingweb.mcp.invalidation.evict_caches_for_actor") as evict:
        assert w.authorise("friend")
        evict.assert_not_called()
        assert w.authorise("viewer")
        evict.assert_called_with(aid(w.actor))


def test_a_failed_type_change_keeps_the_override() -> None:
    """Code review 2026-11-10: the override was removed before the type
    changed, so a failed change left the old type without its override
    (which can be wider). The type changes first now."""
    w = World()
    assert w.authorise("friend")
    peer = str(w.row()["peerid"])
    store = get_trust_permission_store(w.config)
    assert store.store_permissions(
        TrustPermissions(
            actor_id=aid(w.actor),
            peer_id=peer,
            trust_type="friend",
            properties={"patterns": ["public/*"], "operations": ["read"]},
        ),
        notify_peer=False,
    )
    with mock.patch.object(type(get_trust(w.config)), "modify", return_value=False):
        assert w.authorise("viewer") is False
    assert w.row()["relationship"] == "friend"
    assert store.get_permissions_uncached(aid(w.actor), peer) is not None


def _friend_with_override(w: World) -> tuple[str, TrustPermissionStore]:
    assert w.authorise("friend")
    peer = str(w.row()["peerid"])
    store = get_trust_permission_store(w.config)
    assert store.store_permissions(
        TrustPermissions(
            actor_id=aid(w.actor),
            peer_id=peer,
            trust_type="friend",
            properties={"patterns": ["*"], "operations": ["read", "write"]},
        ),
        notify_peer=False,
    )
    return peer, store


def test_a_faulting_override_removal_still_re_types() -> None:
    """Re-run 3 (Issue 2): a ``DbError`` from the cleanup is logged, the
    re-type stands (the override it left is not applied), and the next
    authorisation removes it."""
    from actingweb.db.exceptions import DbError

    w = World()
    peer, store = _friend_with_override(w)
    with mock.patch.object(
        TrustPermissionStore, "delete_permissions", side_effect=DbError("down")
    ):
        assert w.authorise("viewer")
    assert w.row()["relationship"] == "viewer"
    assert store.get_permissions_uncached(aid(w.actor), peer) is not None
    assert w.authorise("viewer")
    assert store.get_permissions_uncached(aid(w.actor), peer) is None


def test_an_override_for_the_approved_type_stays() -> None:
    """The same type authorised again keeps an override written for it."""
    w = World()
    peer, store = _friend_with_override(w)
    assert w.authorise("friend")
    assert store.get_permissions_uncached(aid(w.actor), peer) is not None


def test_an_override_for_another_type_is_removed_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Owner decision 2026-11-10 (re-run 2, Issue 4): a client's override
    naming another type is removed at the next authorisation, the type
    unchanged, and the removal is logged."""
    w = World()
    assert w.authorise("mcp_client")
    peer = str(w.row()["peerid"])
    store = get_trust_permission_store(w.config)
    assert store.store_permissions(
        TrustPermissions(
            actor_id=aid(w.actor),
            peer_id=peer,
            trust_type="viewer",
            properties={"patterns": ["public/*"], "operations": ["read"]},
        ),
        notify_peer=False,
    )
    with caplog.at_level("WARNING", logger="actingweb.interface.trust_manager"):
        assert w.authorise("mcp_client")
    assert store.get_permissions_uncached(aid(w.actor), peer) is None
    assert any("'viewer' was removed" in r.getMessage() for r in caplog.records)


class TestAClientOverrideForAnotherTypeIsInert:
    """Owner decision 2026-11-11 (re-run 3, Issue 2): the evaluator does not
    apply an OAuth2/MCP client's override that names a type other than the
    row's, so a stale one can never decide; a peer's override is applied as
    before."""

    @staticmethod
    def _evaluator(override_type: str) -> Any:
        from actingweb.permission_evaluator import PermissionEvaluator

        evaluator = object.__new__(PermissionEvaluator)
        evaluator.permission_store = mock.Mock()
        evaluator.permission_store.get_permissions.return_value = TrustPermissions(
            actor_id="a1",
            peer_id="x",
            trust_type=override_type,
            properties={"patterns": ["*"], "operations": ["read", "write"]},
        )
        registry = mock.Mock()
        registry.get_type.side_effect = lambda name: mock.Mock(
            base_permissions={"properties": {"patterns": [f"{name}/*"]}}
        )
        evaluator.trust_type_registry = registry
        return evaluator

    def test_a_client_s_stale_override_is_not_applied(self) -> None:
        ev = self._evaluator("friend")
        perms = ev._get_effective_permissions(
            "a1", "oauth2_client:u:c", relationship="viewer"
        )
        assert perms == {"properties": {"patterns": ["viewer/*"]}}

    def test_a_client_s_override_for_its_type_is_applied(self) -> None:
        ev = self._evaluator("viewer")
        perms = ev._get_effective_permissions(
            "a1", "oauth2_client:u:c", relationship="viewer"
        )
        assert perms["properties"]["operations"] == ["read", "write"]

    def test_a_peer_s_override_is_applied_whatever_it_names(self) -> None:
        ev = self._evaluator("friend")
        perms = ev._get_effective_permissions("a1", "peer123", relationship="viewer")
        assert perms["properties"]["operations"] == ["read", "write"]
