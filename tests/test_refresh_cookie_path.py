"""The SPA ``refresh_token`` cookie lives on one path (re-verification N3).

The OAuth callback's hybrid delivery set it on ``/oauth/spa/token`` and the
refresh grant's rotation on ``/``. FastAPI used to drop the path, so both
landed on ``/``; once it kept the path, ``/oauth/logout`` no longer received
the callback's cookie and a browser could hold two. Every setter now uses
``set_refresh_cookie``: ``path=/``, and the old path expired.

Plan: thoughts/plans/2026-11-02-3-16-adoption-fault-followups.md, entry 22.
"""

from __future__ import annotations

from typing import Any

from actingweb.aw_web_request import AWWebObj
from actingweb.handlers.oauth2_spa import (
    LEGACY_REFRESH_COOKIE_PATH,
    set_refresh_cookie,
)


def _webobj() -> AWWebObj:
    return AWWebObj(
        url="https://test.example.com/", params={}, body="", headers={}, cookies={}
    )


def _refresh_cookies(webobj: AWWebObj) -> list[dict[str, Any]]:
    return [c for c in webobj.response.cookies if c["name"] == "refresh_token"]


def test_the_cookie_is_set_on_root_and_the_old_path_expired() -> None:
    webobj = _webobj()
    set_refresh_cookie(webobj.response, "tok", samesite="Strict")
    cookies = _refresh_cookies(webobj)
    live = [c for c in cookies if c["value"]]
    expired = [c for c in cookies if not c["value"]]
    assert len(live) == 1 and live[0]["path"] == "/"
    assert live[0]["samesite"] == "Strict" and live[0]["httponly"] is True
    assert len(expired) == 1 and expired[0]["path"] == LEGACY_REFRESH_COOKIE_PATH
    assert expired[0]["max_age"] == -1


def test_fastapi_keeps_the_root_path() -> None:
    from starlette.responses import Response

    from actingweb.interface.integrations.fastapi_integration import _apply_cookies

    webobj = _webobj()
    set_refresh_cookie(webobj.response, "tok")
    response = Response()
    _apply_cookies(response, webobj)
    headers = [
        v.decode().lower() for k, v in response.raw_headers if k == b"set-cookie"
    ]
    assert any(h.startswith("refresh_token=tok;") and "path=/;" in h for h in headers)
    assert any(
        h.startswith("refresh_token=") and "path=/oauth/spa/token" in h for h in headers
    )


def test_no_handler_sets_a_live_refresh_cookie_off_root() -> None:
    """The callback's two hybrid sites go through the helper: a handler
    that sets ``refresh_token`` with a value on another path would split it
    again (the setters live in handlers the provider flow reaches only with
    a real provider)."""
    import inspect

    from actingweb.handlers import oauth2_callback

    source = inspect.getsource(oauth2_callback)
    assert source.count("set_refresh_cookie(") == 2
    assert 'path="/oauth/spa/token"' not in source
