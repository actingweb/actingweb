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
from actingweb.aw_web_request import AWWebObj
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

    def test_over_span_threshold_spans_on_v2(self, store: dict[Any, Any]) -> None:
        lst = ListProperty(ACTOR, "fresh", _small_config())
        item = _item_of(2_001)
        lst.append(item)
        assert lst.to_list() == [item]

    def test_item_of_exactly_the_threshold_is_stored(
        self, store: dict[Any, Any]
    ) -> None:
        lst = ListProperty(ACTOR, "fresh", _small_config())
        item = _item_of(2_000)
        lst.append(item)
        assert lst.to_list() == [item]

    def test_non_ascii_item_measured_as_escaped_json(
        self, store: dict[Any, Any]
    ) -> None:
        _seed_v1(store, "old", ["a"])
        lst = ListProperty(ACTOR, "old", _small_config())
        # Each "é" encodes as "\u00e9", six bytes: 400 of them plus quotes
        # is 2,402 bytes, over the threshold although 400 characters. A v1
        # list cannot span, so it is refused.
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


class TestBulk413WritesNothing:
    """Verification 2026-10-31, M4: an oversized entry anywhere in a bulk
    batch is refused before any entry is written."""

    def test_earlier_entries_are_not_written(self, live: Any) -> None:
        myself, config = live
        myself.property_lists.bulk2.append({"n": 0})
        webobj = _post_bulk(
            myself,
            config,
            "bulk2",
            [{"index": 0, "n": "changed"}, {"index": 1, "blob": "y" * 20_000}],
        )
        assert webobj.response.status_code == 413
        assert myself.property_lists.bulk2.to_list() == [{"n": 0}]


def _www_post(myself: Any, config: Any, path: str, params: dict[str, str]) -> Any:
    from actingweb.handlers.www import WwwHandler

    webobj = AWWebObj(params=params)
    handler = WwwHandler(webobj, config)
    with mock.patch.object(handler, "require_authenticated_actor", return_value=myself):
        handler.post(myself.id, path)
    return webobj


class TestHandlerStatusMappings:
    """Verification 2026-10-31 follow-ups: 409 for a broken span on PUT
    ?index=, the www item actions' 413/409 and visible reasons, an empty
    www update refused, and a malformed head isolated in the metadata GET."""

    def test_put_index_broken_span_is_409(self, live: Any) -> None:
        from actingweb.property_list import ListItemSpanError

        myself, config = live
        myself.property_lists.p409.append("a")
        with mock.patch.object(
            ListProperty,
            "update_by_handle",
            side_effect=ListItemSpanError(
                "p409", "a0", expected_parts=2, found_parts=1
            ),
        ):
            webobj = _run_handler(
                PropertiesHandler,
                myself,
                config,
                "put",
                "p409",
                params={"index": "0"},
                body=json.dumps("b"),
            )
        assert webobj.response.status_code == 409
        assert "--sweep-spans" in json.loads(webobj.response.body)["remedy"]

    def test_www_update_too_large_is_413_with_a_reason(self, live: Any) -> None:
        myself, config = live
        myself.property_lists.w413.append("a")
        webobj = _www_post(
            myself,
            config,
            "properties/w413/items",
            {"action": "update", "item_index": "0", "item_value": "y" * 20_001},
        )
        assert webobj.response.status_code == 413
        assert "list_item_max_bytes" in webobj.response.body
        assert myself.property_lists.w413.to_list() == ["a"]

    def test_www_empty_update_is_refused(self, live: Any) -> None:
        myself, config = live
        myself.property_lists.wempty.append("keep")
        webobj = _www_post(
            myself,
            config,
            "properties/wempty/items",
            {"action": "update", "item_index": "0", "item_value": ""},
        )
        assert webobj.response.status_code == 400
        assert "The item is empty" in webobj.response.body
        assert myself.property_lists.wempty.to_list() == ["keep"]

    def test_www_out_of_range_shows_its_reason(self, live: Any) -> None:
        myself, config = live
        myself.property_lists.wrange.append("a")
        webobj = _www_post(
            myself,
            config,
            "properties/wrange/items",
            {"action": "delete", "item_index": "9"},
        )
        assert webobj.response.status_code == 400
        assert "Index 9 out of range" in webobj.response.body

    def test_metadata_get_isolates_a_malformed_head(self, live: Any) -> None:
        from actingweb.db import get_property

        myself, config = live
        myself.property_lists.good.append("a")
        bad = myself.property_lists.bad
        bad.append("x")
        ((rank, _),) = bad._v2_load_full()
        get_property(config).set(
            actor_id=myself.id,
            name=f"list:bad-#{rank}",
            value='{"__aw_env": 1, "span": {"gen": "nope"}}',
        )
        webobj = AWWebObj(params={"metadata": "true"})
        handler = PropertiesHandler(webobj, config)
        auth_result = mock.Mock(success=True, actor=myself)
        auth_result.auth_obj = mock.Mock(acl={"peerid": ""})
        with (
            mock.patch.object(handler, "authenticate_actor", return_value=auth_result),
            mock.patch.object(handler, "_check_property_permission", return_value=True),
        ):
            handler.get(myself.id, "")
        assert webobj.response.status_code == 200
        lists = json.loads(webobj.response.body)["lists"]
        assert lists["good"]["count"] == 1
        assert lists["bad"]["error"] == "list_corrupted"


def _www_get(myself: Any, config: Any, path: str, params: dict[str, str]) -> Any:
    from actingweb.handlers.www import WwwHandler

    webobj = AWWebObj(params=params)
    handler = WwwHandler(webobj, config)
    with mock.patch.object(handler, "require_authenticated_actor", return_value=myself):
        handler.get(myself.id, path)
    return webobj


class TestWwwListPageAndActions:
    """Second verification, V4-V6, V8, V9, L7, L8: the web UI's list page
    and its item actions."""

    def _seed(self, myself: Any, name: str) -> Any:
        lst = getattr(myself.property_lists, name)
        lst.extend(["a", {"z": 1, "é": "ü"}, "y" * 5_000])  # the last spans
        return lst

    def test_list_page_reads_heads_only_and_keeps_json_order(self, live: Any) -> None:
        from actingweb.property_list import UNRESOLVED

        myself, config = live
        self._seed(myself, "page")
        with mock.patch.object(
            ListProperty, "_read_span", side_effect=AssertionError("body read")
        ):
            webobj = _www_get(myself, config, "properties/page", {})
        values = webobj.response.template_values
        assert values["list_items"][2] is UNRESOLVED
        entries = values["list_entries"]
        assert entries[1]["json"] == '{"z": 1, "é": "ü"}'
        assert entries[2]["spanned"] and entries[2]["json"] is None
        assert entries[2]["bytes"] == 5_002
        assert all(e["rank"] and e["digest"] for e in entries)

    def test_edit_param_loads_one_item_whole(self, live: Any) -> None:
        myself, config = live
        self._seed(myself, "pedit")
        first = _www_get(myself, config, "properties/pedit", {})
        rank = first.response.template_values["list_entries"][2]["rank"]
        webobj = _www_get(myself, config, "properties/pedit", {"edit": rank})
        edit = webobj.response.template_values["edit_entry"]
        assert edit["json"] == json.dumps("y" * 5_000)

    def test_a_stale_page_cannot_act_on_another_item(self, live: Any) -> None:
        myself, config = live
        lst = self._seed(myself, "stale")
        page = _www_get(myself, config, "properties/stale", {})
        entry = page.response.template_values["list_entries"][0]
        lst.insert(0, "inserted by another writer")
        lst[1] = "a changed"  # the item the page showed, now changed
        webobj = _www_post(
            myself,
            config,
            "properties/stale/items",
            {
                "action": "delete",
                "item_rank": entry["rank"],
                "item_digest": entry["digest"],
            },
        )
        assert webobj.response.status_code == 409
        assert "since the page was loaded" in webobj.response.body
        assert len(lst.to_list()) == 4

    def test_rank_and_digest_update_the_shown_item(self, live: Any) -> None:
        myself, config = live
        lst = self._seed(myself, "byrank")
        page = _www_get(myself, config, "properties/byrank", {})
        entry = page.response.template_values["list_entries"][1]
        lst.insert(0, "inserted first")
        webobj = _www_post(
            myself,
            config,
            "properties/byrank/items",
            {
                "action": "update",
                "item_rank": entry["rank"],
                "item_digest": entry["digest"],
                "item_value": '{"z": 2}',
                "item_format": "json",
            },
        )
        assert webobj.response.status_code == 302
        assert lst.to_list()[2] == {"z": 2}

    def test_invalid_json_from_the_edit_form_is_refused(self, live: Any) -> None:
        myself, config = live
        lst = self._seed(myself, "badjson")
        webobj = _www_post(
            myself,
            config,
            "properties/badjson/items",
            {
                "action": "update",
                "item_index": "1",
                "item_value": '{"z": 1',
                "item_format": "json",
            },
        )
        assert webobj.response.status_code == 400
        assert lst.to_list()[1] == {"z": 1, "é": "ü"}

    def test_whitespace_values_are_refused(self, live: Any) -> None:
        myself, config = live
        lst = self._seed(myself, "blank")
        for params in (
            {"action": "add", "item_value": "   "},
            {"action": "update", "item_index": "0", "item_value": "  "},
        ):
            webobj = _www_post(myself, config, "properties/blank/items", params)
            assert webobj.response.status_code == 400
        assert lst.to_list()[0] == "a" and len(lst.to_list()) == 3

    def test_error_page_has_a_back_link_and_unescaped_reason(self, live: Any) -> None:
        myself, config = live
        myself.property_lists.errpage.append("a")
        webobj = _www_post(
            myself,
            config,
            "properties/errpage/items",
            {"action": "add", "item_value": "y" * 20_001},
        )
        assert webobj.response.status_code == 413
        body = webobj.response.body
        assert webobj.response.headers["Content-Type"].startswith("text/html")
        assert "List &#x27;errpage&#x27;" in body  # escaped once, for HTML
        assert "&amp;#x27;" not in body
        assert f'href="/{myself.id}/www/properties/errpage"' in body
        assert 'name="viewport"' in body

    def test_cross_site_post_is_refused(self, live: Any) -> None:
        from actingweb.handlers.www import WwwHandler

        myself, config = live
        myself.property_lists.csrf.append("a")
        webobj = AWWebObj(
            params={"action": "add", "item_value": "x"},
            headers={"Origin": "https://evil.example"},
        )
        handler = WwwHandler(webobj, config)
        with mock.patch.object(
            handler, "require_authenticated_actor", return_value=myself
        ):
            handler.post(myself.id, "properties/csrf/items")
        assert webobj.response.status_code == 403
        assert myself.property_lists.csrf.to_list() == ["a"]

    def test_read_only_list_refuses_writes(self, live: Any) -> None:
        from actingweb.handlers.www import WwwHandler

        myself, config = live
        myself.property_lists.locked.append("a")
        hooks = mock.Mock()
        hooks.execute_property_hooks.return_value = None  # put rejected
        webobj = AWWebObj(params={"action": "add", "item_value": "x"})
        handler = WwwHandler(webobj, config, hooks=hooks)
        with (
            mock.patch.object(
                handler, "require_authenticated_actor", return_value=myself
            ),
            mock.patch.object(
                handler, "_get_actor_interface", return_value=mock.Mock()
            ),
        ):
            handler.post(myself.id, "properties/locked/items")
        assert webobj.response.status_code == 403
        assert myself.property_lists.locked.to_list() == ["a"]

    def test_corrupted_list_page_says_so(self, live: Any) -> None:
        from actingweb.property_list import ListItemSpanError

        myself, config = live
        myself.property_lists.broken.append("a")
        with mock.patch.object(
            ListProperty,
            "items_with_handles",
            side_effect=ListItemSpanError(
                "broken", "a0", expected_parts=2, found_parts=1
            ),
        ):
            webobj = _www_get(myself, config, "properties/broken", {})
        assert "--sweep-spans" in webobj.response.template_values["list_error"]


class TestRestPermissionFailsClosed:
    """The REST property handlers deny (403) when the permission evaluator
    raises, instead of answering with the legacy access table."""

    @pytest.mark.parametrize(
        "handler_name",
        ["PropertiesHandler", "PropertyMetadataHandler", "PropertyListItemsHandler"],
    )
    def test_evaluator_error_denies(self, handler_name: str) -> None:
        from actingweb.handlers import properties as module

        handler = getattr(module, handler_name)(AWWebObj(), Config(database="dynamodb"))
        auth_obj = mock.Mock()
        auth_obj.acl = {"peerid": "peer-1"}
        with mock.patch.object(
            module, "get_permission_evaluator", side_effect=RuntimeError("bug")
        ):
            assert (
                handler._check_property_permission("a1", auth_obj, "notes", "read")
                is False
            )
        auth_obj.check_authorisation.assert_not_called()

    def test_a_database_fault_still_propagates(self) -> None:
        from actingweb.db.exceptions import DbError
        from actingweb.handlers import properties as module

        handler = module.PropertiesHandler(AWWebObj(), Config(database="dynamodb"))
        auth_obj = mock.Mock()
        auth_obj.acl = {"peerid": "peer-1"}
        with mock.patch.object(
            module, "get_permission_evaluator", side_effect=DbError("trust read", "a1")
        ):
            with pytest.raises(DbError):
                handler._check_property_permission("a1", auth_obj, "notes", "read")


class TestWwwBrowserWalkFollowUps:
    """Third browser walk: a string item is edited as text, and a
    whitespace edit names the real problem."""

    def test_string_item_edit_round_trips_as_text(self, live: Any) -> None:
        myself, config = live
        lst = myself.property_lists.textedit
        lst.append("plain words")
        page = _www_get(myself, config, "properties/textedit", {})
        rank = page.response.template_values["list_entries"][0]["rank"]
        edit = _www_get(myself, config, "properties/textedit", {"edit": rank})
        entry = edit.response.template_values["edit_entry"]
        assert entry["text"] == "plain words"
        webobj = _www_post(
            myself,
            config,
            "properties/textedit/items",
            {
                "action": "update",
                "item_rank": entry["rank"],
                "item_digest": entry["digest"],
                "item_value": '{"not": "parsed"}',
                "item_format": "text",
            },
        )
        assert webobj.response.status_code == 302
        assert lst.to_list() == ['{"not": "parsed"}']

    def test_whitespace_edit_says_the_item_is_empty(self, live: Any) -> None:
        myself, config = live
        myself.property_lists.wsedit.append("a")
        webobj = _www_post(
            myself,
            config,
            "properties/wsedit/items",
            {"action": "update", "item_index": "0", "item_value": "   "},
        )
        assert webobj.response.status_code == 400
        assert "The item is empty" in webobj.response.body


def _seed_v1_live(myself: Any, config: Any, name: str, items: list[Any]) -> None:
    """A v1 list written as its rows, on real storage (new lists are v2)."""
    from actingweb.db import get_property

    for i, item in enumerate(items):
        db = get_property(config)
        assert db.set(
            actor_id=myself.id, name=f"list:{name}-{i}", value=json.dumps(item)
        )
    db = get_property(config)
    assert db.set(
        actor_id=myself.id,
        name=f"list:{name}-meta",
        value=json.dumps(
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
        ),
    )


def _www_call(
    myself: Any,
    config: Any,
    method: str,
    path: str,
    params: dict[str, str],
    headers: dict[str, str] | None = None,
    hooks: Any = None,
) -> Any:
    from actingweb.handlers.www import WwwHandler

    webobj = AWWebObj(params=params, headers=headers or {})
    handler = (
        WwwHandler(webobj, config, hooks=hooks) if hooks else WwwHandler(webobj, config)
    )
    with mock.patch.object(handler, "require_authenticated_actor", return_value=myself):
        getattr(handler, method)(myself.id, path)
    return webobj


class TestWwwVerification3FollowUps:
    """Third verification, W1, W5, W6, W9, W10: one cross-site rule for
    every web UI mutation, the base path kept, CRLF text, v1 editing."""

    @pytest.mark.parametrize(
        "headers",
        [
            {"Sec-Fetch-Site": "cross-site"},
            {"Sec-Fetch-Site": "same-site"},
            {"Origin": "https://evil.example"},
            {"Origin": "null"},
            {"Referer": "https://evil.example/page"},
        ],
    )
    def test_cross_site_list_action_is_refused(
        self, live: Any, headers: dict[str, str]
    ) -> None:
        myself, config = live
        myself.property_lists.xs.append("a")
        webobj = _www_call(
            myself,
            config,
            "post",
            "properties/xs/items",
            {"action": "add", "item_value": "x"},
            headers,
        )
        assert webobj.response.status_code == 403
        assert myself.property_lists.xs.to_list() == ["a"]

    @pytest.mark.parametrize(
        "headers",
        [
            {},
            {"Sec-Fetch-Site": "same-origin"},
            {"Sec-Fetch-Site": "none"},
            # Sec-Fetch-Site wins over a mismatching Origin (a proxy that
            # rewrites Host but not the browser's own verdict).
            {"Sec-Fetch-Site": "same-origin", "Origin": "https://other.example"},
            # Host compared case-insensitively, default port filled in.
            {"Origin": "https://DEMO.actingweb.io:443"},
            {"Referer": "https://demo.actingweb.io/x/www"},
        ],
    )
    def test_same_origin_list_action_passes(
        self, live: Any, headers: dict[str, str]
    ) -> None:
        myself, config = live
        assert config.root == "https://demo.actingweb.io/"
        myself.property_lists.so.append("a")
        webobj = _www_call(
            myself,
            config,
            "post",
            "properties/so/items",
            {"action": "add", "item_value": "x"},
            headers,
        )
        assert webobj.response.status_code == 302
        assert myself.property_lists.so.to_list() == ["a", "x"]

    def test_base_path_origin_passes_and_redirects_keep_the_base(
        self, live: Any
    ) -> None:
        myself, config = live
        config.fqdn = "demo.actingweb.io/base"
        config.root = config.proto + config.fqdn + "/"
        myself.property_lists.bp.append("a")
        webobj = _www_call(
            myself,
            config,
            "post",
            "properties/bp/items",
            {"action": "add", "item_value": "x"},
            {"Origin": "https://demo.actingweb.io"},
        )
        assert webobj.response.status_code == 302
        assert webobj.response.redirect == f"/base/{myself.id}/www/properties/bp"
        bad = _www_call(
            myself,
            config,
            "post",
            "properties/bp/items",
            {"action": "frobnicate"},
            {"Origin": "https://demo.actingweb.io"},
        )
        assert bad.response.status_code == 400
        assert f'href="/base/{myself.id}/www/properties/bp"' in bad.response.body

    def test_cross_site_get_delete_is_refused(self, live: Any) -> None:
        myself, config = live
        myself.property.keepme = "v"
        webobj = _www_call(
            myself,
            config,
            "get",
            "properties/keepme",
            {"_method": "DELETE"},
            {"Sec-Fetch-Site": "cross-site"},
        )
        assert webobj.response.status_code == 403
        assert myself.property.keepme == "v"

    def test_cross_site_property_form_is_refused(self, live: Any) -> None:
        myself, config = live
        webobj = _www_call(
            myself,
            config,
            "post",
            "properties",
            {
                "property_name": "planted",
                "property_value": "x",
                "property_type": "simple",
            },
            {"Origin": "https://evil.example"},
        )
        assert webobj.response.status_code == 403
        assert myself.property.planted is None

    def test_redirect_to_stays_inside_the_actors_web_ui(self, live: Any) -> None:
        myself, config = live
        for target, expected in (
            ("https://evil.example/", f"/{myself.id}/www/properties"),
            ("//evil.example/", f"/{myself.id}/www/properties"),
            ("/other-actor/www", f"/{myself.id}/www/properties"),
            (f"/{myself.id}/www/init", f"/{myself.id}/www/init"),
        ):
            webobj = _www_call(
                myself,
                config,
                "post",
                "properties",
                {
                    "property_name": "rt",
                    "property_value": "x",
                    "property_type": "simple",
                    "redirect_to": target,
                },
            )
            assert webobj.response.status_code == 302, target
            assert webobj.response.redirect == expected, target

    def test_text_edit_keeps_line_breaks_as_lf(self, live: Any) -> None:
        myself, config = live
        lst = myself.property_lists.crlf
        lst.append("one")
        rank = _www_get(myself, config, "properties/crlf", {}).response.template_values[
            "list_entries"
        ][0]["rank"]
        webobj = _www_post(
            myself,
            config,
            "properties/crlf/items",
            {
                "action": "update",
                "item_rank": rank,
                "item_value": "one\r\ntwo\r\n",
                "item_format": "text",
            },
        )
        assert webobj.response.status_code == 302
        assert lst.to_list() == ["one\ntwo\n"]

    def test_v1_list_is_edited_by_position_with_a_stale_guard(self, live: Any) -> None:
        myself, config = live
        _seed_v1_live(myself, config, "old", ["a", {"k": 1}])
        lst = myself.property_lists.old
        assert lst.storage_format() == 1
        page = _www_get(myself, config, "properties/old", {"edit_index": "1"})
        values = page.response.template_values
        edit = values["edit_entry"]
        assert edit["index"] == 1 and edit["rank"] is None
        assert edit["json"] == '{"k": 1}'
        stale = _www_post(
            myself,
            config,
            "properties/old/items",
            {
                "action": "update",
                "item_index": "1",
                "item_digest": values["list_entries"][0]["digest"],
                "item_value": '{"k": 2}',
                "item_format": "json",
            },
        )
        assert stale.response.status_code == 409
        assert lst.to_list() == ["a", {"k": 1}]
        ok = _www_post(
            myself,
            config,
            "properties/old/items",
            {
                "action": "update",
                "item_index": "1",
                "item_digest": edit["digest"],
                "item_value": '{"k": 2}',
                "item_format": "json",
            },
        )
        assert ok.response.status_code == 302
        assert lst.to_list() == ["a", {"k": 2}]
        gone = _www_post(
            myself,
            config,
            "properties/old/items",
            {
                "action": "delete",
                "item_index": "0",
                "item_digest": edit["digest"],
            },
        )
        assert gone.response.status_code == 409
        assert lst.to_list() == ["a", {"k": 2}]

    def test_read_only_probe_failure_answers_500_without_writing(
        self, live: Any
    ) -> None:
        myself, config = live
        myself.property_lists.probe.append("a")
        hooks = mock.Mock()
        hooks.execute_property_hooks.side_effect = RuntimeError("hook bug")
        webobj = _www_call(
            myself,
            config,
            "post",
            "properties/probe/items",
            {"action": "add", "item_value": "x"},
            hooks=hooks,
        )
        assert webobj.response.status_code == 500
        assert "Error processing list item" in webobj.response.body
        assert myself.property_lists.probe.to_list() == ["a"]


def test_prefix_read_pages_past_one_megabyte(live: Any) -> None:
    """W12: the span content checks read a generation's body rows with
    ``get_prefix``; a DynamoDB query page stops at 1 MB, so the read must
    follow the continuation key. Four 390,000-byte rows are about 1.5 MB."""
    from actingweb.db import get_property
    from actingweb.property_list_span import AUX_SUFFIX

    myself, config = live
    aux = myself.id + AUX_SUFFIX
    db = get_property(config)
    names = [f"list:paged-$span-g-p{i:04d}" for i in range(4)]
    # The fixture's actor delete sweeps the side partition.
    for i, name in enumerate(names):
        assert db.set(actor_id=aux, name=name, value=str(i) * 390_000)
    rows = get_property(config).get_prefix(actor_id=aux, prefix="list:paged-")
    assert sorted(rows) == names
    assert all(len(v) == 390_000 for v in rows.values())


def test_delete_error_page_does_not_promise_kept_text(live: Any) -> None:
    """Fourth browser walk: a failed delete had no text to keep."""
    myself, config = live
    myself.property_lists.delerr.append("a")
    gone = _www_post(
        myself,
        config,
        "properties/delerr/items",
        {"action": "delete", "item_index": "5"},
    )
    assert gone.response.status_code == 400
    assert "your text is kept" not in gone.response.body
    assert "go to the list" in gone.response.body
    typed = _www_post(
        myself, config, "properties/delerr/items", {"action": "add", "item_value": " "}
    )
    assert "your text is kept" in typed.response.body


class TestWwwVerification4FollowUps:
    """Fourth verification, X2, X7, X8, X9, X13."""

    @pytest.mark.parametrize(
        "headers",
        [{"Sec-Fetch-Site": "none"}, {"Sec-Fetch-Site": "same-site"}],
    )
    def test_get_delete_from_a_mail_link_is_refused(
        self, live: Any, headers: dict[str, str]
    ) -> None:
        myself, config = live
        myself.property.mailed = "v"
        webobj = _www_call(
            myself, config, "get", "properties/mailed", {"_method": "DELETE"}, headers
        )
        assert webobj.response.status_code == 403
        assert myself.property.mailed == "v"

    def test_v1_position_gone_with_a_digest_is_409(self, live: Any) -> None:
        myself, config = live
        _seed_v1_live(myself, config, "short", ["a", "b"])
        page = _www_get(myself, config, "properties/short", {})
        digest = page.response.template_values["list_entries"][1]["digest"]
        del myself.property_lists.short[1]
        for action in ("delete", "update"):
            webobj = _www_post(
                myself,
                config,
                "properties/short/items",
                {
                    "action": action,
                    "item_index": "1",
                    "item_digest": digest,
                    "item_value": "c",
                },
            )
            assert webobj.response.status_code == 409, action
        assert myself.property_lists.short.to_list() == ["a"]

    def test_add_stores_line_breaks_as_lf(self, live: Any) -> None:
        myself, config = live
        webobj = _www_post(
            myself,
            config,
            "properties/addcrlf/items",
            {"action": "add", "item_value": "one\r\ntwo"},
        )
        assert webobj.response.status_code == 302
        assert myself.property_lists.addcrlf.to_list() == ["one\ntwo"]

    @pytest.mark.parametrize(
        "target",
        [
            "/{id}/www/../../other/www/properties",
            "/{id}/www/%2e%2e/%2e%2e/other/www",
            "/{id}/www/./x",
        ],
    )
    def test_redirect_to_refuses_dot_segments(self, live: Any, target: str) -> None:
        myself, config = live
        webobj = _www_call(
            myself,
            config,
            "post",
            "properties",
            {
                "property_name": "dots",
                "property_value": "x",
                "property_type": "simple",
                "redirect_to": target.format(id=myself.id),
            },
        )
        assert webobj.response.status_code == 302
        assert webobj.response.redirect == f"/{myself.id}/www/properties"

    def test_a_non_ascii_edit_index_is_ignored(self, live: Any) -> None:
        myself, config = live
        _seed_v1_live(myself, config, "sup", ["a"])
        page = _www_get(myself, config, "properties/sup", {"edit_index": "²"})
        assert page.response.template_values["edit_entry"] is None


def test_trust_redirects_keep_the_base_path() -> None:
    from actingweb.handlers import trust

    config = Config(database="dynamodb")
    config.root = "https://demo.actingweb.io/base/"
    webobj = AWWebObj(
        params={"_method": "DELETE"}, headers={"Sec-Fetch-Site": "same-origin"}
    )
    handler = trust.TrustPeerHandler(webobj, config)

    def deleted(*_args: Any) -> None:
        handler.response.set_status(204, "Deleted")

    with mock.patch.object(handler, "delete", side_effect=deleted):
        handler.get("a1", "friend", "p1")
    assert webobj.response.status_code == 302
    assert webobj.response.redirect == "/base/a1/www/trust"
