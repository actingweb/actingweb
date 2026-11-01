"""Creator uniqueness on by default: the first-run sequence (both backends).

A fresh deployment starts once (the start creates the tables and stops with
``UniqueCreatorNotReady``), runs ``actingweb-unique-creators enable --apply``
and starts again. The 403 on a held creator at ``POST /`` is pinned by
``test_unique_creator_http.py`` on the same isolated store.
"""

from __future__ import annotations

from typing import Any

import pytest

from actingweb.interface import ActingWebApp, UniqueCreatorNotReady
from actingweb.maintenance import unique_creators

from .conftest import DATABASE_BACKEND

pytestmark = [
    pytest.mark.xdist_group(name="unique_creator"),
    pytest.mark.usefixtures("real_unique_probe"),
]


def _default_app() -> ActingWebApp:
    # No with_unique_creator(): the default is what is under test.
    return ActingWebApp(
        aw_type="urn:actingweb:test:unique_creator_default",
        database=DATABASE_BACKEND,
        fqdn="test.example.com",
    ).with_indexed_properties([])


def test_the_default_is_on() -> None:
    assert _default_app().get_config().unique_creator is True


def test_first_start_refuses_then_enable_makes_the_second_start_pass(
    fresh_store: Any,
) -> None:
    with pytest.raises(UniqueCreatorNotReady) as raised:
        _default_app().check_ready()
    assert "no actors yet" in str(raised.value)
    assert "enable --apply" in str(raised.value)

    assert unique_creators.main(["enable", "--apply"]) == 0

    _default_app().check_ready()


def test_opting_out_needs_no_enable(fresh_store: Any) -> None:
    _default_app().with_unique_creator(False).check_ready()
