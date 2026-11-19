"""AC-25 over a library route: a list holding an item a later version
stored answers 409 with the fixed code on the list read; the properties
listing, which counts heads without reading them, is still served."""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from actingweb.db import get_property
from actingweb.interface import ActingWebApp
from actingweb.interface.actor_interface import ActorInterface
from tests._adoption_helpers import aid, create_core_actor, uuid_email

NEWER = json.dumps({"__aw_env": 1, "need": ["future"], "v": "later"})


def _app() -> tuple[TestClient, Any]:
    app = ActingWebApp(
        aw_type="urn:actingweb:test:newer-http",
        database="dynamodb",
        fqdn="test.example.com",
        proto="https://",
    ).with_web_ui(enable=False)
    fastapi_app = FastAPI()
    app.integrate_fastapi(fastapi_app)
    return TestClient(fastapi_app), app.get_config()


def test_a_list_read_and_the_listing_answer_the_newer_format() -> None:
    client, config = _app()
    creator = uuid_email()
    actor = create_core_actor(config, creator, auth_method="app")
    iface = ActorInterface.get_by_id(aid(actor), config)
    assert iface is not None
    notes = iface.property_lists.notes
    notes.append("a")
    iface.property_lists.other.append("kept")
    db = get_property(config)
    rows = db.get_prefix(actor_id=aid(actor), prefix="list:notes-#") or {}
    head = sorted(rows)[0]
    db.set(actor_id=aid(actor), name=head, value=NEWER)
    auth = (creator, "squatter-passphrase")

    one = client.get(f"/{aid(actor)}/properties/notes", auth=auth)
    assert one.status_code == 409, one.text
    assert one.json()["code"] == "list_item_newer_format"
    assert "later" not in one.text

    # The listing counts heads without reading them: still served.
    listing = client.get(f"/{aid(actor)}/properties", auth=auth)
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert body["notes"]["_list"] is True and body["other"]["_list"] is True
