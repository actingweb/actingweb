"""Edges of the grant enforcement (3.16, plan Phase 1).

A diff never carries an object the filter emptied (the subscriber replaces a
property with what a diff carries, so ``{}`` would wipe the parts it may
read); a developer view refuses a write that would touch an excluded part,
as REST does; the filter reads no grant when given one; a bulk POST that
faults after applying some keys registers their diffs before the 503.
"""

from __future__ import annotations

import json
from typing import Any
from unittest import mock

import pytest

from actingweb.db.exceptions import DbError
from actingweb.permission_evaluator import GrantSnapshot, PermissionEvaluator

RULES = {
    "patterns": ["*"],
    "operations": ["read", "write", "delete"],
    "excluded_patterns": ["settings/private", "*/deep/private"],
}


def _grant(relationship: str = "friend") -> GrantSnapshot:
    return GrantSnapshot(
        actor_id="a1",
        peer_id="p1",
        has_row=True,
        approved=True,
        relationship=relationship,
        is_client=False,
        permissions={"properties": RULES},
    )


def _evaluator() -> PermissionEvaluator:
    ev = object.__new__(PermissionEvaluator)
    ev.config = None  # type: ignore[assignment]
    ev.snapshot = lambda a, p: _grant()  # type: ignore[method-assign]
    return ev


@pytest.fixture
def actor() -> Any:
    from actingweb.actor import Actor

    a = object.__new__(Actor)
    a.config = mock.Mock()
    a.id = "a1"
    with mock.patch(
        "actingweb.actor.get_permission_evaluator", return_value=_evaluator()
    ):
        yield a


WHOLE = {"target": "properties", "subtarget": ""}
UNDER = {"target": "properties", "subtarget": "settings"}


@pytest.mark.parametrize(
    ("sub", "diff", "sent"),
    [
        (WHOLE, {"settings": {"private": "s2"}}, None),
        (WHOLE, {"settings": {"deep": {"private": "d2"}}}, None),
        (
            WHOLE,
            {"settings": {"theme": "y", "private": "s"}},
            {"settings": {"theme": "y"}},
        ),
        (
            WHOLE,
            {"settings": {"deep": {"private": "d", "ok": 1}}},
            {"settings": {"deep": {"ok": 1}}},
        ),
        (WHOLE, {"settings": {}}, {"settings": {}}),  # an owner's own empty write
        (WHOLE, {"settings": {"private": "s2"}, "color": "red"}, {"color": "red"}),
        (UNDER, {"private": "s2"}, None),
        (UNDER, {"deep": {"private": "d2"}}, None),
        (UNDER, {"deep": {"private": "d2", "ok": 2}}, {"deep": {"ok": 2}}),
    ],
)
def test_a_diff_never_carries_an_emptied_object(actor, sub, diff, sent) -> None:
    out = actor.filter_subscription_blob("p1", sub, json.dumps(diff))
    assert (json.loads(out) if out is not None else None) == sent


def test_the_filter_reads_no_grant_when_given_one(actor) -> None:
    with mock.patch.object(type(actor), "grant_for") as read:
        for _ in range(3):
            actor.filter_subscription_blob(
                "p1", WHOLE, json.dumps({"color": "x"}), snapshot=_grant()
            )
    read.assert_not_called()


class _Store(dict):
    pass


def _view(relationship: str = "friend") -> Any:
    from actingweb.interface.authenticated_views import (
        AuthContext,
        AuthenticatedPropertyStore,
    )

    store = _Store(settings={"theme": "x", "private": "s"}, color="blue")
    ev = _evaluator()
    ev.snapshot = lambda a, p: _grant(relationship)  # type: ignore[method-assign]
    patcher = mock.patch(
        "actingweb.interface.authenticated_views.get_permission_evaluator",
        return_value=ev,
    )
    patcher.start()
    view = AuthenticatedPropertyStore(
        store,  # type: ignore[arg-type]  # a dict stands in for the store
        AuthContext(peer_id="p1"),
        "a1",
        mock.Mock(),
    )
    return view, store, patcher


def test_a_view_write_touching_an_excluded_part_is_refused() -> None:
    from actingweb.interface.authenticated_views import PermissionError

    view, store, patcher = _view()
    try:
        assert view["settings"] == {"theme": "x"}
        with pytest.raises(PermissionError):
            view["settings"] = {"theme": "y"}
        with pytest.raises(PermissionError):
            del view["settings"]
        assert view.delete("settings") is False
        assert store["settings"] == {"theme": "x", "private": "s"}
        view["color"] = "red"
        assert store["color"] == "red"
    finally:
        patcher.stop()


def test_an_admin_view_may_write_the_parent() -> None:
    view, store, patcher = _view("admin")
    try:
        view["settings"] = {"theme": "y"}
        assert store["settings"] == {"theme": "y"}
    finally:
        patcher.stop()


def test_a_bulk_post_that_faults_registers_what_it_applied() -> None:
    from actingweb.aw_web_request import AWWebObj
    from actingweb.handlers.properties import PropertiesHandler

    class _Props:
        def __init__(self) -> None:
            self.written: dict[str, Any] = {}

        def __getitem__(self, name: str) -> Any:
            return None

        def __setitem__(self, name: str, value: Any) -> None:
            if name == "b":
                raise DbError("simulated")
            self.written[name] = value

    myself = mock.Mock()
    myself.property = _Props()
    auth = mock.Mock()
    auth.acl = {"peerid": ""}
    result = mock.Mock(success=True, actor=myself, auth_obj=auth)
    result.authorize.return_value = True
    handler = PropertiesHandler(
        AWWebObj(body=json.dumps({"a": 1, "b": 2}), params={}), mock.Mock()
    )
    handler.hooks = None
    with (
        mock.patch.object(handler, "authenticate_actor", return_value=result),
        pytest.raises(DbError),
    ):
        handler.post("a1", "")
    assert myself.property.written == {"a": 1}
    myself.register_diffs.assert_called_once_with(
        target="properties", blob=json.dumps({"a": 1})
    )


def _bulk_handler(params: dict[str, Any] | None, body: Any, fail_on: str) -> Any:
    from actingweb.aw_web_request import AWWebObj
    from actingweb.handlers.properties import PropertiesHandler

    class _Props:
        def __init__(self) -> None:
            self.written: dict[str, Any] = {}

        def __getitem__(self, name: str) -> Any:
            return None

        def __setitem__(self, name: str, value: Any) -> None:
            if name == fail_on:
                raise DbError("simulated")
            self.written[name] = value

    myself = mock.Mock()
    myself.property = _Props()
    auth = mock.Mock()
    auth.acl = {"peerid": ""}
    result = mock.Mock(success=True, actor=myself, auth_obj=auth)
    result.authorize.return_value = True
    handler = PropertiesHandler(
        AWWebObj(
            body=json.dumps(body) if body is not None else None, params=params or {}
        ),
        mock.Mock(),
    )
    handler.hooks = None
    return handler, myself, result


def test_a_form_post_that_faults_registers_what_it_applied() -> None:
    """Verification 2026-11-10: the form-arguments branch registered no
    diff for the keys it had written before a fault."""
    handler, myself, result = _bulk_handler({"a": "1", "b": "2"}, None, "b")
    with (
        mock.patch.object(handler, "authenticate_actor", return_value=result),
        pytest.raises(DbError),
    ):
        handler.post("a1", "")
    assert myself.property.written == {"a": "1"}
    myself.register_diffs.assert_called_once_with(
        target="properties", blob=json.dumps({"a": "1"})
    )


def test_a_post_stopped_part_way_registers_what_it_applied() -> None:
    """Verification 2026-11-10: a stop in the JSON apply (here a 400 for a
    value the pre-pass does not check) returned without the diffs of the
    keys written before it."""
    from actingweb.handlers import properties as props_module

    handler, myself, result = _bulk_handler(None, {"a": 1, "b": 2}, "")
    real = props_module.PropertiesHandler._apply_post_params

    def stop_after_a(self: Any, me: Any, check: Any, params: Any, pair: Any) -> None:
        real(self, me, check, {"a": params["a"]}, pair)
        self.response.set_status(400, "stop")

    with (
        mock.patch.object(handler, "authenticate_actor", return_value=result),
        mock.patch.object(
            props_module.PropertiesHandler, "_apply_post_params", stop_after_a
        ),
    ):
        handler.post("a1", "")
    assert handler.response.status_code == 400
    myself.register_diffs.assert_called_once_with(
        target="properties", blob=json.dumps({"a": 1})
    )
