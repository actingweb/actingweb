"""A peer's non-finite scalar in a replica callback
(thoughts/plans/2026-11-25-attribute-compare-and-delete.md, AC-29).

``NaN`` and ``Infinity`` are not JSON, and every attribute write refuses them
with ``UnserialisableValue``. The replica skips that key with an error result
and applies the rest of the callback; the key is not marked out of step (a
rebuild would fetch the same value). Runs on the backend ``DATABASE_BACKEND``
selects (both in the Full tier).
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import MagicMock

import pytest

from actingweb.remote_storage import RemotePeerStore
from tests._adoption_helpers import make_config

PEER = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"


@pytest.mark.integration
def test_a_non_finite_scalar_is_skipped_and_the_rest_applied() -> None:
    actor = MagicMock()
    actor.id = "nonfinite" + uuid.uuid4().hex[:12]
    actor.config = make_config(database=os.environ.get("DATABASE_BACKEND", "dynamodb"))
    remote = RemotePeerStore(actor, PEER)
    try:
        result = remote.apply_callback_data({"a": {"v": float("inf")}, "b": {"v": 1}})
        assert "error" in result["a"]
        assert remote.get_value("a") is None
        assert remote.get_value("b") == {"v": 1}
        assert result.out_of_step is None
    finally:
        remote.delete_all()


@pytest.mark.integration
def test_a_non_finite_scalar_in_a_baseline_does_not_keep_a_rebuild_owed() -> None:
    """AC-30 (added in implementation): a baseline that carries a peer's
    non-finite value stores the rest and does not count the key as failed,
    so the rebuild settles instead of refetching the same refusal."""
    actor = MagicMock()
    actor.id = "nonfinite" + uuid.uuid4().hex[:12]
    actor.config = make_config(database=os.environ.get("DATABASE_BACKEND", "dynamodb"))
    remote = RemotePeerStore(actor, PEER)
    try:
        result = remote.apply_resync_data({"a": {"v": float("nan")}, "b": {"v": 1}})
        assert result["a"]["error"] == "refused"
        assert result.failed == []
        assert remote.get_value("a") is None
        assert remote.get_value("b") == {"v": 1}
    finally:
        remote.delete_all()


def test_a_rewrite_that_cannot_be_stored_deletes_the_name() -> None:
    """AC-31 (added in implementation): a revocation rewrites a scalar
    without its revoked parts. A DynamoDB row stored before the refusal can
    hold ``NaN``, which no write takes now; the name is then deleted whole
    (fail closed), and the rest of the revocation goes on."""
    from actingweb.db.exceptions import UnserialisableValue
    from actingweb.replica_revocation import RevokedNames, apply_revoked

    store = MagicMock()
    store._peer_id = PEER
    store.set_value.side_effect = [
        UnserialisableValue("attribute data", ValueError("nan")),
        None,
    ]
    revoked = RevokedNames(
        scalars=["gone"],
        lists=[],
        rewrites={"legacy": {"v": float("nan")}, "fine": {"v": 1}},
    )
    apply_revoked(store, revoked)
    deleted = [c.args[0] for c in store.delete_value.call_args_list]
    assert "legacy" in deleted and "gone" in deleted
    assert [c.args[0] for c in store.set_value.call_args_list] == ["legacy", "fine"]


def _remote() -> RemotePeerStore:
    actor = MagicMock()
    actor.id = "nonfinite" + uuid.uuid4().hex[:12]
    actor.config = make_config(database=os.environ.get("DATABASE_BACKEND", "dynamodb"))
    return RemotePeerStore(actor, PEER)


@pytest.mark.integration
@pytest.mark.parametrize("path", ["callback", "baseline"])
def test_a_refused_value_does_not_leave_the_old_one(path: str) -> None:
    """AC-33 (added in iteration 2; owner, 2026-11-25): fail closed. The
    replica deletes a key whose new value it cannot store, so it never
    serves the peer's previous value as current."""
    remote = _remote()
    try:
        remote.set_value("a", {"v": 3})
        data = {"a": {"v": float("nan")}, "b": {"v": 1}}
        if path == "callback":
            result = remote.apply_callback_data(data)
        else:
            result = remote.apply_resync_data(data)
        assert result["a"]["error"] == "refused"
        assert remote.get_value("a") is None
        assert remote.get_value("b") == {"v": 1}
    finally:
        remote.delete_all()


@pytest.mark.integration
def test_a_list_replaced_by_a_refused_scalar_is_gone() -> None:
    """AC-34 (added in iteration 2): a baseline names a list's key as a
    scalar the replica cannot store; the name ends absent, neither list
    nor stale scalar."""
    remote = _remote()
    try:
        remote.set_list("a", ["x"])
        result = remote.apply_resync_data({"a": float("inf")})
        assert result["a"]["error"] == "refused"
        assert remote.get_value("a") is None
        assert not remote._list_exists("a")  # noqa: SLF001
    finally:
        remote.delete_all()


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("DATABASE_BACKEND", "dynamodb") != "dynamodb",
    reason="only DynamoDB could store NaN before the refusal",
)
def test_a_resource_write_into_a_legacy_nan_property_replaces_it() -> None:
    """AC-35 (added in iteration 2; changed in iterations 8 and 11): a
    property stored before the refusal holds NaN in one path, so no write
    of it can succeed. A resource write replaces it with the peer's value
    alone instead of being refused for good."""
    from actingweb.db.dynamodb.attribute import Attribute

    remote = _remote()
    bucket = remote._bucket  # noqa: SLF001
    Attribute(
        id=remote._actor.id,  # noqa: SLF001
        bucket_name=f"{bucket}:prop",
        bucket=bucket,
        name="prop",
        data={"old": float("nan"), "x": 1, "deep": {"n": float("inf"), "k": 2}},
    ).save()
    try:
        result = remote.apply_callback_data({"v": 2}, subtarget="prop", resource="y")
        assert "error" not in result["prop"]
        assert remote.get_value("prop") == {"y": {"v": 2}}
        # A refused write into such a property deletes it (fail closed).
        Attribute(
            id=remote._actor.id,  # noqa: SLF001
            bucket_name=f"{bucket}:prop",
            bucket=bucket,
            name="prop",
            data={"old": float("nan"), "x": 1},
        ).save()
        result = remote.apply_callback_data(
            {"v": float("nan")}, subtarget="prop", resource="x"
        )
        assert result["prop"]["error"] == "refused"
        assert remote.get_value("prop") is None
    finally:
        remote.delete_all()


@pytest.mark.integration
def test_a_refused_resource_value_drops_only_its_path() -> None:
    """AC-39 (added in iteration 8): a peer's non-finite value at a
    resource path removes that path (its previous value is stale) and keeps
    the property's other paths, which other subscriptions may have
    written."""
    remote = _remote()
    try:
        remote.set_value("prop", {"x": 1, "y": {"v": 0}})
        result = remote.apply_callback_data(
            {"v": float("nan")}, subtarget="prop", resource="y"
        )
        assert result["prop"]["error"] == "refused"
        assert remote.get_value("prop") == {"x": 1}
    finally:
        remote.delete_all()


@pytest.mark.integration
def test_a_refused_resource_value_creates_and_replaces_nothing() -> None:
    """AC-41 (added in iteration 11): a refused value at a path whose
    parents are missing, or whose parent is not an object, leaves the
    property as it was."""
    remote = _remote()
    try:
        remote.set_value("prop", {"a": 5})
        for resource in ("a/b/c", "x/y"):
            result = remote.apply_callback_data(
                {"v": float("nan")}, subtarget="prop", resource=resource
            )
            assert result["prop"]["error"] == "refused"
        assert remote.get_value("prop") == {"a": 5}
    finally:
        remote.delete_all()
