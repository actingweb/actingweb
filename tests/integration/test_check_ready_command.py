"""``actingweb-check-ready`` on a real store (AC-11): a fresh store is ready
at first start; once a user actor exists and nothing was enabled, the
uniqueness gate refuses with its fix line. Nothing is written either way."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from actingweb.db import get_actor
from actingweb.maintenance import check_ready, unique_creators

pytestmark = [
    pytest.mark.xdist_group(name="unique_creator"),
    pytest.mark.usefixtures("real_unique_probe"),
]


def test_fresh_and_populated_store(
    fresh_store: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    assert check_ready.main(["--properties", ""]) == 0
    out = capsys.readouterr().out
    assert "creator uniqueness: ready at first start" in out
    # Read only: still not enabled.
    assert unique_creators.missing_enforcement(fresh_store) is not None

    plain = copy.copy(fresh_store)
    plain.unique_creator = False
    assert get_actor(plain).create(
        actor_id="cr1populated", creator="populated@example.com", passphrase="p"
    )
    assert check_ready.main(["--properties", ""]) == 1
    out = capsys.readouterr().out
    assert "creator uniqueness: REFUSED" in out
    assert "actingweb-unique-creators report" in out
