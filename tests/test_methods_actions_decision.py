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
