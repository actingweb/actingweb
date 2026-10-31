"""Fourth verification, X1 and X2: a GET with a ``_method`` override changes
state, so every handler that honours one refuses it unless the request shows
it came from this app's own pages. A real PUT/POST/DELETE is unaffected, and
a request with no browser headers (a script, a peer) still works unless it
authenticates with the web UI's session cookie."""

from typing import Any
from unittest import mock

import pytest

from actingweb.aw_web_request import AWWebObj
from actingweb.config import Config
from actingweb.handlers import (
    actions,
    callbacks,
    methods,
    properties,
    root,
    subscription,
    trust,
)

ROOT = "https://demo.actingweb.io/"

# (handler class, method the override dispatches to, override, get() args)
SITES: list[tuple[Any, str, str, tuple[str, ...]]] = [
    (root.RootHandler, "delete", "DELETE", ("a1",)),
    (properties.PropertiesHandler, "delete", "DELETE", ("a1", "notes")),
    (properties.PropertiesHandler, "put", "PUT", ("a1", "notes")),
    (trust.TrustHandler, "post", "POST", ("a1",)),
    (trust.TrustRelationshipHandler, "post", "POST", ("a1", "friend")),
    (trust.TrustPeerHandler, "put", "PUT", ("a1", "friend", "p1")),
    (trust.TrustPeerHandler, "delete", "DELETE", ("a1", "friend", "p1")),
    (subscription.SubscriptionRootHandler, "post", "POST", ("a1",)),
    (subscription.SubscriptionRelationshipHandler, "post", "POST", ("a1", "p1")),
    (subscription.SubscriptionHandler, "delete", "DELETE", ("a1", "p1", "s1")),
    (actions.ActionsHandler, "post", "POST", ("a1", "go")),
    (methods.MethodsHandler, "post", "POST", ("a1", "go")),
    (callbacks.CallbacksHandler, "post", "POST", ("a1", "cb")),
]


def _call(
    cls: Any,
    target: str,
    override: str,
    args: tuple[str, ...],
    headers: dict[str, str],
    cookies: dict[str, str] | None = None,
) -> tuple[AWWebObj, mock.MagicMock]:
    config = Config(database="dynamodb")
    config.root = ROOT
    webobj = AWWebObj(
        params={"_method": override}, headers=headers, cookies=cookies or {}
    )
    handler = cls(webobj, config)
    with mock.patch.object(handler, target) as dispatched:
        handler.get(*args)
    return webobj, dispatched


@pytest.mark.parametrize("cls,target,override,args", SITES)
@pytest.mark.parametrize(
    "headers",
    [
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
        # A link opened from a mail or chat client.
        {"Sec-Fetch-Site": "none"},
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Referer": "https://evil.example/page"},
    ],
)
def test_cross_site_override_is_refused(
    cls: Any, target: str, override: str, args: tuple[str, ...], headers: dict[str, str]
) -> None:
    webobj, dispatched = _call(cls, target, override, args, headers)
    assert webobj.response.status_code == 403
    dispatched.assert_not_called()


@pytest.mark.parametrize("cls,target,override,args", SITES)
def test_header_less_session_cookie_override_is_refused(
    cls: Any, target: str, override: str, args: tuple[str, ...]
) -> None:
    """No browser headers (a browser without Fetch Metadata following a
    no-referrer link), but the session cookie: only a browser holds it."""
    webobj, dispatched = _call(
        cls,
        target,
        override,
        args,
        {"Authorization": "Bearer tok"},
        cookies={"oauth_token": "tok"},
    )
    assert webobj.response.status_code == 403
    dispatched.assert_not_called()


@pytest.mark.parametrize("cls,target,override,args", SITES)
@pytest.mark.parametrize(
    "headers",
    [
        {"Sec-Fetch-Site": "same-origin"},
        {"Origin": "https://DEMO.actingweb.io:443"},
        {"Referer": "https://demo.actingweb.io/a1/www/trust"},
        # A script or a peer: no browser headers, its own credentials.
        {},
        {"Authorization": "Basic eDp5"},
    ],
)
def test_same_origin_or_scripted_override_is_dispatched(
    cls: Any, target: str, override: str, args: tuple[str, ...], headers: dict[str, str]
) -> None:
    # Dispatched is the evidence: the callbacks handler falls through to
    # its GET's own authentication afterwards.
    _, dispatched = _call(cls, target, override, args, headers)
    dispatched.assert_called_once()


def test_base_path_root_compares_origin_only() -> None:
    config = Config(database="dynamodb")
    config.root = "https://demo.actingweb.io/base/"
    webobj = AWWebObj(
        params={"_method": "DELETE"}, headers={"Origin": "https://demo.actingweb.io"}
    )
    handler = root.RootHandler(webobj, config)
    with mock.patch.object(handler, "delete") as dispatched:
        handler.get("a1")
    dispatched.assert_called_once()
    assert handler._www_path("a1", "/trust") == "/base/a1/www/trust"


def test_a_get_without_an_override_is_not_checked() -> None:
    config = Config(database="dynamodb")
    config.root = ROOT
    webobj = AWWebObj(params={}, headers={"Sec-Fetch-Site": "cross-site"})
    handler = trust.TrustPeerHandler(webobj, config)
    assert handler._refuse_cross_site_override() is False
    assert webobj.response.status_code != 403


@pytest.mark.parametrize(
    "module,cls",
    [
        ("async_actions", "AsyncActionsHandler"),
        ("async_methods", "AsyncMethodsHandler"),
    ],
)
def test_async_handlers_refuse_a_cross_site_override(module: str, cls: str) -> None:
    import asyncio
    import importlib

    handler_cls = getattr(importlib.import_module(f"actingweb.handlers.{module}"), cls)
    config = Config(database="dynamodb")
    config.root = ROOT
    webobj = AWWebObj(params={"_method": "POST"}, headers={"Sec-Fetch-Site": "none"})
    handler = handler_cls(webobj, config)
    with mock.patch.object(handler, "post_async") as dispatched:
        asyncio.run(handler.get_async("a1", "go"))
    assert webobj.response.status_code == 403
    dispatched.assert_not_called()
