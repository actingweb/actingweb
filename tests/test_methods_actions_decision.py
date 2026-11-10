"""Methods and actions follow the one access decision (3.16, plan Phase 2).

A stated rule (even the consumer's empty ``"methods": []``) answers and
denies what it does not cover; a grant that does not mention the category
leaves it to the access table with the request's method; an evaluator that
cannot be built denies the call and empties the listing; the JSON-RPC entry
on the bare ``/methods`` checks the method the body names, on both twins.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest import mock

import pytest

from actingweb.access_decision import listable_names, named_route_allows
from actingweb.permission_evaluator import (
    GrantSnapshot,
    PermissionEvaluator,
    PermissionType,
)


class _Config:
    def __init__(self, access: list[tuple[str, str, str, str]]):
        self.access = access


def _auth(peer: str = "p1") -> Any:
    auth = mock.Mock()
    auth.acl = {"peerid": peer}
    auth.check_authorisation.return_value = True
    return auth


def _evaluator(permissions: dict[str, Any] | None, relationship: str = "subscriber"):
    ev = object.__new__(PermissionEvaluator)
    ev.config = None  # type: ignore[assignment]
    ev.snapshot = lambda a, p: GrantSnapshot(  # type: ignore[method-assign]
        actor_id=a,
        peer_id=p,
        has_row=True,
        approved=True,
        relationship=relationship,
        is_client=False,
        permissions=permissions,
    )
    return ev


def _config(access: list[tuple[str, str, str, str]]) -> Any:
    return _Config(access)


EMM_ROWS = [("subscriber", "methods", "POST", "a")]


@pytest.mark.parametrize("category", [PermissionType.METHODS, PermissionType.ACTIONS])
def test_an_empty_stated_rule_denies_whatever_the_table_says(category) -> None:
    """The consumer's subscriber: ``"methods": []`` beside a POST row."""
    ev = _evaluator({category.value: []})
    assert not named_route_allows(
        _Config(EMM_ROWS + [("subscriber", "actions", "POST", "a")]),  # type: ignore[arg-type]
        "a1",
        _auth(),
        category,
        "wire_import",
        method="POST",
        get_evaluator=lambda c: ev,
    )


@pytest.mark.parametrize(("method", "allowed"), [("POST", True), ("GET", False)])
def test_not_mentioned_follows_the_table_with_the_request_method(method, allowed):
    ev = _evaluator({"properties": {}})
    assert (
        named_route_allows(
            _Config(EMM_ROWS),  # type: ignore[arg-type]
            "a1",
            _auth(),
            PermissionType.METHODS,
            "m",
            method=method,
            get_evaluator=lambda c: ev,
        )
        is allowed
    )


def test_an_evaluator_that_cannot_be_built_denies_and_empties_the_listing() -> None:
    def broken(_config):
        raise RuntimeError("no evaluator")

    config = _Config(EMM_ROWS)
    assert not named_route_allows(
        config,  # type: ignore[arg-type]
        "a1",
        _auth(),
        PermissionType.METHODS,
        "m",
        method="POST",
        get_evaluator=broken,
    )
    assert (
        listable_names(
            config,  # type: ignore[arg-type]
            "a1",
            _auth(),
            PermissionType.METHODS,
            ["m"],
            get_evaluator=broken,
        )
        == set()
    )


def test_the_listing_shows_what_a_call_would_be_allowed() -> None:
    ev = _evaluator({"methods": {"allowed": ["get_*"], "denied": ["get_secret"]}})
    assert listable_names(
        _Config([]),  # type: ignore[arg-type]
        "a1",
        _auth(),
        PermissionType.METHODS,
        ["get_a", "get_secret", "wipe"],
        get_evaluator=lambda c: ev,
    ) == {"get_a"}


def test_a_caller_that_is_not_a_peer_keeps_the_table() -> None:
    auth = _auth(peer="")
    assert named_route_allows(
        _Config([]),  # type: ignore[arg-type]
        "a1",
        auth,
        PermissionType.METHODS,
        "m",
        method="POST",
        get_evaluator=lambda c: None,
    )
    auth.check_authorisation.assert_called_once_with(
        path="methods", subpath="m", method="GET"
    )
    assert (
        listable_names(
            _Config([]),  # type: ignore[arg-type]
            "a1",
            auth,
            PermissionType.METHODS,
            ["m"],
            get_evaluator=lambda c: None,
        )
        is None
    )


REQUEST = {"jsonrpc": "2.0", "method": "wipe", "params": {}, "id": 7}


def _handler(cls: Any) -> Any:
    from actingweb.aw_web_request import AWWebObj

    handler = cls(AWWebObj(), mock.Mock())
    handler.hooks = mock.Mock()
    return handler


def test_the_jsonrpc_method_is_checked_before_dispatch_sync() -> None:
    from actingweb.handlers.methods import MethodsHandler

    handler = _handler(MethodsHandler)
    with mock.patch.object(
        handler, "_check_method_permission", return_value=False
    ) as c:
        out = handler._handle_jsonrpc_request(
            dict(REQUEST), "", mock.Mock(id="a1"), _auth()
        )
    assert out is not None and out["error"]["message"] == "Forbidden"
    c.assert_called_once()
    assert c.call_args.args[2] == "wipe"
    handler.hooks.execute_method_hooks.assert_not_called()


def test_the_jsonrpc_method_is_checked_before_dispatch_async() -> None:
    from actingweb.handlers.async_methods import AsyncMethodsHandler

    handler = _handler(AsyncMethodsHandler)
    with mock.patch.object(handler, "_check_method_permission", return_value=False):
        out = asyncio.run(
            handler._handle_jsonrpc_request_async(
                dict(REQUEST), "", mock.Mock(id="a1"), _auth()
            )
        )
    assert out is not None and out["error"]["message"] == "Forbidden"
    handler.hooks.execute_method_hooks_async.assert_not_called()


@pytest.mark.parametrize("async_twin", [False, True])
def test_delete_asks_the_grant(async_twin: bool) -> None:
    from actingweb.handlers.async_methods import AsyncMethodsHandler
    from actingweb.handlers.methods import MethodsHandler

    handler = _handler(AsyncMethodsHandler if async_twin else MethodsHandler)
    result = mock.Mock(success=True, actor=mock.Mock(), auth_obj=_auth())
    result.authorize.return_value = True
    with (
        mock.patch.object(handler, "authenticate_actor", return_value=result),
        mock.patch.object(handler, "_check_method_permission", return_value=False) as c,
    ):
        if async_twin:
            asyncio.run(handler.delete_async("a1", "wipe"))
        else:
            handler.delete("a1", "wipe")
    assert c.call_args.args[3] == "DELETE"
    assert handler.response.status_code == 403
    handler.hooks.execute_method_hooks.assert_not_called()


def test_an_application_target_needs_the_subscription_row() -> None:
    """A developer view asks for an application's own target too: the access
    row that admits creating a subscription decides; a client has none."""
    from actingweb.access_decision import subscription_allowed

    ev = _evaluator({"properties": {}})
    row = [("subscriber", "subscriptions/<id>", "POST", "a")]
    assert subscription_allowed(
        _config(row), "a1", "p1", "app_target", evaluator=ev
    ).allowed  # type: ignore[arg-type]
    assert not subscription_allowed(
        _config([]), "a1", "p1", "app_target", evaluator=ev
    ).allowed  # type: ignore[arg-type]
    assert not subscription_allowed(
        _config(row),
        "a1",
        "p1",
        "app_target",
        evaluator=ev,
        is_client=True,  # type: ignore[arg-type]
    ).allowed


def test_the_resources_route_denies_when_no_evaluator_can_be_built() -> None:
    from actingweb.aw_web_request import AWWebObj
    from actingweb.handlers import resources

    handler = resources.ResourcesHandler(AWWebObj(), mock.Mock())
    result = mock.Mock(auth_obj=_auth())
    with (
        mock.patch.object(
            resources, "get_permission_evaluator", side_effect=RuntimeError
        ),
        mock.patch(
            "actingweb.access_decision.get_permission_evaluator",
            side_effect=RuntimeError,
        ),
    ):
        assert not handler._grant_allows("a1", result, "x", "GET")
    assert handler.response.status_code == 403


def test_put_on_methods_is_decided_as_put_and_hooks_get_the_verb() -> None:
    from actingweb.handlers.methods import MethodsHandler

    handler = _handler(MethodsHandler)
    seen: list[str] = []

    def post(actor_id, name):
        handler._check_method_permission(actor_id, _auth(), name, "POST")
        seen.append(handler._create_auth_context(_auth())["method"])

    with (
        mock.patch.object(handler, "post", side_effect=post),
        mock.patch(
            "actingweb.handlers.methods.named_route_allows", return_value=True
        ) as allows,
    ):
        handler.put("a1", "m")
    assert allows.call_args.kwargs["method"] == "PUT"
    assert seen == ["PUT"]


def test_a_method_hook_is_decided_with_the_request_verb() -> None:
    from actingweb.interface.hooks import HookRegistry

    registry = HookRegistry()
    with mock.patch("actingweb.interface.hooks.decide") as decide_:
        decide_.return_value.allowed = True
        registry._check_hook_permission(
            "method",
            "m",
            mock.Mock(id="a1"),
            {"peer_id": "p1", "config": mock.Mock(), "method": "GET"},
        )
    assert decide_.call_args.kwargs["method"] == "GET"


# ---------------------------------------------------------------------------
# A request that names nothing (verification 2026-11-10, Issue 4)
# ---------------------------------------------------------------------------

EVERY_ROW = [
    ("subscriber", "methods", "GET,POST,PUT,DELETE", "a"),
    ("subscriber", "actions", "GET,POST,PUT,DELETE", "a"),
    ("subscriber", "resources", "GET,POST,PUT,DELETE", "a"),
]
NAMED = {"patterns": ["wire_*"], "operations": ["call", "execute", "read"]}


def _nameless(category: PermissionType, method: str, rules: Any) -> bool:
    ev = _evaluator({category.value: rules})
    return named_route_allows(
        _Config(EVERY_ROW),  # type: ignore[arg-type]
        "a1",
        _auth(),
        category,
        "",
        method=method,
        get_evaluator=lambda c: ev,
    )


@pytest.mark.parametrize(
    "category",
    [PermissionType.METHODS, PermissionType.ACTIONS, PermissionType.RESOURCES],
)
@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
def test_a_call_that_names_nothing_is_refused_whatever_the_table_says(
    category, method
) -> None:
    """Consumer shape: a stated rule beside a table row that admits every
    verb; before, the empty name went to the table and a ``*`` hook ran."""
    assert not _nameless(category, method, NAMED)
    assert not _nameless(category, method, [])


@pytest.mark.parametrize("category", [PermissionType.METHODS, PermissionType.ACTIONS])
def test_the_listing_is_admitted_when_the_rule_names_something(category) -> None:
    assert _nameless(category, "GET", NAMED)
    assert not _nameless(category, "GET", [])
    assert not _nameless(category, "GET", {"patterns": [], "operations": ["call"]})


def test_a_bare_resources_get_is_refused_under_a_stated_rule() -> None:
    """Spec: the path must name the resource; there is no listing to filter."""
    assert not _nameless(PermissionType.RESOURCES, "GET", NAMED)


@pytest.mark.parametrize(
    "category",
    [PermissionType.METHODS, PermissionType.ACTIONS, PermissionType.RESOURCES],
)
def test_a_grant_that_does_not_mention_the_category_keeps_the_table(category) -> None:
    ev = _evaluator({"properties": {}})
    assert named_route_allows(
        _Config(EVERY_ROW),  # type: ignore[arg-type]
        "a1",
        _auth(),
        category,
        "",
        method="POST",
        get_evaluator=lambda c: ev,
    )


def test_an_unbuildable_evaluator_is_named_once(caplog) -> None:
    """Verification 2026-11-10 (plan: one ERROR per process)."""
    import logging

    from actingweb import access_decision

    access_decision._evaluator_failure_logged = False

    def boom(config: Any) -> Any:
        raise RuntimeError("no registry")

    with caplog.at_level(logging.DEBUG, logger="actingweb.access_decision"):
        for _ in range(3):
            assert not named_route_allows(
                _Config(EMM_ROWS),  # type: ignore[arg-type]
                "a1",
                _auth(),
                PermissionType.METHODS,
                "x",
                method="POST",
                get_evaluator=boom,
            )
            assert access_decision.evaluator_or_none(_Config([]), boom) is None  # type: ignore[arg-type]
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1


# ---------------------------------------------------------------------------
# Tests the verification of 2026-11-10 found missing (Phase 2)
# ---------------------------------------------------------------------------

RES_ROWS = [("subscriber", "resources", "GET,POST,PUT,DELETE", "a")]


def _resource(permissions: dict[str, Any], name: str, method: str) -> bool:
    ev = _evaluator(permissions)
    return named_route_allows(
        _Config(RES_ROWS),  # type: ignore[arg-type]
        "a1",
        _auth(),
        PermissionType.RESOURCES,
        name,
        method=method,
        get_evaluator=lambda c: ev,
    )


def test_resources_not_mentioned_follow_the_table() -> None:
    assert _resource({"properties": {}}, "x", "GET")
    assert _resource({"properties": {}}, "x", "DELETE")


def test_an_empty_resources_rule_denies_whatever_the_table_says() -> None:
    assert not _resource({"resources": []}, "x", "GET")
    assert not _resource(
        {"resources": {"patterns": [], "operations": ["read"]}}, "x", "GET"
    )


def _subscribe(permissions: dict[str, Any], target: str, subtarget: str = "") -> bool:
    from actingweb.access_decision import subscription_allowed

    return subscription_allowed(
        _Config(RES_ROWS + [("subscriber", "properties", "GET", "a")]),  # type: ignore[arg-type]
        "a1",
        "p1",
        target,
        subtarget,
        evaluator=_evaluator(permissions),
    ).allowed


def test_a_whole_target_subscription_needs_something_readable() -> None:
    nothing = {"properties": {"patterns": [], "operations": ["read"]}}
    write_only = {"properties": {"patterns": ["*"], "operations": ["write"]}}
    something = {"properties": {"patterns": ["color"], "operations": ["read"]}}
    assert not _subscribe(nothing, "properties")
    assert not _subscribe(write_only, "properties")
    assert _subscribe(something, "properties")


def test_a_resources_subscription_to_an_excluded_path_is_refused() -> None:
    grant = {
        "resources": {
            "patterns": ["*"],
            "operations": ["read"],
            "excluded_patterns": ["private/*"],
        }
    }
    assert not _subscribe(grant, "resources", "private/x")
    assert _subscribe(grant, "resources", "public/x")


def test_an_actions_delete_asks_the_grant() -> None:
    """Verification 2026-11-10: only the methods DELETE was tested."""
    from actingweb.handlers.actions import ActionsHandler

    handler = _handler(ActionsHandler)
    result = mock.Mock(success=True, actor=mock.Mock(), auth_obj=_auth())
    with (
        mock.patch.object(handler, "authenticate_actor", return_value=result),
        mock.patch.object(handler, "_check_action_permission", return_value=False) as c,
    ):
        handler.delete("a1", "record")
    assert c.call_args.args[3] == "DELETE"
    assert handler.response.status_code == 403
    handler.hooks.execute_action_hooks.assert_not_called()


@pytest.mark.parametrize("async_twin", [False, True])
def test_bare_jsonrpc_is_decided_by_the_method_it_names(async_twin: bool) -> None:
    """Code review 2026-11-10: with nameless calls refused, a JSON-RPC POST to
    the bare /methods was refused at the URL check before the body's method
    was decided. The body's method decides; a bare non-JSON-RPC call is
    still refused."""
    import json as _json

    from actingweb.aw_web_request import AWWebObj
    from actingweb.handlers.async_methods import AsyncMethodsHandler
    from actingweb.handlers.methods import MethodsHandler

    def run(body: dict[str, Any]) -> Any:
        cls: Any = AsyncMethodsHandler if async_twin else MethodsHandler
        handler: Any = cls(AWWebObj(body=_json.dumps(body)), mock.Mock())
        handler.hooks = mock.Mock()
        handler.hooks.execute_method_hooks.return_value = {"ok": True}
        handler.hooks.execute_method_hooks_async = mock.AsyncMock(
            return_value={"ok": True}
        )
        auth = _auth()
        auth.response = {"code": 200}
        result = mock.Mock(success=True, actor=mock.Mock(), auth_obj=auth)
        with (
            mock.patch.object(
                handler, "_authenticate_dual_context", return_value=result
            ),
            mock.patch.object(
                handler,
                "_check_method_permission",
                side_effect=lambda a, c, name, m: name == "wire_ping",
            ),
            mock.patch.object(
                handler, "_get_actor_interface", return_value=mock.Mock()
            ),
        ):
            if async_twin:
                asyncio.run(handler.post_async("a1", ""))
            else:
                handler.post("a1", "")
        return handler

    granted = run({"jsonrpc": "2.0", "method": "wire_ping", "id": 1})
    assert granted.response.status_code == 200
    refused = run({"jsonrpc": "2.0", "method": "secret", "id": 1})
    assert '"Forbidden"' in refused.response.body or "Forbidden" in str(
        refused.response.body
    )
    # Verification re-run 1 (Issue I): refused with HTTP 403, as the named
    # path is (it answered 200 with the JSON-RPC error).
    assert refused.response.status_code == 403
    plain = run({"x": 1})
    assert plain.response.status_code == 403
