"""Idempotent appends (``ListProperty.append_once``) against the live backends.

Phase 3 of thoughts/plans/2026-10-30-spanned-list-items.md: the first call,
a repeat, a repeat after ``compact()`` moved the item, and a repeat after
the item was deleted, with the key row read directly from the actor's side
partition. The limits are the harness's, explicit so PostgreSQL spans too.
"""

import hashlib
import hmac
import json
import uuid
from collections.abc import Iterator

import pytest

from actingweb.config import Config
from actingweb.db import get_property
from actingweb.property_list import ListProperty
from actingweb.property_list_span import AUX_SUFFIX, key_row_name

LIMITS = {"list_item_span_threshold": 390_000, "list_item_max_bytes": 4 * 2**20}
NAME = "drafts"
KEY = "draft-" + uuid.uuid4().hex


def _config() -> Config:
    return Config(**LIMITS)  # type: ignore[arg-type]


@pytest.fixture
def lst() -> Iterator[ListProperty]:
    prop = ListProperty(f"keyed-{uuid.uuid4().hex}", NAME, _config())
    yield prop
    prop.delete()


def _fresh(lst: ListProperty) -> ListProperty:
    return ListProperty(lst.actor_id, NAME, _config())


def _key_row(lst: ListProperty, key: str = KEY) -> dict[str, str] | None:
    key_hash = hmac.new(lst.actor_id.encode(), key.encode(), hashlib.sha256).hexdigest()
    raw = get_property(Config()).get(
        actor_id=lst.actor_id + AUX_SUFFIX, name=key_row_name(NAME, key_hash)
    )
    return json.loads(raw) if raw is not None else None


class TestAppendOnceLive:
    def test_first_call_then_repeat(self, lst: ListProperty) -> None:
        first = lst.append_once({"title": "a"}, key=KEY)
        assert first.created is True
        row = _key_row(lst)
        assert row is not None and row["rank"] == first.handle.rank
        again = _fresh(lst).append_once({"title": "changed"}, key=KEY)
        assert again.created is False
        assert again.item == {"title": "a"}
        assert again.handle.rank == first.handle.rank
        assert _fresh(lst).to_list() == [{"title": "a"}]
        report = _fresh(lst).verify()
        assert report["key_rows"] == 1
        assert report["dangling_key_rows"] == []
        assert report["duplicate_keyed_items"] == []
        assert report["unkeyed_keyed_items"] == []

    def test_spanned_keyed_item_round_trips(self, lst: ListProperty) -> None:
        item = {"id": "big", "body": "z" * (2**20)}
        first = lst.append_once(item, key=KEY)
        assert first.created is True and first.handle.spanned is True
        again = _fresh(lst).append_once(item, key=KEY)
        assert again.created is False and again.item == item

    def test_repeat_after_compact_repairs_the_hint(self, lst: ListProperty) -> None:
        first = lst.append_once("keyed", key=KEY)
        for i in range(3):
            lst.insert(0, f"front-{i}")
        lst.compact()
        again = _fresh(lst).append_once("keyed", key=KEY)
        assert again.created is False and again.item == "keyed"
        assert again.handle.rank != first.handle.rank
        row = _key_row(lst)
        assert row is not None and row["rank"] == again.handle.rank
        assert _fresh(lst).to_list() == ["front-2", "front-1", "front-0", "keyed"]

    def test_deletion_frees_the_key(self, lst: ListProperty) -> None:
        first = lst.append_once("a", key=KEY)
        assert lst.delete_by_handle(first.handle) is True
        assert _key_row(lst) is None
        again = _fresh(lst).append_once("b", key=KEY)
        assert again.created is True
        assert _fresh(lst).to_list() == ["b"]

    def test_list_delete_removes_key_rows(self, lst: ListProperty) -> None:
        lst.append_once("a", key=KEY)
        lst.delete()
        assert _key_row(lst) is None
