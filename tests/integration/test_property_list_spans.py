"""Property-list item limits and spanned items against the live backends.

Phase 1 of thoughts/plans/2026-10-30-spanned-list-items.md adds the
PostgreSQL defaults check here; Phase 2 adds the span round trips.
"""

import json
import os
import uuid
from collections.abc import Iterator

import pytest

from actingweb.config import Config
from actingweb.db import get_property
from actingweb.property_list import ListProperty


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
