"""
HTTP-level tests for the Phase 3 property-list REST contract
(thoughts/plans/2026-08-08-property-list-index-integrity.md):

- /items GET returns the indexed-pair shape ({"items": [{"index", "item"}],
  "count": n}) and /items POST action=update/delete round-trip against it.
- A punched hole returns a structured 409 from every list-serving path,
  and 200 again after compact().
- Bulk POST (list-shaped POST /properties) applies updates before deletes
  regardless of payload order, closing the intra-batch index-skew bug.
- PUT ?index=N beyond the list length returns 404 (spec: "List Property
  PUT" -- index == length MAY create, index > length MUST 404), not the
  old unbounded append(None) padding.
"""

import uuid

import pytest
import requests

from actingweb.config import Config
from actingweb.db import get_property


def _create_actor(test_app):
    response = requests.post(
        f"{test_app}/",
        json={"creator": f"phase3-{uuid.uuid4()}@example.com"},
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 201
    data = response.json()
    return data["id"], data["creator"], data["passphrase"]


def _delete_actor(test_app, actor_id, auth):
    try:
        requests.delete(f"{test_app}/{actor_id}", auth=auth)
    except Exception:
        pass


def _create_list(test_app, actor_id, auth, list_name):
    response = requests.post(
        f"{test_app}/{actor_id}/properties",
        json={list_name: {"_type": "list"}},
        auth=auth,
    )
    assert response.status_code == 201


def _append_items(test_app, actor_id, auth, list_name, items):
    for item in items:
        response = requests.post(
            f"{test_app}/{actor_id}/properties/{list_name}/items",
            json={"action": "add", "item_value": item},
            auth=auth,
        )
        assert response.status_code == 201


def _punch_hole(actor_id, list_name, index):
    """Directly delete a list item row, bypassing the API -- the residue an
    interrupted delete/insert shift leaves behind."""
    config = Config()
    db = get_property(config)
    assert db.set(actor_id=actor_id, name=f"list:{list_name}-{index}", value=None)


@pytest.fixture
def actor(test_app):
    actor_id, creator, passphrase = _create_actor(test_app)
    auth = (creator, passphrase)
    yield actor_id, auth
    _delete_actor(test_app, actor_id, auth)


class TestItemsEndpointShape:
    def test_get_returns_indexed_pairs(self, test_app, actor):
        actor_id, auth = actor
        _create_list(test_app, actor_id, auth, "notes")
        _append_items(test_app, actor_id, auth, "notes", ["a", "b", "c"])

        response = requests.get(
            f"{test_app}/{actor_id}/properties/notes/items", auth=auth
        )
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 3
        assert data["items"] == [
            {"index": 0, "item": "a"},
            {"index": 1, "item": "b"},
            {"index": 2, "item": "c"},
        ]

    def test_post_action_update_round_trips(self, test_app, actor):
        actor_id, auth = actor
        _create_list(test_app, actor_id, auth, "notes")
        _append_items(test_app, actor_id, auth, "notes", ["a", "b", "c"])

        response = requests.post(
            f"{test_app}/{actor_id}/properties/notes/items",
            json={"action": "update", "item_index": 1, "item_value": "UPDATED"},
            auth=auth,
        )
        assert response.status_code == 204

        response = requests.get(
            f"{test_app}/{actor_id}/properties/notes/items", auth=auth
        )
        assert response.json()["items"] == [
            {"index": 0, "item": "a"},
            {"index": 1, "item": "UPDATED"},
            {"index": 2, "item": "c"},
        ]

    def test_post_action_delete_round_trips(self, test_app, actor):
        actor_id, auth = actor
        _create_list(test_app, actor_id, auth, "notes")
        _append_items(test_app, actor_id, auth, "notes", ["a", "b", "c"])

        response = requests.post(
            f"{test_app}/{actor_id}/properties/notes/items",
            json={"action": "delete", "item_index": 1},
            auth=auth,
        )
        assert response.status_code == 204

        response = requests.get(
            f"{test_app}/{actor_id}/properties/notes/items", auth=auth
        )
        assert response.json()["items"] == [
            {"index": 0, "item": "a"},
            {"index": 1, "item": "c"},
        ]


class TestCorruptionReturns409:
    def test_holed_list_returns_409_everywhere_then_200_after_compact(
        self, test_app, actor
    ):
        actor_id, auth = actor
        _create_list(test_app, actor_id, auth, "notes")
        _append_items(test_app, actor_id, auth, "notes", ["a", "b", "c"])
        _punch_hole(actor_id, "notes", 1)

        expected_body_keys = {"error", "list", "detail", "remedy"}

        r1 = requests.get(f"{test_app}/{actor_id}/properties/notes/items", auth=auth)
        assert r1.status_code == 409
        body = r1.json()
        assert expected_body_keys <= set(body.keys())
        assert body["error"] == "list_corrupted"
        assert body["list"] == "notes"
        assert body["remedy"] == "compact"

        r2 = requests.get(f"{test_app}/{actor_id}/properties/notes", auth=auth)
        assert r2.status_code == 409
        assert r2.json()["error"] == "list_corrupted"

        r3 = requests.get(f"{test_app}/{actor_id}/properties?format=full", auth=auth)
        assert r3.status_code == 409
        assert r3.json()["error"] == "list_corrupted"

        # Repair directly (compact() is a library API, no HTTP endpoint).
        config = Config()
        from actingweb.property_list import ListProperty

        ListProperty(actor_id=actor_id, name="notes", config=config).compact()

        r4 = requests.get(f"{test_app}/{actor_id}/properties/notes/items", auth=auth)
        assert r4.status_code == 200
        assert r4.json()["count"] == 2


class TestBulkPostIntraBatchOrdering:
    def test_delete_before_update_in_payload_does_not_skew_indices(
        self, test_app, actor
    ):
        """Regression: a delete at a lower index appearing BEFORE an update
        at a higher index in the request body must not shift the update's
        target. All indices are interpreted against the pre-batch list."""
        actor_id, auth = actor
        _create_list(test_app, actor_id, auth, "todos")
        response = requests.post(
            f"{test_app}/{actor_id}/properties",
            json={
                "todos": {
                    "items": [
                        {"index": 0, "task": "a"},
                        {"index": 1, "task": "b"},
                        {"index": 2, "task": "c"},
                        {"index": 3, "task": "d"},
                    ]
                }
            },
            auth=auth,
        )
        assert response.status_code == 201

        # Payload order: delete index 0 comes BEFORE update index 2. Under
        # naive in-order processing this would shift index 2 down to
        # index 1 before the delete, and the update (still targeting
        # "index 2") would land on the wrong item ("d", post-shift).
        response = requests.post(
            f"{test_app}/{actor_id}/properties",
            json={
                "todos": {
                    "items": [
                        {"index": 0},  # delete "a"
                        {"index": 2, "task": "UPDATED"},  # update "c"
                    ]
                }
            },
            auth=auth,
        )
        assert response.status_code == 201

        response = requests.get(f"{test_app}/{actor_id}/properties/todos", auth=auth)
        assert response.status_code == 200
        items = response.json()
        assert [i["task"] for i in items] == ["b", "UPDATED", "d"]


class TestPutBeyondLength:
    def test_index_equal_to_length_appends(self, test_app, actor):
        actor_id, auth = actor
        _create_list(test_app, actor_id, auth, "notes")

        response = requests.put(
            f"{test_app}/{actor_id}/properties/notes?index=0",
            json="first",
            auth=auth,
        )
        assert response.status_code == 204

        response = requests.get(f"{test_app}/{actor_id}/properties/notes", auth=auth)
        assert response.json() == ["first"]

    def test_index_beyond_length_returns_404(self, test_app, actor):
        actor_id, auth = actor
        _create_list(test_app, actor_id, auth, "notes")

        response = requests.put(
            f"{test_app}/{actor_id}/properties/notes?index=0",
            json="first",
            auth=auth,
        )
        assert response.status_code == 204

        # Length is now 1 -- index 1 MAY append, index 2 MUST 404.
        response = requests.put(
            f"{test_app}/{actor_id}/properties/notes?index=2",
            json="skips-ahead",
            auth=auth,
        )
        assert response.status_code == 404

        # The list must NOT have been padded.
        response = requests.get(f"{test_app}/{actor_id}/properties/notes", auth=auth)
        assert response.json() == ["first"]
