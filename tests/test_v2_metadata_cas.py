"""Phase 9 of the v2 list read cost release (thoughts/plans/2026-08-20-v2-
positional-access-cost.md): metadata writes become a bounded
compare-and-swap retry loop on Phase 8's ``set_if_value_equals``, closing
the read-modify-write window PR #127 flagged and accepted as a known trade.

Covers the phase's New Tests not already pinned by the (Phase-9-updated)
``TestStaleMetadataIsNeverWrittenBack`` class in
``test_property_list_integrity.py``:

- a metadata write whose row changed underneath it retries and merges onto
  the new value
- a stale-cache dispatch keeps ``foreign_format_rows`` at zero (the
  reverted-migration/dispatch-on-fresh-format scenario itself is pinned by
  ``TestStaleMetadataIsNeverWrittenBack.
  test_concurrent_append_does_not_revert_the_format_flip``)
- the CAS retry is bounded and raises ``ListMetadataContentionError``,
  mapped by the properties handler to 503 with ``Retry-After``
- the advisory carve-out's boundary from both sides: a v2 advisory touch
  exhausting CAS still succeeds; a semantic write (v1's length) still raises
- v1 ``append()``/``insert()`` merge a delta onto the fresh stored length
  instead of computing an absolute value from a stale cached one
"""

import json
import logging

import pytest

from actingweb.property_list import ListMetadataContentionError, ListProperty
from tests.test_property_list_integrity import (
    FakePropertyDb,
    _patch_get_property,
    _seed_list,
    _seed_v2_list,
)


@pytest.fixture
def fake_store():
    return {}


def _stored_meta(store, actor_id, name):
    return json.loads(store[(actor_id, f"list:{name}-meta")])


class _ConcurrentWriterPropertyDb(FakePropertyDb):
    """Fails ``set_if_value_equals`` on one specific row a fixed number of
    times, injecting a replacement value into the store first -- simulates
    a concurrent writer completing its own metadata write in the gap
    between this caller's read and its compare-and-swap attempt."""

    def __init__(self, store, contended_name, injected_values):
        super().__init__(store)
        self.contended_name = contended_name
        self.injected_values = list(injected_values)

    def set_if_value_equals(self, actor_id=None, name=None, expected=None, value=None):
        if name == self.contended_name and self.injected_values:
            self.store[(actor_id, name)] = self.injected_values.pop(0)
            return False
        return super().set_if_value_equals(
            actor_id=actor_id, name=name, expected=expected, value=value
        )


class _AlwaysFailsCASPropertyDb(FakePropertyDb):
    """``set_if_value_equals`` on one row always loses -- simulates
    sustained contention that outlasts every retry the caller is willing to
    make. Counts attempts so tests can assert the loop is BOUNDED, not
    merely eventually successful."""

    def __init__(self, store, contended_name):
        super().__init__(store)
        self.contended_name = contended_name
        self.attempts = 0

    def set_if_value_equals(self, actor_id=None, name=None, expected=None, value=None):
        if name == self.contended_name:
            self.attempts += 1
            return False
        return super().set_if_value_equals(
            actor_id=actor_id, name=name, expected=expected, value=value
        )


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """The CAS retry loop backs off with real ``time.sleep`` between
    attempts. These tests deliberately exhaust or race the retry bound, so
    without this they would burn up to ~1.5s (6 attempts) of wall clock
    each for no benefit -- the backoff mechanism itself isn't what's under
    test here."""
    monkeypatch.setattr("actingweb.property_list.time.sleep", lambda *_: None)


class TestMetadataWriteRetriesAndMergesOntoTheNewValue:
    def test_retry_merges_onto_the_row_that_changed_underneath_it(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-cas-merge"
        name = "notes"
        _seed_v2_list(fake_store, actor_id, name, ["a", "b"])
        meta_name = f"list:{name}-meta"

        # A concurrent writer's version of the row: different count_hint
        # and updated_at than what our caller is about to read. The write
        # under test must end up with BOTH this concurrent change and its
        # own change -- overwriting it back to the caller's original view
        # would silently drop the concurrent writer's update.
        concurrent_meta = dict(_stored_meta(fake_store, actor_id, name))
        concurrent_meta["count_hint"] = 41
        concurrent_meta["updated_at"] = "2026-08-20T00:00:00"
        injected = json.dumps(concurrent_meta)

        fake_db = _ConcurrentWriterPropertyDb(fake_store, meta_name, [injected])
        _patch_get_property(monkeypatch, lambda config: fake_db)

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        lst.set_description("mine")

        final = _stored_meta(fake_store, actor_id, name)
        assert final["description"] == "mine"  # our own update landed
        assert final["count_hint"] == 41  # merged onto the concurrent value


class TestStaleDispatchKeepsForeignFormatRowsAtZero:
    def test_stale_cached_instance_append_leaves_no_foreign_format_rows(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-cas-noforeign"
        name = "notes"
        items = ["a", "b", "c"]
        _seed_list(fake_store, actor_id, name, items)
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        retained = ListProperty(actor_id=actor_id, name=name, config=object())
        assert retained.to_list() == items  # caches format 1

        # Migrate underneath the retained instance.
        for i in range(len(items)):
            fake_store.pop((actor_id, f"list:{name}-{i}"), None)
        _seed_v2_list(fake_store, actor_id, name, items)

        retained.append("d")  # dispatched fresh, despite the stale v1 cache

        fresh = ListProperty(actor_id=actor_id, name=name, config=object())
        report = fresh.verify()
        assert report["healthy"] is True
        assert report["foreign_format_rows"] == 0
        assert fresh.to_list() == [*items, "d"]


class TestCASRetryIsBoundedAndRaises:
    def test_sustained_contention_raises_after_a_bounded_number_of_attempts(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-cas-bounded"
        name = "notes"
        _seed_list(fake_store, actor_id, name, ["a"])
        meta_name = f"list:{name}-meta"

        fake_db = _AlwaysFailsCASPropertyDb(fake_store, meta_name)
        _patch_get_property(monkeypatch, lambda config: fake_db)

        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        with pytest.raises(ListMetadataContentionError) as exc_info:
            lst.set_description("will never land")

        assert exc_info.value.list_name == name
        assert exc_info.value.actor_id == actor_id
        # Bounded, not spinning: exactly the module's non-advisory retry
        # count, not "until it eventually gives up".
        from actingweb.property_list import _METADATA_CAS_MAX_ATTEMPTS

        assert fake_db.attempts == _METADATA_CAS_MAX_ATTEMPTS

    def test_properties_handler_maps_contention_to_503_with_retry_after(self):
        from actingweb.handlers.properties import PropertiesHandler

        class FakeResponse:
            def __init__(self):
                self.status = None
                self.status_message = None
                self.headers = {}
                self.body = None

            def set_status(self, code, message=None):
                self.status = code
                self.status_message = message

            def write(self, text):
                self.body = text

        handler = PropertiesHandler.__new__(PropertiesHandler)
        fake_response = FakeResponse()
        handler.response = fake_response  # type: ignore[assignment]
        error = ListMetadataContentionError("notes", "actor-1")

        handler._respond_list_metadata_contended(error)

        assert fake_response.status == 503
        assert fake_response.headers["Retry-After"] == "1"
        assert fake_response.body is not None
        body = json.loads(fake_response.body)
        assert body["error"] == "list_metadata_contended"
        assert body["detail"] == str(error)


class TestAdvisoryCarveOutBoundary:
    def test_v2_advisory_touch_exhausts_cas_but_the_item_still_lands(
        self, monkeypatch, fake_store, caplog
    ):
        actor_id = "actor-cas-advisory"
        name = "notes"
        _seed_v2_list(fake_store, actor_id, name, ["a"])
        meta_name = f"list:{name}-meta"

        fake_db = _AlwaysFailsCASPropertyDb(fake_store, meta_name)
        _patch_get_property(monkeypatch, lambda config: fake_db)

        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        with caplog.at_level(logging.WARNING, logger="actingweb.property_list"):
            lst.append("b")  # must NOT raise -- the item write already committed

        assert lst.to_list() == ["a", "b"]  # stored exactly once
        item_rows = [
            k for k in fake_store if k[0] == actor_id and f"list:{name}-#" in k[1]
        ]
        assert len(item_rows) == 2

        from actingweb.property_list import _METADATA_CAS_ADVISORY_MAX_ATTEMPTS

        assert fake_db.attempts == _METADATA_CAS_ADVISORY_MAX_ATTEMPTS
        assert any(
            "advisory metadata touch" in r.getMessage() for r in caplog.records
        )

    def test_v1_semantic_length_write_still_raises_on_exhaustion(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-cas-semantic"
        name = "notes"
        _seed_list(fake_store, actor_id, name, ["x"])
        meta_name = f"list:{name}-meta"

        fake_db = _AlwaysFailsCASPropertyDb(fake_store, meta_name)
        _patch_get_property(monkeypatch, lambda config: fake_db)

        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        with pytest.raises(ListMetadataContentionError):
            lst.append("y")  # v1's length write is semantic: raises, not warns

        # The item row itself was written before the metadata step raised
        # -- a pre-existing characteristic of the shift/append loop, not
        # something this test is pinning, just confirming the failure mode
        # is "metadata raised", not "item write also failed".
        assert fake_store[(actor_id, f"list:{name}-1")] == json.dumps("y")


class TestV1LengthDeltaNotAbsoluteFromStaleCache:
    def test_append_merges_delta_onto_fresh_length_not_stale_cached_absolute(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-cas-v1delta"
        name = "notes"
        _seed_list(fake_store, actor_id, name, ["a", "b", "c"])
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        retained = ListProperty(actor_id=actor_id, name=name, config=object())
        assert len(retained) == 3  # populates _meta_cache with length=3

        # A concurrent writer for real appended two more items while
        # `retained` was held -- true stored length is now 5, but
        # `retained`'s cache still says 3.
        fake_store[(actor_id, f"list:{name}-3")] = json.dumps("d")
        fake_store[(actor_id, f"list:{name}-4")] = json.dumps("e")
        meta = _stored_meta(fake_store, actor_id, name)
        meta["length"] = 5
        fake_store[(actor_id, f"list:{name}-meta")] = json.dumps(meta)

        retained.append("f")

        # A stale ABSOLUTE computation would write cached_length(3) + 1 =
        # 4, silently reverting the concurrent writer's real growth. The
        # delta merge lands on the fresh stored truth: 5 + 1 = 6.
        assert _stored_meta(fake_store, actor_id, name)["length"] == 6

    def test_insert_merges_delta_onto_fresh_length_not_stale_cached_absolute(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-cas-v1delta-insert"
        name = "notes"
        _seed_list(fake_store, actor_id, name, ["a", "b", "c"])
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        retained = ListProperty(actor_id=actor_id, name=name, config=object())
        assert len(retained) == 3

        fake_store[(actor_id, f"list:{name}-3")] = json.dumps("d")
        fake_store[(actor_id, f"list:{name}-4")] = json.dumps("e")
        meta = _stored_meta(fake_store, actor_id, name)
        meta["length"] = 5
        fake_store[(actor_id, f"list:{name}-meta")] = json.dumps(meta)

        retained.insert(0, "z")

        assert _stored_meta(fake_store, actor_id, name)["length"] == 6
