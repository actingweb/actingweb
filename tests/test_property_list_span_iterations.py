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
                self, actor_id=None, prefix=None, keys_only=False, consistent_read=True
            ):  # type: ignore[no-untyped-def]
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

    def set_if_value_equals(self, actor_id=None, name=None, expected=None, value=None):  # type: ignore[no-untyped-def]
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

    def create_if_not_exists(self, actor_id=None, name=None, value=None):  # type: ignore[no-untyped-def]
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


class TestM1DeleteKeepsAFreshUnnamedGeneration:
    def test_in_flight_bodies_survive_delete(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        from actingweb.property_list_span import new_gen

        lst = _lst(config)
        lst.append(big("a"))
        fresh = f"{span_prefix(NAME, new_gen())}p0000"
        aged = f"{span_prefix(NAME, OLD_GEN)}p0000"
        store[(AUX, fresh)] = "an append's bodies, head not written yet"
        store[(AUX, aged)] = "orphan"
        lst.delete()
        assert set(aux_rows(store)) == {fresh}


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
            def fetch(self, actor_id=None):  # type: ignore[no-untyped-def]
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
                self, actor_id=None, prefix=None, keys_only=False, consistent_read=True
            ):  # type: ignore[no-untyped-def]
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
        ref = actor._list_state_reference(NAME, lst)
        assert ref is not None and ref["spanned"] is True
        assert ref["bytes"] == len(json.dumps("a")) + len(json.dumps(big("b")))
        assert not [c for c in calls if c[0] == "get_prefix" and c[1] == AUX]

    def test_a_small_list_is_read_as_before(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        from actingweb.actor import Actor

        lst = _lst(config)
        lst.extend(["a", "b"])
        assert Actor(config=config)._list_state_reference(NAME, lst) is None
