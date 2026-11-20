"""Data a later library version stored (4.0 stored-format rule), on both
list kinds: an item whose envelope names a ``need`` this version does not
implement, and a list whose meta ``format`` is not 1 or 2.

Such data is not corruption: it raises ``ListItemNewerFormatError`` (not a
``ListCorruptionError``), and no read, write, repair, sweep or compaction of
this version removes or rewrites any row of it. Deleting the whole list is
the one escape for a newer *item*; a list whose *layout* is newer is not
touched at all. "Nothing changed" is asserted on a snapshot of every row in
both partitions, meta row included.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from actingweb.config import Config
from actingweb.list_core import ListCorruptionError, ListItemNewerFormatError
from actingweb.property_list import ListItemHandle, ListProperty
from tests._attribute_parity import (
    list_class,  # noqa: F401  # pyright: ignore[reportUnusedImport]
)
from tests.test_property_list_spans import (
    ACTOR,
    AUX,
    NAME,
    OLD_GEN,
    RecordingDb,
    heads,
)


@pytest.fixture
def store() -> dict[Any, Any]:
    return {}


@pytest.fixture
def config() -> Config:
    return Config(
        database="dynamodb", list_item_span_threshold=2_000, list_item_max_bytes=20_000
    )


@pytest.fixture(autouse=True)
def _fake(monkeypatch: pytest.MonkeyPatch, store: dict[Any, Any]) -> None:
    calls: list[Any] = []
    monkeypatch.setattr(
        "actingweb.property_list.get_property",
        lambda config: RecordingDb(store, calls),
    )


def _lst(config: Config) -> ListProperty:
    return ListProperty(ACTOR, NAME, config)


def _newer_item(config: Config, store: dict[Any, Any]) -> tuple[str, str]:
    """A list of three items whose middle head a later version rewrote:
    ``need`` names a feature this version lacks, and its ``span`` has a
    shape this version would call malformed. Returns ``(rank, raw)``."""
    lst = _lst(config)
    for item in ("a", "b", "c"):
        lst.append(item)
    name, _ = sorted(heads(store).items())[1]
    raw = json.dumps(
        {
            "__aw_env": 1,
            "need": ["future_span"],
            "span": {"gen": OLD_GEN, "parts": 0, "layout": "v9"},
        }
    )
    store[(ACTOR, name)] = raw
    # A side row this version cannot name, and bodies of an old generation
    # (an orphan by this version's rules) the newer head may own.
    store[(AUX, f"list:{NAME}-$future-0001")] = "later-version-row"
    store[(AUX, f"list:{NAME}-$span-{OLD_GEN}-p0000")] = "x" * 10
    return name.rsplit("-#", 1)[1], raw


def _snapshot(store: dict[Any, Any]) -> dict[Any, Any]:
    return dict(store)


class TestNewerItem:
    def test_reading_raises_and_is_not_corruption(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        _newer_item(config, store)
        with pytest.raises(ListItemNewerFormatError) as raised:
            _lst(config).to_list()
        assert not isinstance(raised.value, ListCorruptionError)
        assert "upgrade" in raised.value.remedy

    def test_writes_by_handle_and_position_change_nothing(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        rank, raw = _newer_item(config, store)
        before = _snapshot(store)
        handle = ListItemHandle(rank=rank, raw_value=raw)
        with pytest.raises(ListItemNewerFormatError):
            _lst(config).delete_by_handle(handle)
        with pytest.raises(ListItemNewerFormatError):
            _lst(config).update_by_handle(handle, "replaced")
        with pytest.raises(ListItemNewerFormatError):
            _lst(config)[1] = "replaced"
        with pytest.raises(ListItemNewerFormatError):
            del _lst(config)[1]
        assert _snapshot(store) == before

    def test_compact_stops_before_its_first_write(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        _newer_item(config, store)
        before = _snapshot(store)
        for sweep in (False, True):
            with pytest.raises(ListItemNewerFormatError):
                _lst(config).compact(sweep_span_orphans=sweep)
        assert _snapshot(store) == before

    def test_sweep_and_repair_keep_the_head_and_every_side_row(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        rank, _ = _newer_item(config, store)
        before = _snapshot(store)
        report = _lst(config).sweep_span_orphans()
        assert report["newer_format_heads"] == [rank]
        assert report["orphan_span_gens_removed"] == 0
        assert _snapshot(store) == before
        verified = _lst(config).verify(spans=True)
        assert verified["newer_format_heads"] == [rank]
        assert _snapshot(store) == before

    def test_the_whole_list_can_be_deleted(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        _newer_item(config, store)
        _lst(config).delete()
        assert not heads(store)
        assert (ACTOR, f"list:{NAME}-meta") not in store
        # A side row this version cannot name is left (AC-28).
        assert store[(AUX, f"list:{NAME}-$future-0001")] == "later-version-row"

    def test_clear_leaves_unrecognised_side_rows(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        _newer_item(config, store)
        _lst(config).clear()
        assert not heads(store)
        assert store[(AUX, f"list:{NAME}-$future-0001")] == "later-version-row"


def test_unrecognised_side_row_names_survive_sweep_clear_and_delete(
    config: Config, store: dict[Any, Any]
) -> None:
    """AC-28 on a list this version wrote whole."""
    lst = _lst(config)
    lst.append("a")
    future = (AUX, f"list:{NAME}-$future-0001")
    store[future] = "later-version-row"
    _lst(config).sweep_span_orphans()
    assert store[future] == "later-version-row"
    _lst(config).clear()
    assert store[future] == "later-version-row"
    _lst(config).append("b")
    _lst(config).delete()
    assert store[future] == "later-version-row"


def test_an_unknown_list_format_is_refused_everywhere(
    config: Config, store: dict[Any, Any]
) -> None:
    """AC-43: a list layout a later version wrote (meta ``format`` 3)."""
    lst = _lst(config)
    lst.append("a")
    meta_key = (ACTOR, f"list:{NAME}-meta")
    meta = json.loads(store[meta_key])
    meta["format"] = 3
    store[meta_key] = json.dumps(meta)
    store[(ACTOR, f"list:{NAME}:0")] = json.dumps("v1-shaped-row")
    before = _snapshot(store)
    operations = [
        lambda: _lst(config).to_list(),
        lambda: _lst(config).append("b"),
        lambda: _lst(config).clear(),
        lambda: _lst(config).delete(),
        lambda: _lst(config).sweep_span_orphans(),
        lambda: _lst(config).compact(),
    ]
    for operation in operations:
        with pytest.raises(ListItemNewerFormatError):
            operation()
    assert _snapshot(store) == before


def test_http_answers_409_with_a_fixed_code() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from actingweb.aw_web_request import AWResponse
    from actingweb.interface import ActingWebApp
    from actingweb.interface.integrations._errors import map_db_error

    error = ListItemNewerFormatError("secret-list-name", "a0")
    response = AWResponse()
    assert map_db_error(response, error)
    assert response.status_code == 409
    body = json.loads(response.body)
    assert body["code"] == "list_item_newer_format"
    assert "secret-list-name" not in str(response.body)

    app = ActingWebApp(
        aw_type="urn:actingweb:test:newer", database="dynamodb", fqdn="t.example"
    )
    fastapi_app = FastAPI()

    # Before the library's routes, whose /{actor_id} would catch it.
    @fastapi_app.get("/consumer")
    def consumer() -> None:  # pyright: ignore[reportUnusedFunction]
        raise ListItemNewerFormatError("secret-list-name")

    app.integrate_fastapi(fastapi_app)

    resp = TestClient(fastapi_app, raise_server_exceptions=False).get("/consumer")
    assert resp.status_code == 409
    assert resp.json()["code"] == "list_item_newer_format"
    assert "secret-list-name" not in resp.text


def test_each_newer_case_names_its_own_remedy() -> None:
    """Iteration 8 (verification issue 7): a newer item points at delete();
    a newer layout, which delete() refuses too, does not."""
    item = ListItemNewerFormatError("notes", "0001")
    layout = ListItemNewerFormatError("notes", detail="list format 3")
    assert "delete()" in item.remedy and "upgrade" in item.remedy
    assert "delete()" not in layout.remedy and "upgrade" in layout.remedy
    assert layout.remedy in str(layout)


def test_a_list_with_a_damaged_meta_row_can_still_be_deleted(
    config: Config, store: dict[Any, Any], request: pytest.FixtureRequest
) -> None:
    """Iteration 9 (verification issue 6): only a newer layout refuses
    delete(); an unparsable meta row is damage, and an attribute list's
    delete() still removes the list whole, as it did before the format
    check. (A property list's delete() dispatches on its meta row and
    refused a damaged one before 4.0 too.)"""
    if request.node.callspec.params["list_class"] == "property":
        pytest.skip("a property list refused a damaged meta row before 4.0")
    lst = _lst(config)
    lst.append("a")
    lst.append("b")
    store[(ACTOR, f"list:{NAME}-meta")] = "{truncated"
    _lst(config).delete()
    assert not [
        key for key in store if key[0] == ACTOR and key[1].startswith(f"list:{NAME}")
    ], sorted(store)
