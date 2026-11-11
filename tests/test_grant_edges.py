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


def test_a_bulk_items_update_a_hook_refuses_still_reaches_subscribers() -> None:
    """Outside voice 2026-11-10: the batch is applied before the hook runs
    and is not rolled back; with no key in ``pair`` the stop registered no
    diff and subscribers kept stale list contents."""
    from actingweb.aw_web_request import AWWebObj
    from actingweb.handlers.properties import PropertiesHandler

    handler = PropertiesHandler(AWWebObj(), mock.Mock())
    handler.hooks = mock.Mock()
    pair: dict[str, Any] = {}
    with (
        mock.patch.object(handler, "_get_actor_interface", return_value=mock.Mock()),
        mock.patch.object(handler, "_run_hooks", return_value=None),
    ):
        ok = handler._finish_bulk_list_update(
            mock.Mock(), "notes", mock.Mock(), mock.Mock(), pair, 2, 1
        )
    assert ok is False
    assert handler.response.status_code == 403
    assert "notes" in pair


def test_a_bulk_items_update_a_hook_denies_is_403_with_its_diff() -> None:
    """Verification re-run 1 (Issue E): a hook answering PERMISSION_DENIED
    (``_run_hooks`` raises ``_HookDenied``) escaped to the bulk path's
    generic handler: 500, and no key for the diff."""
    from actingweb.access_decision import PERMISSION_DENIED
    from actingweb.aw_web_request import AWWebObj
    from actingweb.handlers.properties import PropertiesHandler

    handler = PropertiesHandler(AWWebObj(), mock.Mock())
    handler.hooks = mock.Mock()
    handler.hooks.execute_property_hooks.return_value = PERMISSION_DENIED
    pair: dict[str, Any] = {}
    with mock.patch.object(handler, "_get_actor_interface", return_value=mock.Mock()):
        ok = handler._finish_bulk_list_update(
            mock.Mock(), "notes", mock.Mock(), mock.Mock(), pair, 2, 1
        )
    assert ok is False
    assert handler.response.status_code == 403
    assert "notes" in pair


@pytest.mark.parametrize("shape", ["json", "form"])
def test_a_hook_refusing_a_later_key_registers_what_was_applied(shape: str) -> None:
    """Re-run 2 of the grant-enforcement verification (Issue 9): a hook's
    PERMISSION_DENIED for a later key (``_HookDenied``) answered 403 through
    the decorator, but the keys written before it got no diff. Through
    ``post()``, both body shapes."""
    from actingweb.access_decision import PERMISSION_DENIED

    if shape == "json":
        handler, myself, result = _bulk_handler(None, {"a": 1, "b": 2}, "")
        expected = {"a": 1}
    else:
        handler, myself, result = _bulk_handler({"a": "1", "b": "2"}, None, "")
        expected = {"a": "1"}
    handler.hooks = mock.Mock()
    handler.hooks.execute_property_hooks.side_effect = lambda name, *a, **k: (
        PERMISSION_DENIED if name == "b" else a[2]
    )
    with (
        mock.patch.object(handler, "authenticate_actor", return_value=result),
        mock.patch.object(handler, "_get_actor_interface", return_value=mock.Mock()),
    ):
        handler.post("a1", "")
    assert handler.response.status_code == 403
    assert myself.property.written == expected
    myself.register_diffs.assert_called_once_with(
        target="properties", blob=json.dumps(expected)
    )


def test_touches_excluded_beyond_the_parser() -> None:
    """Re-run 4 (Issue 7): with a value nested beyond the parser, a peer
    whose grant excludes something is refused; one whose grant excludes
    nothing passes this check (and reaches the PUT's own refusal of a
    sub-path merge, 409, or replaces the whole)."""
    from actingweb.aw_web_request import AWWebObj
    from actingweb.handlers.properties import PropertiesHandler
    from actingweb.permission_evaluator import TOO_DEEP

    deep = "[" * 200_000 + "]" * 200_000
    myself = mock.Mock()
    myself.property = {"deep": deep, "color": "blue"}
    for rules, refused in (
        ({"patterns": ["*"], "excluded_patterns": ["private/*"]}, True),
        ({"patterns": ["*"]}, False),
    ):
        handler = PropertiesHandler(AWWebObj(), mock.Mock())
        snapshot = mock.Mock(relationship="friend")
        snapshot.rules.return_value = rules
        handler._decision = mock.Mock(snapshot=snapshot)
        assert handler._touches_excluded(myself, ["deep", "x"], 1) is refused
        assert handler._touches_excluded(myself, ["color"], TOO_DEEP) is refused


def _get_handler(stored: dict[str, Any], hook: Any = None) -> tuple[Any, Any]:
    from actingweb.aw_web_request import AWWebObj
    from actingweb.handlers.properties import PropertiesHandler

    myself = mock.Mock()
    myself.property = stored
    auth = mock.Mock()
    auth.acl = {"peerid": ""}
    result = mock.Mock(success=True, actor=myself, auth_obj=auth)
    handler = PropertiesHandler(AWWebObj(params={}), mock.Mock())
    handler.hooks = None
    if hook is not None:
        handler.hooks = mock.Mock()
        handler.hooks.execute_property_hooks.side_effect = hook
    return handler, result


def _run_get(handler: Any, result: Any, name: str) -> None:
    with (
        mock.patch.object(handler, "authenticate_actor", return_value=result),
        mock.patch.object(handler, "_check_property_permission", return_value=True),
        mock.patch.object(handler, "_list_tail_allowed", return_value=True),
        mock.patch.object(handler, "_get_actor_interface", return_value=mock.Mock()),
    ):
        handler.get("a1", name)


def test_plain_text_has_no_parts_and_the_read_hook_decides_it() -> None:
    """Re-run 5 (Issue 5): a direct read of plain text answered the whole
    text for any sub-path and skipped the read hook, which the listing runs:
    a hook withholding the property hid it from the listing only."""
    handler, result = _get_handler({"email": "a@example.test"})
    _run_get(handler, result, "email/x")
    assert handler.response.status_code == 404
    handler, result = _get_handler(
        {"email": "a@example.test"}, hook=lambda name, *a, **k: None
    )
    _run_get(handler, result, "email")
    assert handler.response.status_code == 404
    handler, result = _get_handler(
        {"email": "a@example.test"}, hook=lambda name, *a, **k: "redacted"
    )
    _run_get(handler, result, "email")
    assert handler.response.status_code == 200
    assert handler.response.body == "redacted"


def test_a_list_item_body_beyond_the_parser_is_400() -> None:
    """Re-run 5 (Issue 3): ``PUT ?index=`` stored such a body as text, and
    list items are not walked by the grant filter."""
    from actingweb.aw_web_request import AWWebObj
    from actingweb.handlers.properties import PropertiesHandler

    deep = "[" * 200_000 + "]" * 200_000
    myself = mock.Mock()
    myself.property = {}
    myself.property_lists.exists.return_value = True
    auth = mock.Mock()
    auth.acl = {"peerid": ""}
    result = mock.Mock(success=True, actor=myself, auth_obj=auth)
    result.authorize.return_value = True
    handler = PropertiesHandler(AWWebObj(body=deep, params={"index": "0"}), mock.Mock())
    handler.hooks = None
    with (
        mock.patch.object(handler, "authenticate_actor", return_value=result),
        mock.patch.object(handler, "_check_property_permission", return_value=True),
        mock.patch.object(handler, "_list_tail_allowed", return_value=True),
    ):
        handler.put("a1", "notes")
    assert handler.response.status_code == 400


def test_a_read_hook_s_result_on_plain_text_is_filtered() -> None:
    """Re-run 6 (Issue 2): the plain-text branch ran the read hook without
    the filter that follows it on the JSON branch and in the listing: a hook
    expanding text to an object sent a peer the keys its grant excludes."""
    handler, result = _get_handler(
        {"profile": "ref:1"},
        hook=lambda name, *a, **k: {"name": "n", "ssn": "secret"},
    )
    snapshot = mock.Mock(relationship="friend")
    snapshot.rules.return_value = {
        "patterns": ["*"],
        "excluded_patterns": ["profile/ssn"],
    }
    decision = mock.Mock(snapshot=snapshot)

    def decide(*a: Any, **k: Any) -> bool:
        handler._decision = decision
        return True

    result.auth_obj.acl = {"peerid": "p1"}
    with (
        mock.patch.object(handler, "authenticate_actor", return_value=result),
        mock.patch.object(handler, "_check_property_permission", side_effect=decide),
        mock.patch.object(handler, "_list_tail_allowed", return_value=True),
        mock.patch.object(handler, "_get_actor_interface", return_value=mock.Mock()),
    ):
        handler.get("a1", "profile")
    assert handler.response.status_code == 200
    assert json.loads(handler.response.body) == {"name": "n"}
