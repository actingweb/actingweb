"""Property-list item size limits: the backend-aware defaults, the Config
validation, ``ListItemTooLargeError`` raised before any write, and the 413
the REST handlers answer with.

Phase 1 of thoughts/plans/2026-10-30-spanned-list-items.md. The library
tests use the dict-backed ``FakePropertyDb``; the handler tests run against
DynamoDB Local through the module-private helpers of
``tests/test_bulk_list_update_handles.py``.
"""

import json
import logging
import os
import types
import uuid
from typing import Any
from unittest import mock

import pytest

import actingweb
from actingweb.config import Config
from actingweb.handlers.properties import PropertiesHandler, PropertyListItemsHandler
from actingweb.property_list import ListItemTooLargeError, ListProperty
from actingweb.property_list_span import (
    ITEM_MAX_BYTES_DEFAULT,
    SPAN_THRESHOLD_DEFAULT,
    encoded_size,
)
from tests.test_bulk_list_update_handles import _post_bulk, _run_handler
from tests.test_property_list_integrity import FakePropertyDb

ACTOR = "actor-limits"


@pytest.fixture
def store() -> dict[Any, Any]:
    return {}


@pytest.fixture(autouse=True)
def _fake_db(monkeypatch: pytest.MonkeyPatch, store: dict[Any, Any]) -> None:
    monkeypatch.setattr(
        "actingweb.property_list.get_property", lambda config: FakePropertyDb(store)
    )


def _small_config(database: str = "dynamodb") -> Config:
    return Config(
        database=database,
        list_item_span_threshold=2_000,
        list_item_max_bytes=20_000,
    )


def _item_of(size: int) -> str:
    """A string item whose encoded JSON is exactly ``size`` bytes."""
    item = "x" * (size - 2)
    assert encoded_size(json.dumps(item)) == size
    return item


def _seed_v1(store: dict[Any, Any], name: str, items: list[Any]) -> None:
    for i, item in enumerate(items):
        store[(ACTOR, f"list:{name}-{i}")] = json.dumps(item)
    store[(ACTOR, f"list:{name}-meta")] = json.dumps(
        {
            "length": len(items),
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
            "item_type": "json",
            "chunk_size": 1,
            "version": "1.0",
            "description": "",
            "explanation": "",
        }
    )


def _v2_list(store: dict[Any, Any], config: Config, items: list[Any]) -> ListProperty:
    lst = ListProperty(ACTOR, "v2list", config)
    lst.extend(items)
    return lst


class TestBackendDefaults:
    def test_dynamodb_defaults(self) -> None:
        config = Config(database="dynamodb")
        assert config.list_item_span_threshold == SPAN_THRESHOLD_DEFAULT == 390_000
        assert config.list_item_max_bytes == ITEM_MAX_BYTES_DEFAULT == 4 * 2**20

    def test_postgresql_defaults_are_off(self) -> None:
        config = Config(database="postgresql")
        assert config.list_item_span_threshold is None
        assert config.list_item_max_bytes is None

    def test_backend_without_max_row_bytes_gets_no_limits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import importlib

        real_import = importlib.import_module
        bare = types.ModuleType("bare_property")
        bare.DbProperty = type("DbProperty", (), {})  # type: ignore[attr-defined]

        def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "actingweb.db.dynamodb.property":
                return bare
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("actingweb.config.importlib.import_module", fake_import)
        config = Config(database="dynamodb")
        assert config.list_item_span_threshold is None
        assert config.list_item_max_bytes is None


class TestConfigValidation:
    @pytest.mark.parametrize("bad", [400_001, 390_001, 0, -1, True, "1000", 1.5])
    def test_span_threshold_out_of_range_refused_from_kwargs(self, bad: Any) -> None:
        with pytest.raises(ValueError):
            Config(database="dynamodb", list_item_span_threshold=bad)

    @pytest.mark.parametrize("bad", [400_001, 0, False])
    def test_span_threshold_out_of_range_refused_on_assignment(self, bad: Any) -> None:
        config = Config(database="dynamodb")
        with pytest.raises(ValueError):
            config.list_item_span_threshold = bad

    @pytest.mark.parametrize("bad", [0, -5, True, "x"])
    def test_max_bytes_out_of_range_refused(self, bad: Any) -> None:
        with pytest.raises(ValueError):
            Config(database="dynamodb", list_item_max_bytes=bad)
        config = Config(database="dynamodb")
        with pytest.raises(ValueError):
            config.list_item_max_bytes = bad

    def test_max_bytes_below_span_threshold_refused_from_kwargs(self) -> None:
        with pytest.raises(ValueError, match="at least"):
            Config(database="dynamodb", list_item_max_bytes=100_000)

    def test_pair_given_in_either_order(self) -> None:
        config = Config(
            database="dynamodb",
            list_item_max_bytes=100_000,
            list_item_span_threshold=50_000,
        )
        assert (config.list_item_span_threshold, config.list_item_max_bytes) == (
            50_000,
            100_000,
        )

    def test_none_accepted_for_either(self) -> None:
        config = Config(
            database="dynamodb",
            list_item_span_threshold=None,
            list_item_max_bytes=None,
        )
        assert config.list_item_span_threshold is None
        assert config.list_item_max_bytes is None


class TestLimitsReader:
    def test_mock_config_sets_no_limit(self) -> None:
        lst = ListProperty(ACTOR, "m", mock.Mock())
        assert lst._limits() == (None, None)

    def test_real_values_are_read(self) -> None:
        lst = ListProperty(ACTOR, "m", _small_config())
        assert lst._limits() == (2_000, 20_000)


class TestV2RefusedBeforeAnyWrite:
    """An item over max_bytes raises from every v2 item write, and nothing
    is written -- not even the meta row of a never-created list."""

    def test_append_on_never_created_list_writes_nothing(
        self, store: dict[Any, Any]
    ) -> None:
        lst = ListProperty(ACTOR, "fresh", _small_config())
        with pytest.raises(ListItemTooLargeError) as exc:
            lst.append(_item_of(20_001))
        assert exc.value.bytes == 20_001
        assert exc.value.limit == 20_000
        assert store == {}
        assert ListProperty(ACTOR, "fresh", _small_config())._read_meta_row() == (
            None,
            None,
        )

    def test_extend_with_oversized_item_in_position_3_writes_nothing(
        self, store: dict[Any, Any]
    ) -> None:
        lst = ListProperty(ACTOR, "fresh", _small_config())
        with pytest.raises(ListItemTooLargeError):
            lst.extend(["a", "b", _item_of(20_001), "d"])
        assert store == {}

    def test_insert_on_never_created_list_writes_nothing(
        self, store: dict[Any, Any]
    ) -> None:
        lst = ListProperty(ACTOR, "fresh", _small_config())
        with pytest.raises(ListItemTooLargeError):
            lst.insert(0, _item_of(20_001))
        assert store == {}

    def test_setitem_and_update_by_handle_leave_the_item(
        self, store: dict[Any, Any]
    ) -> None:
        config = _small_config()
        lst = _v2_list(store, config, ["a", "b"])
        before = dict(store)
        with pytest.raises(ListItemTooLargeError):
            lst[1] = _item_of(20_001)
        handle, _ = lst.items_with_handles()[0]
        with pytest.raises(ListItemTooLargeError):
            lst.update_by_handle(handle, _item_of(20_001))
        assert store == before
        assert lst.to_list() == ["a", "b"]

    def test_over_span_threshold_refused_until_items_can_span(
        self, store: dict[Any, Any]
    ) -> None:
        lst = ListProperty(ACTOR, "fresh", _small_config())
        with pytest.raises(ListItemTooLargeError) as exc:
            lst.append(_item_of(2_001))
        assert exc.value.limit == 2_000
        assert store == {}

    def test_item_of_exactly_the_threshold_is_stored(
        self, store: dict[Any, Any]
    ) -> None:
        lst = ListProperty(ACTOR, "fresh", _small_config())
        item = _item_of(2_000)
        lst.append(item)
        assert lst.to_list() == [item]

    def test_non_ascii_item_measured_as_escaped_json(self) -> None:
        lst = ListProperty(ACTOR, "fresh", _small_config())
        # Each "é" encodes as "é", six bytes: 400 of them plus quotes
        # is 2,402 bytes, over the threshold although 400 characters.
        with pytest.raises(ListItemTooLargeError) as exc:
            lst.append("é" * 400)
        assert exc.value.bytes == 2_402


class TestV1RefusedBeforeAnyWrite:
    def test_append_insert_setitem_on_v1(self, store: dict[Any, Any]) -> None:
        _seed_v1(store, "old", ["a", "b"])
        before = dict(store)
        lst = ListProperty(ACTOR, "old", _small_config())
        with pytest.raises(ListItemTooLargeError):
            lst.append(_item_of(20_001))
        with pytest.raises(ListItemTooLargeError):
            lst.insert(0, _item_of(20_001))
        with pytest.raises(ListItemTooLargeError):
            lst[0] = _item_of(20_001)
        with pytest.raises(ListItemTooLargeError):
            lst.extend(["c", _item_of(20_001)])
        assert store == before

    def test_v1_item_over_390000_raises_on_dynamodb(
        self, store: dict[Any, Any]
    ) -> None:
        _seed_v1(store, "old", ["a"])
        before = dict(store)
        lst = ListProperty(ACTOR, "old", Config(database="dynamodb"))
        with pytest.raises(ListItemTooLargeError) as exc:
            lst.append(_item_of(390_001))
        assert exc.value.limit == 390_000
        assert store == before

    def test_v1_item_over_390000_is_one_row_on_postgresql(
        self, store: dict[Any, Any]
    ) -> None:
        _seed_v1(store, "old", ["a"])
        lst = ListProperty(ACTOR, "old", Config(database="postgresql"))
        big = _item_of(390_001)
        lst.append(big)
        assert json.loads(store[(ACTOR, "list:old-1")]) == big


class TestErrorShape:
    def test_message_carries_no_item_content(self) -> None:
        lst = ListProperty(ACTOR, "secretlist", _small_config())
        with pytest.raises(ListItemTooLargeError) as exc:
            lst.append("SECRET-" + "x" * 20_000)
        text = str(exc.value)
        assert "SECRET" not in text
        assert "secretlist" in text
        assert "20000" in text or "20,000" in text

    def test_is_a_value_error_and_exported(self) -> None:
        assert issubclass(ListItemTooLargeError, ValueError)
        assert actingweb.ListItemTooLargeError is ListItemTooLargeError
        assert "ListItemTooLargeError" in actingweb.__all__


# --- REST handlers: 413 (DynamoDB Local) ---------------------------------


@pytest.fixture
def _require_dynamodb() -> None:
    if os.getenv("DATABASE_BACKEND", "dynamodb") != "dynamodb":
        pytest.skip("DynamoDB-only test")


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch, _require_dynamodb: None) -> Any:
    """A real actor on DynamoDB Local with small limits. Undoes this
    module's autouse fake so the handlers reach real storage."""
    from actingweb.actor import Actor
    from actingweb.db import get_property

    monkeypatch.setattr("actingweb.property_list.get_property", get_property)
    config = Config(
        database="dynamodb",
        list_item_span_threshold=2_000,
        list_item_max_bytes=20_000,
    )
    actor_id = f"limits-{uuid.uuid4()}"
    a = Actor(config=config)
    assert a.create(
        url=f"https://example.com/{actor_id}",
        creator="tester@example.com",
        passphrase="testpass",
        actor_id=actor_id,
    )
    yield a, config
    a.delete()


def _assert_413(webobj: Any, name: str, size: int, limit: int) -> None:
    assert webobj.response.status_code == 413
    body = json.loads(webobj.response.body)
    assert body["error"] == "list_item_too_large"
    assert body["list"] == name
    assert body["bytes"] == size
    assert body["limit"] == limit
    assert body["remedy"] == "split the item or raise list_item_max_bytes"
    assert "detail" in body


class TestHandlers413:
    def test_put_index(self, live: Any, caplog: pytest.LogCaptureFixture) -> None:
        myself, config = live
        myself.property_lists.big.append("a")
        with caplog.at_level(logging.WARNING):
            webobj = _run_handler(
                PropertiesHandler,
                myself,
                config,
                "put",
                "big",
                params={"index": "0"},
                body=json.dumps("y" * 20_000),
            )
        _assert_413(webobj, "big", 20_002, 20_000)
        assert myself.property_lists.big.to_list() == ["a"]

    def test_items_post_add_and_update(self, live: Any) -> None:
        myself, config = live
        myself.property_lists.items.append("a")
        for params in (
            {"action": "add", "item_value": "y" * 20_000},
            {"action": "update", "item_index": 0, "item_value": "y" * 20_000},
        ):
            webobj = _run_handler(
                PropertyListItemsHandler,
                myself,
                config,
                "post",
                "items",
                body=json.dumps(params),
            )
            _assert_413(webobj, "items", 20_002, 20_000)
        assert myself.property_lists.items.to_list() == ["a"]

    def test_bulk_post(self, live: Any) -> None:
        myself, config = live
        myself.property_lists.bulk.append({"n": 0})
        webobj = _post_bulk(
            myself, config, "bulk", [{"index": 0, "blob": "y" * 20_000}]
        )
        assert webobj.response.status_code == 413
        body = json.loads(webobj.response.body)
        assert body["error"] == "list_item_too_large"
        assert body["list"] == "bulk"
        assert myself.property_lists.bulk.to_list() == [{"n": 0}]
