"""``actingweb-migrate-property-lists``: a list whose layout a later library
version wrote (meta ``format`` 3) is skipped and reported, not migrated,
swept or counted as an error (AC-43)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from actingweb.maintenance.migrate_property_lists import RateLimiter, migrate_actor
from actingweb.property_list import ListProperty
from tests.test_property_list_integrity import FakePropertyDb, _FakePropertyList

ACTOR = "actor-newer-layout"


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


def test_the_command_skips_and_reports_an_unknown_format(
    store: dict[Any, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    ListProperty(actor_id=ACTOR, name="notes", config=object()).append("a")
    meta_key = (ACTOR, "list:notes-meta")
    meta = json.loads(store[meta_key])
    meta["format"] = 3
    store[meta_key] = json.dumps(meta)
    store[(ACTOR, "list:notes-0")] = json.dumps("v1-shaped-row")
    before = dict(store)

    for migrate in (False, True):
        _checked, migrated, errored, refused = migrate_actor(
            ACTOR, object(), migrate=migrate, limiter=RateLimiter(0)
        )
        assert (migrated, errored) == (0, 0)
        assert refused == [(f"{ACTOR}/notes", "stored by a later version")]
    assert "NEWER FORMAT" in capsys.readouterr().out
    assert dict(store) == before
