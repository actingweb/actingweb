"""Phase 5 of the v2 list read cost release (thoughts/plans/2026-08-20-v2-
positional-access-cost.md): an advisory count, so a count stops costing a
whole list.

``get_metadata()["length"]`` under v2 is served from ``count_hint``, an
item count mutations maintain as a side effect instead of counting the
rank-key range on every call. This is a documented, bounded-drift
contract, NOT the v1 disaster returning: the true items are always
resolved from the rank keys regardless of what the hint says, and
``len(list_prop)`` remains an exact count.

Uses the dict-backed ``FakePropertyDb`` fake from
``test_property_list_integrity.py`` (a fresh ``get_property(config)``
handle per operation means a plain ``Mock(side_effect=[...])`` list
exhausts too soon) so drift can be manufactured directly by writing a
wrong ``count_hint`` into the fake store, bypassing ``ListProperty``
entirely -- exactly what a concurrent writer or a pre-3.14 writer that
doesn't know about ``count_hint`` would leave behind.
"""

import json

import pytest

from actingweb.property_list import ListProperty
from tests.test_property_list_integrity import (
    CountingPropertyDb,
    FakePropertyDb,
    _patch_get_property,
    _seed_v2_list,
)


@pytest.fixture
def fake_store():
    return {}


def _meta(fake_store, actor_id, name):
    return json.loads(fake_store[(actor_id, f"list:{name}-meta")])


class TestCountHintTracksMutations:
    def test_matches_len_across_a_mixed_sequence(self, monkeypatch, fake_store):
        actor_id = "actor-hint-mixed"
        name = "mixed"
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        lst.append("a")
        lst.append("b")
        lst.insert(0, "z")  # [z, a, b]
        lst.append("c")  # [z, a, b, c]
        del lst[1]  # [z, b, c]
        lst.pop()  # [z, b]
        lst.append("d")  # [z, b, d]
        lst.remove("b")  # [z, d]

        assert lst.to_list() == ["z", "d"]
        assert lst.get_metadata()["length"] == len(lst) == 2

    def test_setitem_leaves_the_hint_unchanged(self, monkeypatch, fake_store):
        actor_id = "actor-hint-setitem"
        name = "setitem"
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        lst.append("a")
        lst.append("b")

        before = lst.get_metadata()["length"]
        lst[0] = "replaced"
        after = lst.get_metadata()["length"]

        assert before == after == 2
        assert lst.to_list() == ["replaced", "b"]


class TestCountHintDriftIsReportedAndRepaired:
    def test_verify_reports_count_hint_drift_and_compact_repairs_it(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-hint-drift"
        name = "drifted"
        _seed_v2_list(fake_store, actor_id, name, ["a", "b", "c"])
        meta = _meta(fake_store, actor_id, name)
        meta["count_hint"] = 99  # a corrupted/stale hint
        fake_store[(actor_id, f"list:{name}-meta")] = json.dumps(meta)

        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        report = lst.verify()
        assert report["length"] == 3
        assert report["count_hint"] == 99
        assert report["count_hint_drift"] == 96
        assert report["healthy"] is True  # drift is informational, not corruption

        lst.compact()

        fresh = ListProperty(actor_id=actor_id, name=name, config=object())
        assert fresh.get_metadata()["length"] == 3
        assert fresh.verify()["count_hint_drift"] == 0

    def test_corrupted_hint_never_used_to_resolve_a_row(self, monkeypatch, fake_store):
        actor_id = "actor-hint-not-authoritative"
        name = "notauthoritative"
        _seed_v2_list(fake_store, actor_id, name, ["a", "b", "c"])
        meta = _meta(fake_store, actor_id, name)
        meta["count_hint"] = 0  # would misreport an empty list if trusted
        fake_store[(actor_id, f"list:{name}-meta")] = json.dumps(meta)

        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        assert lst.to_list() == ["a", "b", "c"]
        assert lst[0] == "a"
        assert lst[2] == "c"
        assert list(iter(lst)) == ["a", "b", "c"]
        assert len(lst) == 3  # len() always counts, never trusts the hint

        # get_metadata()["length"] is the one place the corrupted hint DOES
        # surface -- that's the documented advisory contract, not a bug.
        assert lst.get_metadata()["length"] == 0


class TestCountHintSelfCorrects:
    def test_a_stale_hint_left_by_a_concurrent_writer_is_restored_by_the_next_mutation(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-hint-concurrent"
        name = "concurrent"
        _seed_v2_list(fake_store, actor_id, name, ["a", "b", "c", "d"])
        meta = _meta(fake_store, actor_id, name)
        # Two concurrent appends both read count_hint=2 and both wrote 3,
        # where the truth (4 items landed) is 4 -- exactly the race the
        # class docstring's drift bound describes.
        meta["count_hint"] = 3
        fake_store[(actor_id, f"list:{name}-meta")] = json.dumps(meta)

        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        removed = lst.pop()  # a rank-counting mutation: forces a fresh read
        assert removed == "d"
        assert lst.get_metadata()["length"] == 3  # restored to the counted truth

    def test_a_pre_314_writer_leaves_drift_the_next_rank_counting_mutation_repairs(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-hint-rolling-deploy"
        name = "rollingdeploy"
        _seed_v2_list(fake_store, actor_id, name, ["a", "b", "c"])
        meta = _meta(fake_store, actor_id, name)
        meta["count_hint"] = 3
        fake_store[(actor_id, f"list:{name}-meta")] = json.dumps(meta)

        # A pre-3.14 writer knows nothing about count_hint: it inserted a
        # v2 item row directly and re-touched metadata WITHOUT the field --
        # _save_metadata()'s merge (updates={}) preserves the stale hint
        # verbatim rather than maintaining it, exactly like a legacy
        # instance would.
        import fractional_indexing as fi

        new_rank = fi.generate_key_between("a2", None)
        fake_store[(actor_id, f"list:{name}-#{new_rank}")] = json.dumps("d")

        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        stale_view = ListProperty(actor_id=actor_id, name=name, config=object())
        assert stale_view.verify()["count_hint_drift"] == -1  # hint(3) - truth(4)

        stale_view.pop()  # the next 3.14 rank-counting mutation repairs it

        fresh = ListProperty(actor_id=actor_id, name=name, config=object())
        assert fresh.get_metadata()["length"] == 3
        assert fresh.verify()["count_hint_drift"] == 0


class TestGetMetadataIssuesNoRangeQuery:
    def test_get_metadata_on_a_v2_list_issues_zero_get_range_calls(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-hint-zero-query"
        name = "zeroquery"
        fake_db = CountingPropertyDb(fake_store)
        _patch_get_property(monkeypatch, lambda config: fake_db)
        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        lst.append("a")
        lst.append("b")

        fresh = ListProperty(actor_id=actor_id, name=name, config=object())
        fake_db.range_call_count = 0
        metadata = fresh.get_metadata()
        assert fake_db.range_call_count == 0
        assert metadata["length"] == 2


class TestNotifiedAppendRegistersDiffWithNoExtraQuery:
    def test_register_diff_adds_no_get_range_call_beyond_appends_own(
        self, monkeypatch, fake_store
    ):
        """One fresh ListProperty per append(), matching real usage --
        property.py mints a new instance per attribute access, so a
        retained warm rank cache across separate calls is NOT the
        mechanism this pins (see TestGetMetadataIssuesNoRangeQuery and
        the class docstring's Phase 9B forward-reference: once append()
        stops holding a rank cache at all, _register_diff() reading
        get_metadata() instead of len() is what keeps this at one call
        instead of two)."""
        from actingweb.interface.property_store import NotifyingListProperty

        actor_id = "actor-hint-notified"
        name = "notified"
        fake_db = CountingPropertyDb(fake_store)
        _patch_get_property(monkeypatch, lambda config: fake_db)

        class FakeActor:
            def __init__(self):
                self.diffs = []

            def register_diffs(self, **kw):
                self.diffs.append(kw)

        fake_actor = FakeActor()

        for expected_index, item in enumerate(["x", "y"]):
            core = ListProperty(actor_id=actor_id, name=name, config=object())
            wrapped = NotifyingListProperty(core, name, fake_actor)  # type: ignore[arg-type]
            fake_db.range_call_count = 0
            wrapped.append(item)
            assert fake_db.range_call_count == 1

            diff = json.loads(fake_actor.diffs[-1]["blob"])
            assert diff["operation"] == "append"
            assert diff["length"] == expected_index + 1
            assert diff["index"] == expected_index


class TestCountHintRegressionCompatibility:
    def test_v2_list_with_no_stored_hint_falls_back_to_counting(
        self, monkeypatch, fake_store
    ):
        """A v2 list written before count_hint existed (this phase's
        _seed_v2_list helper omits it, matching a pre-3.14 list's meta
        row exactly)."""
        actor_id = "actor-hint-no-hint-yet"
        name = "nohintyet"
        _seed_v2_list(fake_store, actor_id, name, ["a", "b"])
        meta = _meta(fake_store, actor_id, name)
        assert "count_hint" not in meta  # sanity on the fixture

        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        assert lst.get_metadata()["length"] == 2  # counted, not guessed

        # append()/insert() merge stored-plus-delta -- with no existing int
        # hint to merge onto, they deliberately leave it absent rather than
        # guessing at one (see _v2_touch_metadata()'s count_delta branch).
        # A RANK-COUNTING mutation (insert/pop/remove/__delitem__/compact)
        # is what establishes the first hint, because it always knows the
        # counted truth outright.
        lst.pop()

        fresh = ListProperty(actor_id=actor_id, name=name, config=object())
        assert fresh.get_metadata()["length"] == 1
        assert _meta(fake_store, actor_id, name)["count_hint"] == 1

    def test_v1_lists_are_untouched(self, monkeypatch, fake_store):
        from tests.test_property_list_integrity import _seed_list

        actor_id = "actor-hint-v1"
        name = "v1list"
        _seed_list(fake_store, actor_id, name, ["a", "b", "c"])

        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        assert lst.get_metadata()["length"] == 3
        assert "count_hint" not in _meta(fake_store, actor_id, name)
