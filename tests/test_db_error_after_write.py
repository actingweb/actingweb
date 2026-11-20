"""AC-22: ``DbErrorAfterWrite``: a property or list write was stored and the
fault came after it, registering its diff. A plain ``DbError`` means nothing
was written (or the caller cannot tell); the subclass tells a caller that a
repeat of a plain set is safe, while a repeat of an unkeyed append adds a
second item (``append_once`` does not)."""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from actingweb.actor import Actor
from actingweb.db.exceptions import DbError, DbErrorAfterWrite
from actingweb.interface import ActingWebApp
from actingweb.interface.actor_interface import ActorInterface
from actingweb.interface.integrations._errors import db_error_answer
from tests._adoption_helpers import aid, create_core_actor, make_config, uuid_email


def _faulting_diffs(*_a: Any, **_k: Any) -> Any:
    raise DbError("diff registration")


def _iface() -> tuple[Any, ActorInterface]:
    config = make_config()
    actor = create_core_actor(config, uuid_email(), auth_method="app")
    found = ActorInterface.get_by_id(aid(actor), config)
    assert found is not None
    return config, found


def test_a_diff_fault_after_a_property_write() -> None:
    _config, iface = _iface()
    with (
        mock.patch.object(Actor, "register_diffs", _faulting_diffs),
        pytest.raises(DbErrorAfterWrite),
    ):
        iface.properties["note"] = "stored"
    assert iface.properties["note"] == "stored"


def test_a_diff_fault_after_a_list_write() -> None:
    _config, iface = _iface()
    notes = iface.property_lists.notes
    with (
        mock.patch.object(Actor, "register_diffs", _faulting_diffs),
        pytest.raises(DbErrorAfterWrite),
    ):
        notes.append({"text": "one"})
    assert list(iface.property_lists.notes) == [{"text": "one"}]


def test_clear_faults_before_its_write_is_plain() -> None:
    _config, iface = _iface()
    iface.properties["keep"] = "me"
    with (
        mock.patch.object(Actor, "register_diffs", _faulting_diffs),
        pytest.raises(DbError) as raised,
    ):
        iface.properties.clear()
    assert not isinstance(raised.value, DbErrorAfterWrite)
    assert iface.properties["keep"] == "me"


def test_the_wire_answer_has_its_own_code_and_no_retry_after() -> None:
    status, headers, body = db_error_answer(DbErrorAfterWrite("diff", "a1"))
    assert status == 503
    assert "Retry-After" not in headers
    assert headers["X-ActingWeb-Error"] == body["code"] == "stored_not_notified"
    plain_status, plain_headers, plain_body = db_error_answer(DbError("x"))
    assert plain_status == 503 and plain_headers["Retry-After"] == "5"
    assert plain_body["code"] != "stored_not_notified"


def test_a_rest_put_whose_diff_faults_answers_the_after_write_code() -> None:
    """A REST put whose diff faults answers the after-write code; the value
    is stored."""
    app = ActingWebApp(
        aw_type="urn:actingweb:test:after-write",
        database="dynamodb",
        fqdn="test.example.com",
        proto="https://",
    ).with_web_ui(enable=False)
    fastapi_app = FastAPI()
    app.integrate_fastapi(fastapi_app)
    config = app.get_config()
    creator = uuid_email()
    actor = create_core_actor(config, creator, auth_method="app")
    client = TestClient(fastapi_app)
    with mock.patch.object(Actor, "register_diffs", _faulting_diffs):
        resp = client.put(
            f"/{aid(actor)}/properties/note",
            content="stored",
            auth=(creator, "squatter-passphrase"),
        )
    assert resp.status_code == 503
    assert resp.headers["X-ActingWeb-Error"] == "stored_not_notified"
    assert "Retry-After" not in resp.headers
    again = Actor(actor_id=aid(actor), config=config)
    assert again.property is not None and again.property["note"] == "stored"


def test_append_once_repeat_does_not_duplicate() -> None:
    _config, iface = _iface()
    notes = iface.property_lists.once
    with (
        mock.patch.object(Actor, "register_diffs", _faulting_diffs),
        pytest.raises(DbErrorAfterWrite),
    ):
        notes.append_once({"text": "one"}, key="k1")
    iface.property_lists.once.append_once({"text": "one"}, key="k1")
    assert list(iface.property_lists.once) == [{"text": "one"}]
