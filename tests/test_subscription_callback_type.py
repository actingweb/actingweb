"""A subscription ``callback`` is a bool on both backends (3.16).

PynamoDB stored any truthy value (a URL) as ``True``; PostgreSQL failed the
cast as a store fault. Both now refuse a non-bool with ``TypeError`` before
any I/O, naming the type and never the value.
"""

from __future__ import annotations

import importlib
from typing import Any
from unittest import mock

import pytest

URL = "https://peer.example.com/callback/secret-path"


def _backend(name: str) -> tuple[Any, Any]:
    """The subscription module and a DbSubscription with a loaded handle."""
    if name == "postgresql":
        pytest.importorskip("psycopg")
    module = importlib.import_module(f"actingweb.db.{name}.subscription")
    return module, module.DbSubscription()


@pytest.fixture(params=["dynamodb", "postgresql"])
def backend(request: pytest.FixtureRequest) -> Any:
    module, db = _backend(request.param)
    io = mock.Mock(side_effect=AssertionError("no I/O expected"))
    patches = [mock.patch.object(db, "get", io)]
    if request.param == "postgresql":
        patches.append(mock.patch.object(module, "get_connection", io))
    else:
        patches.append(mock.patch.object(module.Subscription, "save", io))
        patches.append(mock.patch.object(module.Subscription, "update", io))
    for p in patches:
        p.start()
    try:
        yield db, io
    finally:
        for p in patches:
            p.stop()


def test_create_refuses_a_string_before_any_io(backend: Any) -> None:
    db, io = backend
    with pytest.raises(TypeError) as raised:
        db.create(actor_id="a", peerid="p", subid="s", callback=URL)
    message = str(raised.value)
    assert "str" in message and "callback=True" in message
    assert URL not in message and "secret-path" not in message
    io.assert_not_called()


def test_modify_refuses_a_non_bool_and_accepts_none(backend: Any) -> None:
    db, io = backend
    db.handle = {"id": "a", "peerid": "p", "subscriptionid": "s"}
    with pytest.raises(TypeError) as raised:
        db.modify(callback="x")
    assert "bool or None" in str(raised.value)
    with pytest.raises(TypeError):
        db.modify(callback=1)
    io.assert_not_called()
    db.handle = None  # None passes the guard; no handle answers False
    assert db.modify(callback=None) is False


def test_an_int_is_not_a_bool_for_create(backend: Any) -> None:
    db, _io = backend
    with pytest.raises(TypeError):
        db.create(actor_id="a", peerid="p", subid="s", callback=1)
