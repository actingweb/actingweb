"""Creator uniqueness on by default: the first-run sequence (both backends).

A fresh deployment (no user actors) enables enforcement at its first start
(4.0; before, it stopped until ``actingweb-unique-creators enable --apply``
ran). The 403 on a held creator at ``POST /`` is pinned by
``test_unique_creator_http.py`` on the same isolated store.
"""

from __future__ import annotations

from typing import Any

import pytest

from actingweb.interface import ActingWebApp
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


def test_the_first_start_on_an_empty_store_passes(fresh_store: Any) -> None:
    """4.0: the store has no user actors, so the start enables enforcement
    itself (AWS_DB_PREFIX is set on the isolated store)."""
    _default_app().check_ready()
    assert unique_creators.missing_enforcement(fresh_store) is None
    _default_app().check_ready()


def test_opting_out_needs_no_enable(fresh_store: Any) -> None:
    _default_app().with_unique_creator(False).check_ready()
