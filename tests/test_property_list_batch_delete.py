"""Phase 12 of the v2 list read cost release (thoughts/plans/2026-08-20-v2-
positional-access-cost.md): whole-list teardown (``clear()``/``delete()``)
stops being a serial per-item delete loop, and ``sweep_foreign_format_rows()``
skips its range query entirely for a list that has never crossed storage
formats.

Uses real DynamoDB Local (no mocked storage for the actor/list machinery),
spying on PynamoDB's ``Connection.batch_write_item`` and the sibling
``DbProperty.get_range`` to count backend calls -- same convention as
``test_v2_cost_library_callers.py``.
"""

import json
import uuid
from unittest import mock

import pytest

from actingweb.db.dynamodb.property import DbProperty


@pytest.fixture(autouse=True)
def _require_dynamodb():
    import os

    if os.getenv("DATABASE_BACKEND", "dynamodb") != "dynamodb":
        pytest.skip("DynamoDB-only test")


@pytest.fixture
def config():
    from actingweb.config import Config

    return Config(database="dynamodb")


@pytest.fixture
def actor_id():
    return f"batchdel-{uuid.uuid4()}"


@pytest.fixture
def myself(config, actor_id):
    from actingweb.actor import Actor

    a = Actor(config=config)
    created = a.create(
        url=f"https://example.com/{actor_id}",
        creator="tester@example.com",
        passphrase="testpass",
        actor_id=actor_id,
    )
    assert created
    yield a
    a.delete()


def _count_batch_write_calls(fn):
    from pynamodb.connection.base import Connection

    calls = []
    orig = Connection.batch_write_item

    def spy(self, *a, **kw):
        calls.append((a, kw))
        return orig(self, *a, **kw)

    with mock.patch.object(Connection, "batch_write_item", spy):
        result = fn()
    return result, calls


def _count_get_range(fn):
    calls = []
    orig = DbProperty.get_range

    def spy(self, *a, **kw):
        calls.append(kw)
        return orig(self, *a, **kw)

    with mock.patch.object(DbProperty, "get_range", spy):
        result = fn()
    return result, calls


class TestClearIssuesBatchedWritesNotSerialDeletes:
    def test_clear_on_60_item_list_issues_3_batch_write_calls_and_ends_empty(
        self, myself, config
    ):
        lst = myself.property_lists.big
        for i in range(60):
            lst.append({"n": i})

        _, calls = _count_batch_write_calls(lambda: lst.clear())

        assert len(calls) == 3  # ceil(60 / 25) == 3
        assert lst.to_list() == []
        assert len(lst) == 0

    def test_delete_on_60_item_list_issues_3_batch_write_calls_and_list_is_gone(
        self, myself, config
    ):
        lst = myself.property_lists.big2
        for i in range(60):
            lst.append({"n": i})

        _, calls = _count_batch_write_calls(lambda: lst.delete())

        assert len(calls) == 3
        assert myself.property_lists.exists("big2") is False


class TestSweepSkipsItsRangeQueryForANeverMigratedList:
    def test_clear_on_a_healthy_v2_list_issues_exactly_one_range_query(
        self, myself, config
    ):
        """Before Phase 12, clear() issued TWO range queries under v2:
        sweep_foreign_format_rows()'s always-empty v1-range check, and
        _v2_item_names_in_range() for the list's own rows. A list that has
        never crossed formats can skip the first entirely."""
        lst = myself.property_lists.neverchanged
        for i in range(5):
            lst.append({"n": i})

        _, calls = _count_get_range(lambda: lst.clear())

        assert len(calls) == 1

    def test_a_brand_new_list_metadata_marks_format_never_changed(
        self, myself, config
    ):
        lst = myself.property_lists.freshlist
        lst.append("a")

        from actingweb.property import get_property

        db = get_property(config)
        raw = db.get(actor_id=myself.id, name="list:freshlist-meta")
        assert raw is not None
        meta = json.loads(raw)
        assert meta["format"] == 2  # sanity: this IS v2
        assert meta["format_ever_changed"] is False


class TestSweepStillRunsAfterAFormatChange:
    def test_migrated_list_clear_still_issues_the_full_sweep(self, myself, config):
        """A list that crossed formats can no longer prove it has no
        residue from metadata alone, so the sweep must still query -- even
        though migrate_to_v2() already cleaned up after itself and there
        is genuinely nothing left to find this time."""
        from actingweb.property import get_property
        from actingweb.property_list import ListProperty

        db = get_property(config)
        for i, item in enumerate(["a", "b", "c"]):
            db.set(
                actor_id=myself.id,
                name=f"list:migrated-{i}",
                value=json.dumps(item),
            )
        db.set(
            actor_id=myself.id,
            name="list:migrated-meta",
            value=json.dumps(
                {
                    "format": 1,
                    "length": 3,
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
        v1_prop = ListProperty(actor_id=myself.id, name="migrated", config=config)
        report = v1_prop.migrate_to_v2()
        assert report["migrated"] is True

        raw_after_migration = db.get(actor_id=myself.id, name="list:migrated-meta")
        assert raw_after_migration is not None
        meta_after_migration = json.loads(raw_after_migration)
        assert meta_after_migration["format_ever_changed"] is True

        lst = myself.property_lists.migrated
        _, calls = _count_get_range(lambda: lst.clear())

        # Not skipped: at least the v1-range check ran (and found nothing,
        # since migrate_to_v2() already swept it) -- this is the
        # conservative "cannot rule it out" path, not the optimisation.
        assert len(calls) >= 1
        assert lst.to_list() == []


class TestUnprocessedItemsAreRetried:
    def test_a_throttled_batch_write_is_retried_and_the_list_still_ends_empty(
        self, myself, config
    ):
        """Simulates DynamoDB reporting one item as UnprocessedItems on the
        first BatchWriteItem call -- PynamoDB's BatchWrite context manager
        (not hand-rolled retry code here) must resend it."""
        from pynamodb.connection.base import Connection
        from pynamodb.constants import DELETE_REQUEST, KEY, UNPROCESSED_ITEMS

        lst = myself.property_lists.throttled
        for i in range(5):
            lst.append({"n": i})

        orig = Connection.batch_write_item
        call_count = {"n": 0}

        def flaky(self, table_name_arg, put_items=None, delete_items=None, **kw):
            call_count["n"] += 1
            if call_count["n"] == 1 and delete_items:
                # Hold back the last delete_item as "unprocessed" on this
                # first call -- real backend still deletes the rest. The
                # held-back key is re-wrapped in DynamoDB's actual
                # UnprocessedItems wire shape (via the same
                # get_item_attribute_map() the real call would use), not a
                # hand-guessed shape -- PynamoDB's retry parser expects
                # exactly this.
                held_back = delete_items[-1]
                orig(
                    self,
                    table_name_arg,
                    put_items=put_items,
                    delete_items=delete_items[:-1],
                    **kw,
                )
                key_map = self.get_item_attribute_map(
                    table_name_arg, held_back, item_key=KEY, pythonic_key=False
                )
                return {
                    UNPROCESSED_ITEMS: {
                        table_name_arg: [{DELETE_REQUEST: key_map}]
                    }
                }
            return orig(
                self,
                table_name_arg,
                put_items=put_items,
                delete_items=delete_items,
                **kw,
            )

        with mock.patch.object(Connection, "batch_write_item", flaky):
            lst.clear()

        assert call_count["n"] == 2  # the flaky first call, then the retry
        assert myself.property_lists.throttled.to_list() == []
