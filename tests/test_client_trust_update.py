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


def test_an_overlapping_authorisation_s_override_is_kept() -> None:
    """Re-run 4 (Issue 2): the cleanup compared the override with the type
    its own call approved; an overlapping authorisation that wrote the row
    back to the override's type lost the override. It compares with the row
    as stored."""
    w = World()
    peer, store = _friend_with_override(w)
    db_type = type(get_trust(w.config))
    real_modify = db_type.modify

    def other_tab_writes_friend_back(self: Any, *a: Any, **kw: Any) -> Any:
        out = real_modify(self, *a, **kw)
        if kw.get("relationship") == "viewer":
            other = get_trust(w.config)
            assert other.get(actor_id=aid(w.actor), peerid=peer)
            real_modify(other, relationship="friend")
        return out

    with mock.patch.object(db_type, "modify", other_tab_writes_friend_back):
        assert w.authorise("viewer")
    assert w.row()["relationship"] == "friend"
    kept = store.get_permissions_uncached(aid(w.actor), peer)
    assert kept is not None and kept.trust_type == "friend"


def test_a_stale_override_that_cannot_go_does_not_come_back() -> None:
    """Re-run 4 (Issue 2): an inert override left by a failed cleanup came
    back into force when the user approved its type again. It is removed
    before the re-type, and when it cannot be, that approval issues no
    code."""
    w = World()
    peer, store = _friend_with_override(w)
    with mock.patch.object(
        TrustPermissionStore, "delete_permissions", return_value=False
    ):
        assert w.authorise("viewer")  # the friend override is left, inert
        assert w.authorise("friend") is False
    assert w.row()["relationship"] == "viewer"
    assert w.authorise("friend")  # the removal works now: re-typed
    assert w.row()["relationship"] == "friend"
    assert store.get_permissions_uncached(aid(w.actor), peer) is None


def _stale_client(w: World) -> tuple[str, TrustPermissionStore]:
    """A client re-typed friend → viewer whose friend override the cleanup
    could not remove (inert)."""
    peer, store = _friend_with_override(w)
    with mock.patch.object(
        TrustPermissionStore, "delete_permissions", return_value=False
    ):
        assert w.authorise("viewer")
    assert w.row()["relationship"] == "viewer"
    return peer, store


def _owner_handler(w: World, body: Any = None) -> Any:
    import json as _json

    from actingweb.aw_web_request import AWWebObj
    from actingweb.handlers.trust import TrustPermissionHandler

    handler = TrustPermissionHandler(
        AWWebObj(body=_json.dumps(body) if body is not None else None), w.config
    )
    auth = mock.Mock(acl={"peerid": "", "relationship": "creator"})
    result = mock.Mock(success=True, actor=w.actor, auth_obj=auth)
    result.authorize.return_value = True
    return handler, result


def test_the_owner_s_edit_of_a_stale_client_override_applies() -> None:
    """Re-run 4 (Issue 3): the owner's edit kept the stale type, answered
    200 and was never applied. It is written for the row's type."""
    w = World()
    peer, store = _stale_client(w)
    # The stale override also holds a field the edit does not name.
    stale = store.get_permissions_uncached(aid(w.actor), peer)
    assert stale is not None
    stale.methods = {"allowed": ["*"]}
    assert store.store_permissions(stale, notify_peer=False)
    handler, result = _owner_handler(
        w, {"properties": {"patterns": ["public/*"], "operations": ["read"]}}
    )
    with mock.patch.object(handler, "authenticate_actor", return_value=result):
        handler.put(aid(w.actor), "viewer", peer)
    assert handler.response.status_code in (200, 201)
    stored = store.get_permissions_uncached(aid(w.actor), peer)
    assert stored is not None and stored.trust_type == "viewer"
    # Re-run 5 (Issue 1): replaced, not merged: the stale override's other
    # fields, never shown to the owner, do not come into force.
    assert not stored.methods
    assert stored.properties is not None
    assert stored.properties["patterns"] == ["public/*"]


def test_the_owner_does_not_see_a_stale_client_override_as_applied() -> None:
    """Re-run 4 (Issue 3): ``GET .../permissions`` showed the inert override
    as the client's grant."""
    w = World()
    peer, _ = _stale_client(w)
    handler, result = _owner_handler(w)
    with mock.patch.object(handler, "authenticate_actor", return_value=result):
        handler.get(aid(w.actor), "viewer", peer)
    # The defaults' branch answered (this test has no registry, so it
    # reports an error), not the override's.
    assert "custom_override" not in str(handler.response.body)
    assert '"friend"' not in str(handler.response.body)


def test_the_evaluator_reads_the_row_to_decide_a_client_override() -> None:
    """Re-run 4 (Issue 7): with no row type given, the evaluator reads the
    row (real storage) and does not apply a stale client override."""
    from actingweb.permission_evaluator import PermissionEvaluator

    w = World()
    peer, store = _stale_client(w)
    ev = object.__new__(PermissionEvaluator)
    ev.config = w.config
    ev.permission_store = store
    registry = mock.Mock()
    registry.get_type.side_effect = lambda name: mock.Mock(
        base_permissions={"properties": {"patterns": [f"{name}/*"]}}
    )
    ev.trust_type_registry = registry
    assert ev._get_effective_permissions(aid(w.actor), peer) == {
        "properties": {"patterns": ["viewer/*"]}
    }


def test_a_read_fault_before_the_re_type_issues_no_code() -> None:
    """Re-run 5 (Issue 2): a fault reading the override before a re-type
    read as "none left", so a stale override of the approved type could
    come back. An unread override refuses the re-type; the row stays."""
    from actingweb.db.exceptions import DbError

    w = World()
    assert w.authorise("friend")
    with mock.patch.object(
        TrustPermissionStore,
        "get_permissions_uncached",
        side_effect=DbError("down"),
    ):
        assert w.authorise("viewer") is False
    assert w.row()["relationship"] == "friend"
    assert w.authorise("viewer")


def test_the_permissions_get_answers_only_for_the_row_s_type() -> None:
    """Re-run 5 (Issue 4): the GET decided what applies by the path's type,
    which it never compared with the row's; the stale type's path showed
    the unapplied override as the grant. It answers 404, as the PUT does."""
    w = World()
    peer, _ = _stale_client(w)
    handler, result = _owner_handler(w)
    with mock.patch.object(handler, "authenticate_actor", return_value=result):
        handler.get(aid(w.actor), "friend", peer)
    assert handler.response.status_code == 404


def test_the_re_type_decides_from_the_row_it_just_read() -> None:
    """Re-run 6 (Issue 3): the decision used an earlier read; an overlapping
    authorisation in between meant no write and a code at the other type."""
    w = World()
    assert w.authorise("viewer")
    stale = w.trust.get_relationship(str(w.row()["peerid"]))
    db = get_trust(w.config)
    assert db.get(actor_id=aid(w.actor), peerid=str(w.row()["peerid"]))
    assert db.modify(relationship="friend")  # the overlapping authorisation
    with mock.patch.object(type(w.trust), "get_relationship", return_value=stale):
        assert w.authorise("viewer")
    assert w.row()["relationship"] == "viewer"


def test_the_trust_put_s_edit_replaces_a_stale_override() -> None:
    """Re-run 5/6 (Issues 1, 8): the other edit path, ``PUT /trust/<rel>/<peer>``
    with ``permissions``: replaced, its unseen fields not carried."""
    import json as _json

    from actingweb.aw_web_request import AWWebObj
    from actingweb.handlers.trust import TrustPeerHandler

    w = World()
    peer, store = _stale_client(w)
    stale = store.get_permissions_uncached(aid(w.actor), peer)
    assert stale is not None
    stale.methods = {"allowed": ["*"]}
    assert store.store_permissions(stale, notify_peer=False)
    body = {
        "permissions": {"properties": {"patterns": ["a/*"], "operations": ["read"]}}
    }
    handler = TrustPeerHandler(AWWebObj(body=_json.dumps(body)), w.config)
    auth = mock.Mock(acl={"peerid": "", "relationship": "creator"})
    result = mock.Mock(success=True, actor=w.actor, auth_obj=auth)
    result.authorize.return_value = True
    with mock.patch.object(handler, "authenticate_actor", return_value=result):
        handler.put(aid(w.actor), "viewer", peer)
    stored = store.get_permissions_uncached(aid(w.actor), peer)
    assert stored is not None and stored.trust_type == "viewer"
    assert not stored.methods


def test_a_grant_that_is_not_an_object_is_400() -> None:
    """Re-run 7 (Issue 4): a list or scalar failed in the store, a 500."""
    w = World()
    assert w.authorise("viewer")
    peer = str(w.row()["peerid"])
    handler, result = _owner_handler(w, [1, 2])
    with mock.patch.object(handler, "authenticate_actor", return_value=result):
        handler.put(aid(w.actor), "viewer", peer)
    assert handler.response.status_code == 400


def test_the_store_owns_created_by() -> None:
    """Re-run 7 (Issue 4): the create path took ``created_by`` from the body,
    which an update refuses."""
    w = World()
    assert w.authorise("viewer")
    peer = str(w.row()["peerid"])
    handler, result = _owner_handler(
        w,
        {
            "created_by": "someone-else",
            "properties": {"patterns": ["a/*"], "operations": ["read"]},
        },
    )
    with mock.patch.object(handler, "authenticate_actor", return_value=result):
        handler.put(aid(w.actor), "viewer", peer)
    assert handler.response.status_code == 201
    stored = get_trust_permission_store(w.config).get_permissions_uncached(
        aid(w.actor), peer
    )
    assert stored is not None
    assert stored.created_by == "system"


def test_the_permissions_put_reads_the_store_not_the_cache() -> None:
    """Re-run 6/7 (Issues 4, 5): an override deleted elsewhere (another
    process) but still in this process's cache was merged into, bringing
    its fields back. The edit reads the store: it creates (201)."""
    w = World()
    assert w.authorise("viewer")
    peer = str(w.row()["peerid"])
    store = get_trust_permission_store(w.config)
    assert store.store_permissions(
        TrustPermissions(
            actor_id=aid(w.actor),
            peer_id=peer,
            trust_type="viewer",
            methods={"allowed": ["*"]},
        ),
        notify_peer=False,
    )
    assert store.get_permissions(aid(w.actor), peer) is not None  # cached
    bucket = store._get_permissions_bucket(aid(w.actor))
    assert bucket is not None
    bucket.delete_attr(name=f"{aid(w.actor)}:{peer}")  # another process
    handler, result = _owner_handler(
        w, {"properties": {"patterns": ["a/*"], "operations": ["read"]}}
    )
    with mock.patch.object(handler, "authenticate_actor", return_value=result):
        handler.put(aid(w.actor), "viewer", peer)
    assert handler.response.status_code == 201
    stored = store.get_permissions_uncached(aid(w.actor), peer)
    assert stored is not None and not stored.methods


def test_a_failed_restore_is_not_reported_as_nothing_changed() -> None:
    """Re-run 7 (Issue 2): the trust write and the override's restore both
    failed; the caller got 400 and the new grant stood."""
    import json as _json

    from actingweb.aw_web_request import AWWebObj
    from actingweb.handlers.trust import TrustPeerHandler
    from actingweb.interface.trust_manager import TrustManager

    w = World()
    assert w.authorise("viewer")
    peer = str(w.row()["peerid"])
    body = {
        "permissions": {"properties": {"patterns": ["a/*"], "operations": ["read"]}}
    }
    handler = TrustPeerHandler(AWWebObj(body=_json.dumps(body)), w.config)
    auth = mock.Mock(acl={"peerid": "", "relationship": "creator"})
    result = mock.Mock(success=True, actor=w.actor, auth_obj=auth)
    result.authorize.return_value = True
    with (
        mock.patch.object(handler, "authenticate_actor", return_value=result),
        mock.patch.object(TrustManager, "modify_and_notify", return_value=False),
        mock.patch.object(
            TrustPermissionStore, "delete_permissions", return_value=False
        ),
    ):
        handler.put(aid(w.actor), "viewer", peer)
    assert handler.response.status_code == 500
