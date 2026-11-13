"""The revocation cleanup (A8) of a peer's replica
(thoughts/plans/2026-11-13-attribute-list-v2-port.md, Phase 3), on the
in-memory attribute backend."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from actingweb.peer_permissions import PeerPermissions
from actingweb.remote_storage import RemotePeerStore
from actingweb.replica_revocation import (
    NotEvaluated,
    RevokedNames,
    apply_revoked,
    plan_cleanup,
    revoked_replica_names,
    still_readable,
)
from tests.mcp_token_double import make_config

ACTOR = "a" * 32
PEER = "b" * 32


def _grant(**properties: Any) -> PeerPermissions:
    return PeerPermissions(actor_id=ACTOR, peer_id=PEER, properties=properties or None)


@pytest.fixture
def remote() -> RemotePeerStore:
    actor = MagicMock()
    actor.id = ACTOR
    actor.config, _ = make_config()
    actor.config.auto_delete_on_revocation = True
    store = RemotePeerStore(actor, PEER)
    store.set_list("notes", ["n"])
    store.set_list("private_list", ["p"])
    store.set_value("color", {"v": 1})
    store.set_value("settings", {"theme": "x", "private": {"k": 1}})
    store.set_value("private", {"v": 2})
    return store


def _plan(store: RemotePeerStore, **properties: Any) -> RevokedNames:
    plan = revoked_replica_names(store, _grant(**properties))
    assert isinstance(plan, RevokedNames)
    return plan


class TestWhatIsRevoked:
    def test_a_pattern_removed(self, remote):
        plan = _plan(remote, patterns=["notes", "color"], operations=["read"])
        assert sorted(plan.lists) == ["private_list"]
        assert sorted(plan.scalars) == ["private", "settings"]

    def test_read_dropped(self, remote):
        plan = _plan(remote, patterns=["*"], operations=["write"])
        assert sorted(plan.names) == sorted(
            ["notes", "private_list", "color", "settings", "private"]
        )

    def test_an_exclusion_added_with_an_ancestor_and_a_descendant(self, remote):
        plan = _plan(
            remote,
            patterns=["*"],
            operations=["read"],
            excluded_patterns=["private/*", "settings/private"],
        )
        # private/* names the node private too; settings keeps theme.
        assert plan.scalars == ["private"]
        assert plan.rewrites == {"settings": {"theme": "x"}}
        assert plan.lists == []

    def test_scalars_and_lists_are_deleted_and_objects_rewritten(self, remote):
        plan = _plan(
            remote,
            patterns=["notes", "settings", "color"],
            operations=["read"],
            excluded_patterns=["settings/private"],
        )
        apply_revoked(remote, plan)
        assert remote.list_all_lists() == ["notes"]
        assert remote.get_value("private") is None
        assert remote.get_value("settings") == {"theme": "x"}
        assert remote.get_value("color") == {"v": 1}

    def test_still_readable_is_name_keyed(self):
        grant = _grant(patterns=["p/*"], operations=["read"], excluded_patterns=["p/x"])
        assert still_readable(grant, ["p/a", "p/x", "q"]) == ["p/a"]


class TestNotEvaluated:
    @pytest.mark.parametrize(
        "properties",
        [
            {},
            {"allowed": ["*"]},
            {"patterns": ["*"]},
            {"operations": ["read"]},
            {"patterns": "*", "operations": ["read"]},
        ],
    )
    def test_shapes_it_cannot_evaluate_delete_nothing(self, remote, properties):
        result = revoked_replica_names(remote, _grant(**properties))
        assert isinstance(result, NotEvaluated) and result.why


class TestEarlyExits:
    def _config(self, flag: bool) -> Any:
        config = MagicMock()
        config.auto_delete_on_revocation = flag
        return config

    def test_the_flag_off_reads_nothing(self, remote):
        with patch(
            "actingweb.replica_revocation.subscribes_to_whole_properties"
        ) as sub:
            assert (
                plan_cleanup(self._config(False), ACTOR, remote, None, _grant()) is None
            )
        sub.assert_not_called()

    def test_no_whole_target_subscription_reads_no_replica(self, remote):
        with (
            patch(
                "actingweb.replica_revocation.subscribes_to_whole_properties",
                return_value=False,
            ),
            patch.object(remote, "list_scalar_names") as names,
        ):
            assert (
                plan_cleanup(self._config(True), ACTOR, remote, None, _grant()) is None
            )
        names.assert_not_called()

    def test_an_unchanged_grant_reads_no_replica(self, remote):
        grant = _grant(patterns=["*"], operations=["read"])
        with (
            patch(
                "actingweb.replica_revocation.subscribes_to_whole_properties",
                return_value=True,
            ),
            patch.object(remote, "list_scalar_names") as names,
        ):
            assert plan_cleanup(self._config(True), ACTOR, remote, grant, grant) is None
        names.assert_not_called()

    def test_a_subtarget_subscription_only_is_not_covered(self):
        from actingweb.replica_revocation import subscribes_to_whole_properties

        listing = MagicMock()
        listing.fetch.return_value = [
            {"peerid": PEER, "callback": True, "target": "properties", "subtarget": "x"}
        ]
        with patch("actingweb.db.get_subscription_list", return_value=listing):
            assert subscribes_to_whole_properties(MagicMock(), ACTOR, PEER) is False
        listing.fetch.return_value = [
            {"peerid": PEER, "callback": True, "target": "properties"}
        ]
        with patch("actingweb.db.get_subscription_list", return_value=listing):
            assert subscribes_to_whole_properties(MagicMock(), ACTOR, PEER) is True


class TestOtherWriters:
    def test_a_writer_whose_grant_is_not_the_stored_one_deletes_nothing(self, remote):
        from actingweb.replica_revocation import cleanup_after_store

        newer = _grant(patterns=["*"], operations=["read"])
        older = _grant(patterns=["notes"], operations=["read"])
        store = MagicMock()
        store.read_stored_permissions.return_value = (None, newer)
        with patch(
            "actingweb.peer_permissions.get_peer_permission_store", return_value=store
        ):
            assert (
                cleanup_after_store(
                    remote._actor.config,  # noqa: SLF001
                    remote._actor,  # noqa: SLF001
                    PEER,
                    newer,
                    older,
                )
                == []
            )
        assert sorted(remote.list_all_lists()) == ["notes", "private_list"]


class TestWrappedScalars:
    def test_a_wrapped_value_the_grant_still_allows_is_kept(self, remote):
        remote.set_value("label", {"value": "x"})
        plan = _plan(
            remote,
            patterns=["*"],
            operations=["read"],
            excluded_patterns=["label/value"],
        )
        assert "label" not in plan.rewrites and "label" not in plan.scalars

    def test_has_revocations_stays_the_grant_comparison(self):
        from actingweb.handlers.callbacks import CallbacksHandler

        handler = CallbacksHandler.__new__(CallbacksHandler)
        changes: dict[str, Any] = {"has_revocations": True}
        myself = MagicMock()
        myself.config.auto_delete_on_revocation = True
        with patch(
            "actingweb.replica_revocation.plan_cleanup",
            return_value=RevokedNames(),
        ):
            handler._clean_replica(  # noqa: SLF001
                myself, MagicMock(), PEER, None, None, changes
            )
        assert changes["has_revocations"] is True
        assert changes["deleted_names"] == []


class TestRestoreByName:
    def test_names_are_escaped_into_exact_patterns(self):
        from actingweb.handlers.callbacks import _still_granted
        from actingweb.permission_evaluator import glob_match

        grant = _grant(patterns=["*"], operations=["read"])
        escaped = _still_granted(grant, ["a*b", "q?", "back\\slash", "plain"])
        assert escaped[-1] == "plain"
        for name, pattern in zip(
            ["a*b", "q?", "back\\slash", "plain"], escaped, strict=True
        ):
            assert glob_match(name, pattern)
        assert not glob_match("aXb", escaped[0])
