"""The one access decision for a peer (``actingweb.access_decision.decide``).

``thoughts/plans/2026-11-10-grant-enforcement-per-route.md``, Phase 1: a
grant that mentions a category answers with its rule (an unmatched or empty
rule denies); one that does not mention it leaves a peer to the access table
and denies a client; an unapproved row, an evaluator that cannot be built or
that raises deny; a storage fault raises.
"""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest

from actingweb import access_decision
from actingweb.access_decision import decide, forbidden_body
from actingweb.db.exceptions import DbError
from actingweb.permission_evaluator import (
    GrantSnapshot,
    PermissionEvaluator,
    PermissionType,
)


class _Config:
    """A config with an access table and nothing else."""

    def __init__(self, access: list[tuple[str, str, str, str]]):
        self.access = access


def _evaluator() -> PermissionEvaluator:
    ev = object.__new__(PermissionEvaluator)
    ev.config = None  # type: ignore[assignment]
    return ev


def _grant(
    permissions: dict[str, Any] | None,
    *,
    approved: bool = True,
    relationship: str = "friend",
    is_client: bool = False,
) -> GrantSnapshot:
    return GrantSnapshot(
        actor_id="a1",
        peer_id="p1",
        has_row=True,
        approved=approved,
        relationship=relationship,
        is_client=is_client,
        permissions=permissions,
    )


GET_ROW = [("friend", "properties", "GET", "a")]
POST_ROW = [("friend", "properties", "POST", "a")]


def _decide(
    grant: GrantSnapshot,
    path: str = "color",
    operation: str = "read",
    access: list[tuple[str, str, str, str]] | None = None,
    **kwargs: Any,
):
    return decide(
        _Config(GET_ROW if access is None else access),  # type: ignore[arg-type]
        "a1",
        "p1",
        PermissionType.PROPERTIES,
        path,
        operation,
        evaluator=_evaluator(),
        snapshot=grant,
        **kwargs,
    )


def test_mentioned_and_matching() -> None:
    d = _decide(_grant({"properties": {"patterns": ["*"], "operations": ["read"]}}))
    assert d.allowed and d.reason == "allowed"


@pytest.mark.parametrize(
    "rule",
    [
        {"patterns": ["notes"], "operations": ["read"]},
        {"allowed": ["notes"]},
        {},
    ],
)
def test_mentioned_and_unmatched_denies_whatever_the_table_says(rule) -> None:
    d = _decide(_grant({"properties": rule}), access=GET_ROW)
    assert not d.allowed and d.reason == "not_granted"


def test_an_excluded_path_says_so_in_its_reason_only() -> None:
    d = _decide(
        _grant(
            {
                "properties": {
                    "patterns": ["*"],
                    "operations": ["read"],
                    "excluded_patterns": ["color"],
                }
            }
        )
    )
    assert not d.allowed and d.reason == "excluded"
    assert forbidden_body(d) == {"error": "forbidden"}


@pytest.mark.parametrize(
    ("access", "operation", "allowed"),
    [(GET_ROW, "read", True), (POST_ROW, "read", False), ([], "read", False)],
)
def test_not_mentioned_follows_the_table(access, operation, allowed) -> None:
    d = _decide(
        _grant({"methods": {"allowed": ["*"]}}), access=access, operation=operation
    )
    assert d.allowed is allowed
    assert d.reason == ("allowed" if allowed else "no_table_row")


def test_an_unregistered_type_is_not_mentioned() -> None:
    assert _decide(_grant(None)).allowed


def test_the_request_method_reaches_the_table() -> None:
    d = _decide(_grant({}), access=POST_ROW, operation="write", method="POST")
    assert d.allowed


def test_a_client_never_reaches_the_table() -> None:
    assert not _decide(_grant({}, is_client=True)).allowed
    assert not _decide(_grant({}), is_client=True).allowed


def test_an_unapproved_row_is_not_approved() -> None:
    d = _decide(
        _grant(
            {"properties": {"patterns": ["*"], "operations": ["read"]}}, approved=False
        )
    )
    assert not d.allowed and d.reason == "not_approved"
    assert forbidden_body(d) == {"error": "not_approved"}


def test_a_control_character_denies() -> None:
    d = _decide(
        _grant({"properties": {"patterns": ["*"], "operations": ["read"]}}), path="a\nb"
    )
    assert not d.allowed


def test_an_evaluator_that_cannot_be_built_denies() -> None:
    with mock.patch.object(
        access_decision, "get_permission_evaluator", side_effect=RuntimeError("no")
    ):
        d = decide(_Config(GET_ROW), "a1", "p1", "properties", "color", "read")  # type: ignore[arg-type]
    assert not d.allowed and d.reason == "unavailable"


def test_an_evaluator_that_raises_denies() -> None:
    ev = _evaluator()
    with mock.patch.object(ev, "evaluate_rules_for", side_effect=ValueError("bug")):
        d = decide(
            _Config(GET_ROW),  # type: ignore[arg-type]
            "a1",
            "p1",
            "properties",
            "color",
            "read",
            evaluator=ev,
            snapshot=_grant(
                {"properties": {"patterns": ["*"], "operations": ["read"]}}
            ),
        )
    assert not d.allowed and d.reason == "unavailable"


def test_a_storage_fault_raises() -> None:
    ev = _evaluator()
    with (
        mock.patch.object(ev, "snapshot", side_effect=DbError("fault")),
        pytest.raises(DbError),
    ):
        decide(_Config(GET_ROW), "a1", "p1", "properties", "c", "read", evaluator=ev)  # type: ignore[arg-type]


def test_the_grant_is_read_once_per_request() -> None:
    """``snapshot()`` reads the trust row once; the override and registry
    lookups are cached stores (no second row read, as there was)."""
    config = mock.Mock()
    row = {"relationship": "friend", "approved": True}
    db_trust = mock.Mock()
    db_trust.get.return_value = row
    ev = object.__new__(PermissionEvaluator)
    ev.config = config
    ev.permission_store = mock.Mock(get_permissions=mock.Mock(return_value=None))
    ev.trust_type_registry = mock.Mock(
        get_type=mock.Mock(
            return_value=mock.Mock(
                base_permissions={
                    "properties": {"patterns": ["*"], "operations": ["read"]}
                }
            )
        )
    )
    with mock.patch("actingweb.permission_evaluator.get_trust", return_value=db_trust):
        grant = ev.snapshot("a1", "p1")
        for name in ("a", "b", "c"):
            assert decide(
                config,
                "a1",
                "p1",
                "properties",
                name,
                "read",
                evaluator=ev,
                snapshot=grant,
            ).allowed
    assert db_trust.get.call_count == 1
    assert grant.relationship == "friend" and grant.approved


def test_a_missing_row_is_not_approved() -> None:
    db_trust = mock.Mock()
    db_trust.get.return_value = None
    ev = object.__new__(PermissionEvaluator)
    ev.config = mock.Mock()
    ev.permission_store = mock.Mock()
    with mock.patch("actingweb.permission_evaluator.get_trust", return_value=db_trust):
        grant = ev.snapshot("a1", "p1")
    assert not grant.has_row and not grant.approved and grant.permissions is None


def test_a_client_row_is_recognised() -> None:
    db_trust = mock.Mock()
    db_trust.get.return_value = {
        "relationship": "mcp_client",
        "approved": True,
        "established_via": "oauth2_client",
    }
    ev = object.__new__(PermissionEvaluator)
    ev.config = mock.Mock()
    ev.permission_store = mock.Mock(get_permissions=mock.Mock(return_value=None))
    ev.trust_type_registry = mock.Mock(get_type=mock.Mock(return_value=None))
    with mock.patch("actingweb.permission_evaluator.get_trust", return_value=db_trust):
        grant = ev.snapshot("a1", "oauth2_client:x:y")
    assert grant.is_client
