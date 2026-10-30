"""Property-list item limits and spanned items against the live backends.

thoughts/plans/2026-10-30-spanned-list-items.md: Phase 1's PostgreSQL
defaults check, and Phase 2's span round trips over HTTP and through the
library. The harness sets 390,000 / 4 MiB for both backends.
"""

import json
import os
import uuid
from collections.abc import Iterator

import pytest
import requests

from actingweb.config import Config
from actingweb.db import get_property
from actingweb.property import PropertyListStore
from actingweb.property_list import ListProperty
from actingweb.property_list_span import AUX_SUFFIX, parse
from tests.integration.test_property_list_http_contract import (
    _create_actor,
    _create_list,
    _delete_actor,
)


@pytest.fixture
def _require_postgresql() -> None:
    if os.getenv("DATABASE_BACKEND", "dynamodb") != "postgresql":
        pytest.skip("PostgreSQL-only test")


@pytest.fixture
def pg_list(_require_postgresql: None) -> Iterator[ListProperty]:
    config = Config()
    lst = ListProperty(f"pglimits-{uuid.uuid4().hex}", "big", config)
    yield lst
    lst.delete()


class TestPostgresqlDefaults:
    def test_config_built_directly_has_no_limits(self, _require_postgresql: None):
        config = Config()
        assert config.database == "postgresql"
        assert config.list_item_span_threshold is None
        assert config.list_item_max_bytes is None

    def test_five_mib_item_is_one_row_and_reads_back(self, pg_list: ListProperty):
        item = {"body": "x" * (5 * 2**20)}
        pg_list.append(item)
        assert pg_list.to_list() == [item]

        rows = get_property(pg_list.config).get_range(
            actor_id=pg_list.actor_id,
            lower="list:big-",
            upper="list:big-~",
        )
        item_rows = [name for name in rows if name != "list:big-meta"]
        assert len(item_rows) == 1
        assert json.loads(rows[item_rows[0]]) == item


# --- Spanned items on both backends (Phase 2) ------------------------------

LIMITS = {"list_item_span_threshold": 390_000, "list_item_max_bytes": 4 * 2**20}


def _limits_config() -> Config:
    # The backend comes from DATABASE_BACKEND; the limits are the harness's,
    # explicit so PostgreSQL spans too.
    return Config(**LIMITS)  # type: ignore[arg-type]


def _aux_rows(actor_id: str) -> dict[str, str]:
    return get_property(Config()).get_prefix(
        actor_id=actor_id + AUX_SUFFIX, prefix="list:"
    )


def _mib_item(tag: str) -> dict[str, str]:
    # About 1 MiB encoded.
    return {"id": tag, "body": tag * (2**20)}


@pytest.fixture
def http_actor(test_app: str) -> Iterator[tuple[str, tuple[str, str]]]:
    actor_id, creator, passphrase = _create_actor(test_app)
    auth = (creator, passphrase)
    yield actor_id, auth
    _delete_actor(test_app, actor_id, auth)


class TestSpannedItemsOverHttp:
    def test_round_trip_cascade_and_actor_delete(
        self, test_app: str, http_actor: tuple[str, tuple[str, str]]
    ) -> None:
        actor_id, auth = http_actor
        base = f"{test_app}/{actor_id}/properties"
        _create_list(test_app, actor_id, auth, "docs")
        first = _mib_item("a")

        r = requests.post(
            f"{base}/docs/items", json={"action": "add", "item_value": first}, auth=auth
        )
        assert r.status_code == 201
        assert requests.get(f"{base}/docs", auth=auth).json() == [first]
        assert requests.get(f"{base}/docs?index=0", auth=auth).json() == first
        meta = requests.get(f"{base}?metadata=true", auth=auth).json()
        assert meta["lists"]["docs"]["count"] == 1
        assert meta["lists"]["docs"]["total_bytes"] == len(json.dumps(first))
        aux = _aux_rows(actor_id)
        assert len(aux) == 3  # about 1 MiB at 390,000 bytes per body row

        # The actor's own partition dump holds no body row, and a list read
        # from it resolves the item.
        store = PropertyListStore(actor_id=actor_id, config=_limits_config())
        names, rows = store.list_all_with_rows()
        assert names == ["docs"]
        assert not any("$span-" in name for name in rows)
        lst = ListProperty(actor_id, "docs", _limits_config())
        lst.prime_from_rows(rows)
        assert lst.to_list_from_rows(rows) == [first]

        second = _mib_item("b")
        r = requests.put(f"{base}/docs?index=0", data=json.dumps(second), auth=auth)
        assert r.status_code == 204
        assert requests.get(f"{base}/docs", auth=auth).json() == [second]
        third = _mib_item("c")
        r = requests.post(
            f"{base}/docs/items",
            json={"action": "update", "item_index": 0, "item_value": third},
            auth=auth,
        )
        assert r.status_code == 204
        assert requests.get(f"{base}/docs?index=0", auth=auth).json() == third
        # Every rewrite deleted the generation it replaced.
        assert len(_aux_rows(actor_id)) == 3

        r = requests.post(
            f"{base}/docs/items",
            json={"action": "delete", "item_index": 0},
            auth=auth,
        )
        assert r.status_code == 204
        assert _aux_rows(actor_id) == {}

        requests.post(
            f"{base}/docs/items", json={"action": "add", "item_value": first}, auth=auth
        )
        assert _aux_rows(actor_id)
        assert requests.delete(f"{test_app}/{actor_id}", auth=auth).status_code == 204
        assert _aux_rows(actor_id) == {}

    def test_broken_span_answers_409_with_the_span_remedy(
        self, test_app: str, http_actor: tuple[str, tuple[str, str]]
    ) -> None:
        actor_id, auth = http_actor
        base = f"{test_app}/{actor_id}/properties"
        _create_list(test_app, actor_id, auth, "docs")
        requests.post(
            f"{base}/docs/items",
            json={"action": "add", "item_value": _mib_item("a")},
            auth=auth,
        )
        victim = sorted(_aux_rows(actor_id))[0]
        assert get_property(Config()).set(
            actor_id=actor_id + AUX_SUFFIX, name=victim, value=None
        )
        for url in (f"{base}/docs", f"{base}/docs?index=0", f"{base}/docs/items"):
            r = requests.get(url, auth=auth)
            assert r.status_code == 409, url
            body = r.json()
            assert body["error"] == "list_corrupted"
            assert "--sweep-spans" in body["remedy"]
        # format=full reports the one broken list instead of failing.
        full = requests.get(f"{base}?format=full", auth=auth)
        assert full.status_code == 200
        assert full.json()["docs"]["error"] == "list_corrupted"
        # The repair the remedy names.
        report = ListProperty(actor_id, "docs", _limits_config()).compact(
            sweep_span_orphans=True
        )
        assert report["broken_spans_removed"] == 1
        assert requests.get(f"{base}/docs", auth=auth).json() == []


class TestSpannedItemsInTheLibrary:
    def test_cascade_on_the_live_backend(self) -> None:
        actor_id = f"spans{uuid.uuid4().hex}"
        lst = ListProperty(actor_id, "docs", _limits_config())
        try:
            lst.append(_mib_item("a"))
            lst.append("small")
            handle, _ = lst.items_with_handles(resolve=False)[0]
            assert handle.spanned and handle.bytes == len(json.dumps(_mib_item("a")))
            assert lst.update_by_handle(handle, _mib_item("b"))
            assert lst.to_list() == [_mib_item("b"), "small"]
            assert len(_aux_rows(actor_id)) == 3
            assert lst.pop(0) == _mib_item("b")
            assert _aux_rows(actor_id) == {}
            lst.append(_mib_item("c"))
            assert lst.verify(spans=True)["broken_spans"] == []
        finally:
            lst.delete()
        assert _aux_rows(actor_id) == {}


@pytest.fixture
def _require_dynamodb() -> None:
    if os.getenv("DATABASE_BACKEND", "dynamodb") != "dynamodb":
        pytest.skip("DynamoDB-only test")


class TestDynamodbRowShape:
    def test_450kb_item_is_a_head_and_two_bodies(self, _require_dynamodb: None) -> None:
        """Every row stays under DynamoDB's 400 KB item cap.

        A direct ``DbProperty.set`` of a 450 KB value is attempted too:
        DynamoDB Local enforces the cap like DynamoDB (observed 2026-10-30
        with this repository's compose image), so the write raises
        ``DbError`` -- the untyped failure an unspanned item used to hit.
        """
        actor_id = f"spans{uuid.uuid4().hex}"
        config = Config(database="dynamodb")
        lst = ListProperty(actor_id, "docs", config)
        item = "x" * 450_000
        try:
            lst.append(item)
            (head,) = lst._v2_load_full()
            env = parse(head[1])
            assert env is not None and env.span is not None
            assert env.span.parts == 2
            bodies = _aux_rows(actor_id)
            assert len(bodies) == 2
            assert all(len(v) <= 390_000 for v in bodies.values())
            assert lst.to_list() == [item]
        finally:
            lst.delete()

        db = get_property(config)
        try:
            outcome = db.set(actor_id=actor_id, name="direct450", value=item)
        except Exception as e:  # folds DbError: recording the backend's answer
            outcome = type(e).__name__
        finally:
            db.set(actor_id=actor_id, name="direct450", value=None)
        assert outcome == "DbError", outcome


class TestPostgresqlMigration:
    def test_oversized_v1_item_migrates_unspanned_then_spans_on_rewrite(
        self, _require_postgresql: None
    ) -> None:
        actor_id = f"spans{uuid.uuid4().hex}"
        config = Config()
        db = get_property(config)
        big = "y" * 500_000
        db.set(actor_id=actor_id, name="list:old-0", value=json.dumps(big))
        db.set(
            actor_id=actor_id,
            name="list:old-meta",
            value=json.dumps(
                {"length": 1, "item_type": "json", "chunk_size": 1, "version": "1.0"}
            ),
        )
        lst = ListProperty(actor_id, "old", _limits_config())
        try:
            assert lst.migrate_to_v2()["migrated"] is True
            ((_, raw),) = lst._v2_load_full()
            assert parse(raw) is None  # an unspanned head, legal on PostgreSQL
            assert lst.to_list() == [big]
            handle, _ = lst.items_with_handles()[0]
            assert lst.update_by_handle(handle, big + "z")
            assert lst.items_with_handles(resolve=False)[0][0].spanned
            assert lst.to_list() == [big + "z"]
        finally:
            lst.delete()
