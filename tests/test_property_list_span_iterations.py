"""Regression tests for the 2026-10-31 verification of spanned list items
(thoughts/verifications/2026-10-31-spanned-list-items.md), one class per
finding. Each failed before its fix.
"""

import json
from typing import Any

import pytest

from actingweb.config import Config
from actingweb.db.exceptions import DbError
from actingweb.property_list import ListItemSpanError, ListProperty
from actingweb.property_list_span import parse, span_prefix
from tests.test_property_list_spans import (
    ACTOR,
    AUX,
    NAME,
    OLD_GEN,
    RecordingDb,
    aux_rows,
    big,
    heads,
)


@pytest.fixture
def store() -> dict[Any, Any]:
    return {}


@pytest.fixture
def config() -> Config:
    return Config(
        database="dynamodb", list_item_span_threshold=2_000, list_item_max_bytes=20_000
    )


def _use(monkeypatch: pytest.MonkeyPatch, factory: Any) -> None:
    monkeypatch.setattr("actingweb.property_list.get_property", factory)


@pytest.fixture(autouse=True)
def _fake(monkeypatch: pytest.MonkeyPatch, store: dict[Any, Any]) -> None:
    _use(monkeypatch, lambda config: RecordingDb(store, []))


def _lst(config: Config) -> ListProperty:
    return ListProperty(ACTOR, NAME, config)


class TestH2ConcurrentDeleteIsNotCorruption:
    """A reader that loaded a spanned head while another request deleted the
    item must not report the list corrupted."""

    def _deleting_db(self, store: dict[Any, Any], config: Config) -> type:
        class DeleteOnFirstBodyRead(RecordingDb):
            fired = False

            def get_prefix(
                self,
                actor_id: str | None = None,
                prefix: str | None = None,
                keys_only: bool = False,
                consistent_read: bool = True,
            ) -> dict[str, str]:
                if actor_id == AUX and not DeleteOnFirstBodyRead.fired:
                    DeleteOnFirstBodyRead.fired = True
                    other = ListProperty(ACTOR, NAME, config)
                    h = next(
                        h
                        for h, _ in other.items_with_handles(resolve=False)
                        if h.spanned
                    )
                    assert other.delete_by_handle(h)
                return super().get_prefix(
                    actor_id=actor_id,
                    prefix=prefix,
                    keys_only=keys_only,
                    consistent_read=consistent_read,
                )

        return DeleteOnFirstBodyRead

    def test_whole_list_reads_drop_the_deleted_item(
        self, config: Config, store: dict[Any, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lst = _lst(config)
        lst.extend(["a", big("b"), "c"])
        cls = self._deleting_db(store, config)
        _use(monkeypatch, lambda c: cls(store, []))
        assert lst.to_list() == ["a", "c"]
        cls.fired = False
        lst.append(big("d"))
        assert [i for _, i in lst.items_with_handles()] == ["a", "c"]

    def test_point_read_of_a_deleted_item_is_index_error(
        self, config: Config, store: dict[Any, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lst = _lst(config)
        lst.append(big("b"))
        cls = self._deleting_db(store, config)
        _use(monkeypatch, lambda c: cls(store, []))
        with pytest.raises(IndexError) as exc:
            lst[0]
        assert not isinstance(exc.value, ListItemSpanError)


class _LandsThen(RecordingDb):
    """A head write that commits and then reports failure: ``mode="raise"``
    (a timeout after the write applied) or ``mode="false"`` (an SDK retry of
    a committed conditional write fails its own condition). Once, on the
    first spanned head write of the kind named by ``method``."""

    method = "set_if_value_equals"
    mode = "raise"
    fired = False

    def _spanned_head(self, actor_id: Any, name: Any, value: Any) -> bool:
        return (
            actor_id == ACTOR
            and "-#" in (name or "")
            and isinstance(value, str)
            and '"span"' in value
        )

    def _after(self) -> bool:
        _LandsThen.fired = True
        if _LandsThen.mode == "raise":
            raise DbError("property write", ACTOR)
        return False

    def set_if_value_equals(
        self,
        actor_id: str | None = None,
        name: str | None = None,
        expected: str | None = None,
        value: str | None = None,
    ) -> Any:
        landed = super().set_if_value_equals(
            actor_id=actor_id, name=name, expected=expected, value=value
        )
        if (
            landed
            and not _LandsThen.fired
            and _LandsThen.method == "set_if_value_equals"
            and self._spanned_head(actor_id, name, value)
        ):
            return self._after()
        return landed

    def create_if_not_exists(
        self,
        actor_id: str | None = None,
        name: str | None = None,
        value: str | None = None,
    ) -> bool:
        landed = super().create_if_not_exists(actor_id=actor_id, name=name, value=value)
        if (
            landed
            and not _LandsThen.fired
            and _LandsThen.method == "create_if_not_exists"
            and self._spanned_head(actor_id, name, value)
        ):
            return self._after()
        return landed


class TestH1AmbiguousHeadWriteKeepsTheBodies:
    @pytest.fixture(autouse=True)
    def _ambiguous(
        self, monkeypatch: pytest.MonkeyPatch, store: dict[Any, Any]
    ) -> None:
        _LandsThen.fired = False
        _use(monkeypatch, lambda c: _LandsThen(store, []))

    def _readable(self, config: Config, store: dict[Any, Any]) -> list[Any]:
        return ListProperty(ACTOR, NAME, config).to_list()

    def test_update_by_handle_raise_after_commit(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        _LandsThen.method, _LandsThen.mode = "set_if_value_equals", "raise"
        lst = _lst(config)
        lst.append("small")
        handle, _ = lst.items_with_handles()[0]
        with pytest.raises(DbError):
            lst.update_by_handle(handle, big("b"))
        # The head landed: its bodies must still be there.
        assert self._readable(config, store) == [big("b")]

    def test_update_by_handle_false_after_commit_is_success(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        _LandsThen.method, _LandsThen.mode = "set_if_value_equals", "false"
        lst = _lst(config)
        lst.append("small")
        handle, _ = lst.items_with_handles()[0]
        assert lst.update_by_handle(handle, big("b")) is True
        assert self._readable(config, store) == [big("b")]

    def test_append_false_after_commit_is_one_item(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        _LandsThen.method, _LandsThen.mode = "create_if_not_exists", "false"
        lst = _lst(config)
        lst.append(big("a"))
        assert self._readable(config, store) == [big("a")]
        assert len(heads(store)) == 1

    def test_append_raise_after_commit_keeps_bodies(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        _LandsThen.method, _LandsThen.mode = "create_if_not_exists", "raise"
        lst = _lst(config)
        with pytest.raises(DbError):
            lst.append(big("a"))
        assert self._readable(config, store) == [big("a")]

    def test_extend_raise_after_commit_keeps_the_in_flight_bodies(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        _LandsThen.method, _LandsThen.mode = "create_if_not_exists", "raise"
        lst = _lst(config)
        with pytest.raises(DbError):
            lst.extend([big("a"), big("b")])
        # The first head landed; the second was never written, and only
        # its bodies are gone.
        assert self._readable(config, store) == [big("a")]
        gens = {parse(v).span.gen for v in heads(store).values()}  # type: ignore[union-attr]
        assert {n.split("-$span-")[1][:30] for n in aux_rows(store)} == gens


class TestH3CompactRefusesBeforeWritingAnything:
    def test_unreadable_span_stops_compact_with_no_head_written(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        lst = _lst(config)
        for tag in ("c", "b", "a"):
            lst.insert(0, big(tag))  # ranks below a0: compact moves them all
        # Break the LAST item to be moved, so earlier ones would already
        # have been rewritten if compact wrote as it went.
        pairs = lst._v2_load_full()
        env = parse(pairs[-1][1])
        assert env is not None and env.span is not None
        victim = f"{span_prefix(NAME, env.span.gen)}p0001"
        del store[(AUX, victim)]
        before_heads = dict(heads(store))
        before_aux = set(aux_rows(store))

        with pytest.raises(ListItemSpanError):
            lst.compact()

        assert heads(store) == before_heads  # no duplicate, no move
        assert set(aux_rows(store)) == before_aux  # copies rolled back


class TestV7DeleteSweepsEveryGeneration:
    """Second verification, V7: delete() removes every side-partition row
    of the list, fresh or aged, since nothing can sweep them once the list
    is gone; it assumes writes are quiesced, like an actor delete."""

    def test_fresh_and_aged_generations_both_go(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        from actingweb.property_list_span import new_gen

        lst = _lst(config)
        lst.append(big("a"))
        store[(AUX, f"{span_prefix(NAME, new_gen())}p0000")] = "in flight"
        store[(AUX, f"{span_prefix(NAME, OLD_GEN)}p0000")] = "orphan"
        lst.delete()
        assert aux_rows(store) == {}


MALFORMED = '{"__aw_env": 1, "span": {"gen": "bad"}}'


class TestM2MalformedHeadsCanBeRemoved:
    def _with_malformed(self, config: Config, store: dict[Any, Any]) -> ListProperty:
        lst = _lst(config)
        lst.extend(["a", "victim", "c"])
        name = sorted(heads(store))[1]
        store[(ACTOR, name)] = MALFORMED
        return lst

    def test_handles_are_handed_out_and_delete_by_handle_removes_it(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        from actingweb import UNRESOLVED

        lst = self._with_malformed(config, store)
        pairs = lst.items_with_handles(resolve=False)
        assert [i for _, i in pairs] == ["a", UNRESOLVED, "c"]
        assert lst.delete_by_handle(pairs[1][0])
        assert lst.to_list() == ["a", "c"]

    def test_notifying_delete_by_handle_and_value_scans(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        from unittest import mock

        from actingweb.interface.property_store import NotifyingListProperty

        lst = self._with_malformed(config, store)
        lst.remove("c")  # a scan past the malformed head
        assert lst.index("a") == 0
        wrapped = NotifyingListProperty(lst, NAME, mock.Mock())
        handle = wrapped.items_with_handles(resolve=False)[1][0]
        assert wrapped.delete_by_handle(handle)
        assert lst.to_list() == ["a"]

    def test_sweep_removes_malformed_heads(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        lst = self._with_malformed(config, store)
        report = lst.compact(sweep_span_orphans=True)
        assert report["malformed_heads_removed"] == 1
        assert lst.to_list() == ["a", "c"]
        assert lst.verify()["healthy"] is True


class TestM3IdentityVerifyReportsABrokenSpan:
    def test_verify_with_identity_key_does_not_raise(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        lst = _lst(config)
        lst.extend([{"id": "x"}, big("b")])
        victim = sorted(aux_rows(store))[0]
        del store[(AUX, victim)]
        report = lst.verify(identity_key="id", spans=True)
        assert len(report["broken_spans"]) == 1
        assert report["healthy"] is False
        assert report["identity_checked_count"] == 1


class TestM6ValueScansAfterAThresholdChange:
    def test_item_spanned_under_a_lower_threshold_is_found(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        lst = _lst(config)
        item = big("a", 3_000)  # spans at 2,000
        lst.extend(["x", item])
        raised = Config(
            database="dynamodb",
            list_item_span_threshold=10_000,
            list_item_max_bytes=20_000,
        )
        later = ListProperty(ACTOR, NAME, raised)
        assert later.index(item) == 1
        assert later.count(item) == 1
        later.remove(item)
        assert later.to_list() == ["x"]
        assert aux_rows(store) == {}

    def test_differently_sized_value_reads_no_bodies(
        self, config: Config, store: dict[Any, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lst = _lst(config)
        lst.extend([big("a"), "needle"])
        calls: list[Any] = []
        _use(monkeypatch, lambda c: RecordingDb(store, calls))
        assert lst.index("needle") == 1
        assert not [c for c in calls if c[0] == "get_prefix" and c[1] == AUX]


class TestM7SweepWithoutRebalance:
    def test_sweep_span_orphans_moves_no_head(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        lst = _lst(config)
        for tag in ("c", "b", "a"):
            lst.insert(0, big(tag))  # non-canonical ranks: compact would move all
        store[(AUX, f"{span_prefix(NAME, OLD_GEN)}p0000")] = "orphan"
        before = dict(heads(store))
        report = lst.sweep_span_orphans()
        assert report["orphan_span_gens_removed"] == 1
        assert heads(store) == before  # no rebalance, no copy
        assert lst.to_list() == [big("a"), big("b"), big("c")]

    def test_verify_script_uses_the_sweep_not_compact(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from actingweb.maintenance import verify_property_lists as script

        assert "sweep_span_orphans()" in open(script.__file__).read()
        assert "compact(sweep_span_orphans=True)" not in open(script.__file__).read()


class TestL1LimitsAndPreconditionsBeforeAnyWrite:
    def test_a_ceiling_needing_more_than_9999_parts_is_refused(self) -> None:
        with pytest.raises(ValueError, match="9999"):
            Config(
                database="dynamodb",
                list_item_span_threshold=100,
                list_item_max_bytes=4 * 2**20,
            )

    def test_spanning_write_on_a_dollar_actor_writes_nothing(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        lst = ListProperty("legacy$id", NAME, config)
        with pytest.raises(ValueError, match=r"\$"):
            lst.append(big("a"))
        assert store == {}


class TestL4DigestCatchesSameLengthWrongContent:
    def test_swapped_body_of_the_same_length_is_a_broken_span(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        lst = _lst(config)
        lst.append(big("a"))
        name = sorted(aux_rows(store))[0]
        store[(AUX, name)] = "q" * len(store[(AUX, name)])
        with pytest.raises(ListItemSpanError):
            lst.to_list()

    def test_envelopes_without_a_digest_still_read(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        lst = _lst(config)
        lst.append(big("a"))
        (head_name, head) = next(iter(heads(store).items()))
        obj = json.loads(head)
        del obj["span"]["sha256"]
        store[(ACTOR, head_name)] = json.dumps(obj)
        assert lst.to_list() == [big("a")]


class TestM8AndL4ActorLevelSweep:
    def _wire(
        self,
        monkeypatch: pytest.MonkeyPatch,
        store: dict[Any, Any],
        aux_actor: Any,
        db_cls: type = RecordingDb,
    ) -> Any:
        from unittest import mock

        from actingweb import property as property_module

        class FakeList:
            def fetch(self, actor_id: str | None = None) -> Any:
                return {}

            def delete(self) -> None:
                return None

        monkeypatch.setattr(property_module, "get_property_list", lambda c: FakeList())
        monkeypatch.setattr(
            property_module, "get_property", lambda c: db_cls(store, [])
        )
        monkeypatch.setattr(
            property_module,
            "get_actor",
            lambda c: mock.Mock(get=mock.Mock(return_value=aux_actor)),
        )
        return property_module

    def test_an_actor_named_like_the_side_partition_is_left_alone(
        self,
        config: Config,
        store: dict[Any, Any],
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        property_module = self._wire(
            monkeypatch, store, {"id": AUX, "creator": "someone"}
        )
        store[(AUX, "list:theirs-meta")] = "{}"
        with caplog.at_level("ERROR", logger="actingweb.property"):
            assert property_module.Properties(ACTOR, config).delete()
        assert (AUX, "list:theirs-meta") in store
        assert "an actor with that id exists" in caplog.text

    def test_rows_left_after_the_last_pass_are_logged(
        self,
        config: Config,
        store: dict[Any, Any],
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        class AlwaysWriting(RecordingDb):
            n = 0

            def get_prefix(
                self,
                actor_id: str | None = None,
                prefix: str | None = None,
                keys_only: bool = False,
                consistent_read: bool = True,
            ) -> dict[str, str]:
                rows = super().get_prefix(
                    actor_id=actor_id,
                    prefix=prefix,
                    keys_only=keys_only,
                    consistent_read=consistent_read,
                )
                AlwaysWriting.n += 1
                store[(AUX, f"list:x-$span-{OLD_GEN}-p{AlwaysWriting.n:04d}")] = "w"
                return rows

        property_module = self._wire(monkeypatch, store, None, AlwaysWriting)
        store[(AUX, f"list:x-$span-{OLD_GEN}-p0000")] = "w"
        with caplog.at_level("WARNING", logger="actingweb.property"):
            assert property_module.Properties(ACTOR, config).delete()
        assert "still had rows" in caplog.text


class TestM5FullStateFitsTheDiffRow:
    def test_merged_lists_under_the_threshold_each_still_fit_together(self) -> None:
        from actingweb.property_list import fit_full_state

        cfg = Config(database="dynamodb")  # 390,000
        state = {
            "title": "a scalar",
            "odd": {"list": "not a list diff", "items": ["kept"]},
            **{
                f"l{i}": {
                    "list": f"l{i}",
                    "operation": "extend",
                    "items": ["x" * 150_000],
                }
                for i in range(3)
            },
        }
        out = fit_full_state(state, cfg)
        assert len(json.dumps(out)) <= 390_000
        assert out["title"] == "a scalar"
        assert out["odd"] == state["odd"]
        refs = [k for k in ("l0", "l1", "l2") if out[k].get("spanned")]
        assert refs and all("items" not in out[k] for k in refs)
        kept = [k for k in ("l0", "l1", "l2") if not out[k].get("spanned")]
        assert all(out[k]["items"] == ["x" * 150_000] for k in kept)

    def test_no_threshold_leaves_the_state_alone(self) -> None:
        from actingweb.property_list import fit_full_state

        state = {"l": {"list": "l", "operation": "extend", "items": ["x" * 500_000]}}
        assert fit_full_state(state, Config(database="postgresql")) == state

    def test_a_spanned_list_becomes_a_reference_without_reading_bodies(
        self, config: Config, store: dict[Any, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from actingweb.actor import Actor

        lst = _lst(config)
        lst.extend(["a", big("b")])
        calls: list[Any] = []
        _use(monkeypatch, lambda c: RecordingDb(store, calls))
        actor = Actor(config=config)
        ref, pairs = actor._list_state_reference(NAME, lst)
        assert pairs is None
        assert ref is not None and ref["spanned"] is True
        assert ref["bytes"] == len(json.dumps("a")) + len(json.dumps(big("b")))
        assert not [c for c in calls if c[0] == "get_prefix" and c[1] == AUX]

    def test_a_small_list_is_read_as_before(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        from actingweb.actor import Actor

        lst = _lst(config)
        lst.extend(["a", "b"])
        ref, pairs = Actor(config=config)._list_state_reference(NAME, lst)
        assert ref is None
        assert pairs is not None and [i for _, i in pairs] == ["a", "b"]


class TestV1PreReleaseItemsAreNeverSwept:
    """Second verification, V1: a user item stored before 3.16 that merely
    starts like an envelope is an item, read as such and never removed."""

    def test_it_reads_and_survives_the_sweep(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        lst = _lst(config)
        lst.extend(["a", "b"])
        name = sorted(heads(store))[1]
        legacy = {"__aw_env": "x", "title": "written by 3.14"}
        store[(ACTOR, name)] = json.dumps(legacy)
        assert lst.to_list() == ["a", legacy]
        report = lst.sweep_span_orphans()
        assert report["malformed_heads_removed"] == 0
        assert lst.to_list() == ["a", legacy]
        assert lst.verify()["malformed_heads"] == []


class TestV2ContentMismatchIsFoundAndSwept:
    def test_verify_reports_and_the_sweep_removes_it(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        lst = _lst(config)
        lst.extend(["ok", big("a")])
        name = sorted(aux_rows(store))[0]
        store[(AUX, name)] = "q" * len(store[(AUX, name)])
        with pytest.raises(ListItemSpanError, match="do not match"):
            lst.to_list()
        report = lst.verify(spans=True)
        assert len(report["broken_spans"]) == 1
        assert lst.sweep_span_orphans()["broken_spans_removed"] == 1
        assert lst.to_list() == ["ok"]


class TestV3KnownFailuresDeleteTheirBodies:
    def test_collision_storm_on_append_leaves_no_bodies(
        self, config: Config, store: dict[Any, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class AlwaysCollides(RecordingDb):
            def create_if_not_exists(
                self,
                actor_id: str | None = None,
                name: str | None = None,
                value: str | None = None,
            ) -> bool:
                if actor_id == ACTOR and "-#" in (name or ""):
                    return False
                return super().create_if_not_exists(
                    actor_id=actor_id, name=name, value=value
                )

        lst = _lst(config)
        lst.append("seed")
        _use(monkeypatch, lambda c: AlwaysCollides(store, []))
        with pytest.raises(RuntimeError, match="collisions"):
            lst.append(big("a"))
        assert aux_rows(store) == {}

    def test_a_last_rank_fault_before_any_write_leaves_no_bodies(
        self, config: Config, store: dict[Any, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lst = _lst(config)
        lst.append("seed")

        def boom(self: ListProperty) -> str:
            raise DbError("property read", ACTOR)

        monkeypatch.setattr(ListProperty, "_v2_last_rank", boom)
        with pytest.raises(DbError):
            lst.append(big("a"))
        assert aux_rows(store) == {}

    def test_compact_failure_deletes_the_copies_of_unwritten_items(
        self, config: Config, store: dict[Any, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lst = _lst(config)
        for tag in ("c", "b", "a"):
            lst.insert(0, big(tag))
        before = set(aux_rows(store))
        writes = [0]

        class SecondHeadWriteFails(RecordingDb):
            def set(
                self,
                actor_id: str | None = None,
                name: str | None = None,
                value: str | None = None,
            ) -> bool:
                if actor_id == ACTOR and "-#" in (name or "") and value:
                    writes[0] += 1
                    if writes[0] == 2:
                        return False
                return super().set(actor_id=actor_id, name=name, value=value)

        _use(monkeypatch, lambda c: SecondHeadWriteFails(store, []))
        with pytest.raises(RuntimeError):
            lst.compact()
        # Old bodies plus exactly one copy: the item written before the
        # failure. The failed item's and the unwritten item's copies are gone.
        added = set(aux_rows(store)) - before
        gens = {n.split("-$span-")[1][:30] for n in added}
        assert len(gens) == 1


class TestL1NonAsciiPartCount:
    def test_too_many_non_ascii_parts_is_413_before_any_write(
        self, store: dict[Any, Any]
    ) -> None:
        from actingweb.property_list import ListItemTooLargeError

        # 10-byte parts hold two 4-byte emoji (8 bytes), so 50,000 bytes of
        # emoji need about 6,250 parts while 10 * 9,999 allows 99,990 bytes:
        # use a 15-byte threshold (3 emoji per part = 12 bytes).
        cfg = Config(
            database="dynamodb",
            list_item_span_threshold=15,
            list_item_max_bytes=15 * 9_999,
        )

        class Emoji:
            def __str__(self) -> str:
                return "\U0001f600" * 37_000  # 148,000 bytes, ~12,334 parts

        lst = ListProperty(ACTOR, NAME, cfg)
        with pytest.raises(ListItemTooLargeError, match="body rows"):
            lst.append(Emoji())
        assert store == {}


class TestW2DamagedEnvelopesAreReportedAndTheirBodiesKept:
    """Third verification, W2: a truncated library envelope or one of
    another format is malformed (never a plain item); the sweep keeps both
    the head and the bodies it names, so a repair can recover them."""

    @pytest.mark.parametrize("damage", ["truncate", "format2"])
    def test_reported_not_served_not_swept(
        self, config: Config, store: dict[Any, Any], damage: str
    ) -> None:
        lst = _lst(config)
        lst.extend(["ok", big("a")])
        name = sorted(heads(store))[1]
        head = store[(ACTOR, name)]
        if damage == "truncate":
            store[(ACTOR, name)] = head[: len(head) // 2]
        else:
            store[(ACTOR, name)] = head.replace('"__aw_env": 1', '"__aw_env": 2', 1)
        bodies = dict(aux_rows(store))
        with pytest.raises(ListItemSpanError, match="malformed"):
            lst.to_list()
        assert lst.verify(spans=True)["malformed_heads"]
        report = lst.sweep_span_orphans()
        assert report["malformed_heads_removed"] == 0
        assert report["orphan_span_gens_removed"] == 0
        assert aux_rows(store) == bodies
        assert (ACTOR, name) in store

    def test_a_library_envelope_with_a_bad_field_is_still_removed(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        lst = _lst(config)
        lst.extend(["ok", "x"])
        name = sorted(heads(store))[1]
        store[(ACTOR, name)] = MALFORMED  # marker 1, valid JSON, bad gen
        assert lst.sweep_span_orphans()["malformed_heads_removed"] == 1
        assert lst.to_list() == ["ok"]


class TestW3ReadBackFaultIsAnUnknownOutcome:
    def test_bodies_stay_when_the_read_back_raises(
        self, config: Config, store: dict[Any, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class CommitsThenFalseThenReadFaults(RecordingDb):
            def create_if_not_exists(
                self,
                actor_id: str | None = None,
                name: str | None = None,
                value: str | None = None,
            ) -> bool:
                landed = super().create_if_not_exists(
                    actor_id=actor_id, name=name, value=value
                )
                if (
                    actor_id == ACTOR
                    and "-#" in (name or "")
                    and '"span"' in (value or "")
                ):
                    return False  # an SDK retry of the committed create
                return landed

            def get(self, actor_id: str | None = None, name: str | None = None) -> Any:
                if actor_id == ACTOR and "-#" in (name or ""):
                    raise DbError("property read", actor_id)
                return super().get(actor_id=actor_id, name=name)

        lst = _lst(config)
        lst.append("seed")
        _use(monkeypatch, lambda c: CommitsThenFalseThenReadFaults(store, []))
        with pytest.raises(DbError):
            lst.append(big("a"))
        _use(monkeypatch, lambda c: RecordingDb(store, []))
        # The head landed; its bodies were kept, so it reads whole.
        assert lst.to_list() == ["seed", big("a")]


class TestW8LostPlainCasStaysLost:
    def test_identical_plain_value_from_another_writer_is_not_our_success(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        lst = _lst(config)
        lst.append("x")
        handle, _ = lst.items_with_handles()[0]
        lst[0] = "y"  # another writer: the row no longer holds handle's bytes
        lst[0] = "z"
        other_handle, _ = lst.items_with_handles()[0]
        assert lst.update_by_handle(other_handle, "w")  # row is now "w"
        # Our stale handle loses its CAS although the row holds what we ask.
        assert lst.update_by_handle(handle, "w") is False


class TestW14InFlightMarkIsPerThread:
    def test_another_threads_mark_is_invisible(self, config: Config) -> None:
        import threading

        lst = _lst(config)
        lst._head_write_in_flight = True
        seen: list[bool] = []
        t = threading.Thread(target=lambda: seen.append(lst._head_write_in_flight))
        t.start()
        t.join()
        assert seen == [False]
        assert lst._head_write_in_flight is True


class TestW4SingleListResyncSurvivesDamageAndDeletes:
    def test_a_malformed_head_is_sized_from_its_raw_value(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        from actingweb.actor import Actor

        lst = _lst(config)
        lst.extend(["a", "b"])
        name = sorted(heads(store))[1]
        store[(ACTOR, name)] = MALFORMED
        ref, pairs = Actor(config=config)._list_state_reference(NAME, lst)
        assert ref is None and pairs is not None

    def test_an_item_deleted_mid_resolve_is_dropped(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        from actingweb.actor import Actor

        lst = _lst(config)
        lst.extend(["a", big("b")])
        pairs = lst.items_with_handles(resolve=False)
        assert lst.delete_by_handle(pairs[1][0])  # deleted after the read
        assert Actor._resolve_list_heads(lst, pairs) == ["a"]

    def test_a_spanned_item_resolves(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        from actingweb.actor import Actor

        lst = _lst(config)
        lst.extend(["a", big("b")])
        pairs = lst.items_with_handles(resolve=False)
        assert Actor._resolve_list_heads(lst, pairs) == ["a", big("b")]
