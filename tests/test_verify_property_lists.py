"""``actingweb-verify-property-lists`` and data a later library version
stored: newer-format items are reported on a line of their own and never
repaired (AC-27), and side-partition rows named for a list with no meta row
are reported and kept (AC-45)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from actingweb.maintenance import verify_property_lists as script
from actingweb.property_list import ListProperty
from actingweb.property_list_span import AUX_SUFFIX
from tests.test_property_list_integrity import FakePropertyDb, _FakePropertyList

ACTOR = "actor-verify-newer"
AUX = ACTOR + AUX_SUFFIX


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> dict[Any, Any]:
    fake: dict[Any, Any] = {}
    monkeypatch.setattr(
        "actingweb.property_list.get_property", lambda config: FakePropertyDb(fake)
    )
    monkeypatch.setattr(
        "actingweb.property.get_property_list",
        lambda config: _FakePropertyList(fake),
        raising=False,
    )
    return fake


def _newer_head(store: dict[Any, Any]) -> None:
    lst = ListProperty(actor_id=ACTOR, name="notes", config=object())
    for item in ("a", "b"):
        lst.append(item)
    name = sorted(n for (a, n) in store if a == ACTOR and "-#" in n)[0]
    store[(ACTOR, name)] = json.dumps({"__aw_env": 1, "need": ["future"], "v": "later"})


def test_sweep_and_repair_keep_the_head_and_every_side_row(
    store: dict[Any, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    _newer_head(store)
    store[(AUX, "list:notes-$future-0001")] = "later-version-row"
    before = dict(store)
    newer: list[str] = []
    checked, unhealthy, errored = script.sweep_actor(
        ACTOR,
        object(),
        True,
        script.RateLimiter(0),
        sweep_spans=True,
        newer=newer,
    )
    assert (checked, unhealthy, errored) == (1, 0, 0)
    assert newer == [f"actor={ACTOR} list=notes"]
    assert "NEWER FORMAT" in capsys.readouterr().out
    assert dict(store) == before


def test_side_rows_of_a_list_without_meta_are_reported_not_removed(
    store: dict[Any, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    ListProperty(actor_id=ACTOR, name="kept", config=object()).append("a")
    store[(AUX, "list:gone-$future-0001")] = "later-version-row"
    store[(AUX, "list:gone-$span-0000000000000-0000000000000000-p0000")] = "x"
    before = dict(store)
    script.sweep_actor(ACTOR, object(), False, script.RateLimiter(0), spans=True)
    out = capsys.readouterr().out
    assert "list=gone: 2 side-partition row(s)" in out
    assert "list=kept" not in out
    assert dict(store) == before
