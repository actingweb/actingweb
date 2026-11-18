"""The fetch after a grant takes the baseline's decision (4.0).

When a peer grants a property, the subscriber fetches it
(``CallbacksHandler._fetch_single_property``). A text value that is not JSON
reaches the proxy as ``{}``; it was stored as ``{}``. The fetch now decides
as the baseline does: a non-2xx or redirected answer stores nothing, text
the publisher itself answered is stored, an empty body or ``{}`` removes the
replica's value, and an answer that is not the publisher's stores nothing.

A real ``AwProxy`` with the HTTP call replaced: a mock proxy reads as
redirected.
"""

from __future__ import annotations

import json
from typing import Any
from unittest import mock
from unittest.mock import MagicMock

import pytest

from actingweb.aw_proxy import AwProxy
from actingweb.handlers.callbacks import CallbacksHandler
from actingweb.remote_storage import RemotePeerStore
from tests.mcp_token_double import make_config

ACTOR = "a" * 32
PEER = "b" * 32
BASE = "https://peer.example/" + PEER


class _Response:
    def __init__(
        self,
        body: bytes,
        content_type: str,
        status: int = 200,
        redirected_to: str | None = None,
    ) -> None:
        self.status_code = status
        self.content = body
        self.headers = {"content-type": content_type}
        self.history = [object()] if redirected_to else []
        self.url = redirected_to or ""

    def json(self) -> Any:
        return json.loads(self.content.decode("utf-8"))


def _proxy(config: Any) -> AwProxy:
    proxy = AwProxy(config=config)
    proxy.trust = {"baseuri": BASE, "secret": "s", "peerid": PEER}
    return proxy


def _remote(config: Any) -> RemotePeerStore:
    actor = MagicMock()
    actor.id = ACTOR
    actor.config = config
    return RemotePeerStore(actor, PEER, validate_peer_id=False)


def _fetch(response: _Response, remote: RemotePeerStore, config: Any) -> None:
    handler = CallbacksHandler.__new__(CallbacksHandler)
    with mock.patch("actingweb.aw_proxy.requests.get", return_value=response):
        handler._fetch_single_property(  # pyright: ignore[reportPrivateUsage]
            _proxy(config), remote, PEER, "note"
        )


@pytest.fixture
def config() -> Any:
    cfg, _store = make_config()
    return cfg


def test_a_granted_text_property_reaches_the_replica_as_text(config: Any) -> None:
    remote = _remote(config)
    _fetch(_Response(b"hello there", "text/plain; charset=utf-8"), remote, config)
    assert remote.get_value("note") == {"value": "hello there"}


@pytest.mark.parametrize(
    "response",
    [
        _Response(b"hello", "text/plain", redirected_to="https://login.example/"),
        _Response(b"<html>sign in</html>", "text/html"),
        _Response(
            b'{"v": 1}', "application/json", redirected_to="https://login.example/"
        ),
        _Response(b"oops", "text/plain", status=500),
    ],
    ids=["redirect", "text/html", "redirected JSON", "non-2xx"],
)
def test_an_answer_that_is_not_the_publishers_stores_nothing(
    config: Any, response: _Response
) -> None:
    remote = _remote(config)
    remote.set_value("note", {"value": "kept"})
    _fetch(response, remote, config)
    assert remote.get_value("note") == {"value": "kept"}


@pytest.mark.parametrize(
    "response",
    [_Response(b"", "text/plain"), _Response(b"{}", "application/json")],
    ids=["empty body", "{}"],
)
@pytest.mark.parametrize("held", ["plain", "list"])
def test_an_empty_answer_removes_the_replicas_value(
    config: Any, response: _Response, held: str
) -> None:
    remote = _remote(config)
    if held == "plain":
        remote.set_value("note", {"value": "old"})
    else:
        remote.set_list("note", [{"t": "old"}])
    _fetch(response, remote, config)
    assert remote.get_value("note") is None
    assert remote.get_list("note") == []


def test_a_json_object_is_still_stored_as_it_is(config: Any) -> None:
    remote = _remote(config)
    _fetch(_Response(b'{"v": 1}', "application/json"), remote, config)
    assert remote.get_value("note") == {"v": 1}


def test_an_empty_answer_with_the_list_names_unreadable_raises(config: Any) -> None:
    """A fault reading which lists the replica holds is not "no list": the
    delete would leave the list behind and report the value removed. It
    raises before anything is deleted (the sync logs it)."""
    from actingweb.db.exceptions import DbError

    remote = _remote(config)
    remote.set_list("note", [{"t": "old"}])

    def faulting(*, strict: bool = False) -> list[str]:
        if strict:
            raise DbError("list read")
        return []

    with (
        mock.patch.object(remote, "list_all_lists", side_effect=faulting),
        pytest.raises(DbError),
    ):
        _fetch(_Response(b"", "text/plain"), remote, config)
    assert remote.get_list("note") == [{"t": "old"}]
