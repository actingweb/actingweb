"""Spanned property-list items, on the dict-backed fake.

Phase 2 of thoughts/plans/2026-10-30-spanned-list-items.md. A low span
threshold (2,000 bytes; ceiling 20,000) makes every path run on small data.
A recording subclass of ``FakePropertyDb`` captures each backend call, so
"issues no body read", "eventually consistent first" and "two re-reads, then
raise" are asserted on the call list, not inferred.
"""

import json
import logging
from typing import Any
from unittest import mock

import pytest

from actingweb import UNRESOLVED
from actingweb.config import Config
from actingweb.db.exceptions import DbError
from actingweb.property_list import (
    ListItemHandle,
    ListItemSpanError,
    ListProperty,
    diff_reference,
)
from actingweb.property_list_span import (
    AUX_SUFFIX,
    parse,
    part_names,
    span_prefix,
    wrap,
)
from tests.test_property_list_integrity import FakePropertyDb

ACTOR = "actorspan"
AUX = ACTOR + AUX_SUFFIX
NAME = "docs"
OLD_GEN = f"{0:013d}-{'0' * 16}"  # minted at the epoch: always aged


class RecordingDb(FakePropertyDb):
    """FakePropertyDb that appends ``(method, actor_id, name_or_prefix,
    consistent)`` for every read to a shared list."""

    def __init__(self, store: dict[Any, Any], calls: list[tuple[Any, ...]]) -> None:
        super().__init__(store)
        self.calls = calls

    def get(self, actor_id: str | None = None, name: str | None = None) -> Any:
        self.calls.append(("get", actor_id, name, True))
        return super().get(actor_id=actor_id, name=name)

    def get_prefix(
        self,
        actor_id: str | None = None,
        prefix: str | None = None,
        keys_only: bool = False,
        consistent_read: bool = True,
    ) -> dict[str, str]:
        self.calls.append(("get_prefix", actor_id, prefix, consistent_read))
        return super().get_prefix(
            actor_id=actor_id,
            prefix=prefix,
            keys_only=keys_only,
            consistent_read=consistent_read,
        )

    def get_range(
        self,
        actor_id: str | None = None,
        lower: str | None = None,
        upper: str | None = None,
        keys_only: bool = False,
        consistent_read: bool = True,
    ) -> dict[str, str]:
        self.calls.append(("get_range", actor_id, lower, consistent_read))
        return super().get_range(
            actor_id=actor_id,
            lower=lower,
            upper=upper,
            keys_only=keys_only,
            consistent_read=consistent_read,
        )


@pytest.fixture
def store() -> dict[Any, Any]:
    return {}


@pytest.fixture
def calls() -> list[tuple[Any, ...]]:
    return []


@pytest.fixture
def config() -> Config:
    return Config(
        database="dynamodb", list_item_span_threshold=2_000, list_item_max_bytes=20_000
    )


@pytest.fixture(autouse=True)
def _fake(
    monkeypatch: pytest.MonkeyPatch,
    store: dict[Any, Any],
    calls: list[tuple[Any, ...]],
) -> None:
    monkeypatch.setattr(
        "actingweb.property_list.get_property",
        lambda config: RecordingDb(store, calls),
    )


def _lst(config: Config, name: str = NAME) -> ListProperty:
    return ListProperty(ACTOR, name, config)


def big(tag: str, size: int = 5_000) -> dict[str, Any]:
    return {"id": tag, "body": tag[0] * size}


def aux_rows(store: dict[Any, Any]) -> dict[str, str]:
    return {name: v for (aid, name), v in store.items() if aid == AUX}


def actor_rows(store: dict[Any, Any]) -> dict[str, str]:
    return {name: v for (aid, name), v in store.items() if aid == ACTOR}


def heads(store: dict[Any, Any], name: str = NAME) -> dict[str, str]:
    prefix = f"list:{name}-#"
    return {n: v for n, v in actor_rows(store).items() if n.startswith(prefix)}


def aux_reads(calls: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    return [c for c in calls if c[0] == "get_prefix" and c[1] == AUX]


class TestRoundTrip:
    def test_spanned_item_reads_back_through_every_reader(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        lst = _lst(config)
        item = big("a")
        lst.append("small")
        lst.append(item)
        assert lst.to_list() == ["small", item]
        assert lst[1] == item
        assert list(lst) == ["small", item]
        assert [i for _, i in lst.items_with_handles()] == ["small", item]
        assert lst.find("id", "a") == item
        assert lst.index(item) == 1
        assert lst.count(item) == 1
        assert lst.slice(1, 2) == [item]

    def test_to_list_from_rows_reads_bodies_eventually_first(
        self, config: Config, store: dict[Any, Any], calls: list[tuple[Any, ...]]
    ) -> None:
        lst = _lst(config)
        lst.append(big("a"))
        dump = actor_rows(store)
        assert not any("$span-" in n for n in dump)
        calls.clear()
        fresh = _lst(config)
        fresh.prime_from_rows(dump)
        assert fresh.to_list_from_rows(dump) == [big("a")]
        reads = aux_reads(calls)
        assert len(reads) == 1
        assert reads[0][3] is False  # the dump's own (eventual) consistency


class TestRowShape:
    def test_head_bodies_and_partitions(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        lst = _lst(config)
        item = big("a")
        lst.append(item)
        (head,) = heads(store).values()
        assert head.startswith('{"__aw_env": 1')
        env = parse(head)
        assert env is not None and env.span is not None
        assert env.span.bytes == len(json.dumps(item))
        assert set(aux_rows(store)) == set(
            part_names(NAME, env.span.gen, env.span.parts)
        )
        assert env.span.parts == 3  # 5,000+ bytes at 2,000 per part
        # The actor's partition holds the head and the meta row, nothing else.
        assert set(actor_rows(store)) == {f"list:{NAME}-meta", *heads(store)}
        assert all(v == head for _, v in lst._v2_load_full())
        assert all(len(v) <= 2_000 for v in aux_rows(store).values())

    def test_v1_shaped_rows_under_the_span_prefix_are_never_bodies(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        # Rows a sibling list could leave under the same prefix, in the side
        # partition itself, with v1's "-{digits}" suffix instead of "-pNNNN".
        sibling = f"{span_prefix(NAME)}1793393684000-0123456789abcdef-1000"
        store[(AUX, sibling)] = "not a body"
        lst = _lst(config)
        lst.append(big("a"))
        report = lst.verify(spans=True)
        assert report["orphan_span_gens"] == 0
        assert report["span_body_rows"] == 3
        lst.delete()
        assert aux_rows(store) == {sibling: "not a body"}

    def test_boundary_exactly_threshold_is_one_row(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        lst = _lst(config)
        at = "x" * 1_998  # 2,000 bytes encoded
        over = "x" * 1_999
        lst.append(at)
        assert aux_rows(store) == {}
        lst.append(over)
        assert len(aux_rows(store)) == 2
        assert lst.to_list() == [at, over]


class TestDeferredResolution:
    def test_items_with_handles_resolve_false(
        self, config: Config, store: dict[Any, Any], calls: list[tuple[Any, ...]]
    ) -> None:
        lst = _lst(config)
        item = big("a")
        lst.extend(["small", item])
        calls.clear()
        pairs = lst.items_with_handles(resolve=False)
        assert pairs[0][1] == "small"
        assert pairs[0][0].spanned is False
        assert pairs[1][1] is UNRESOLVED
        assert pairs[1][0].spanned is True
        assert pairs[1][0].bytes == len(json.dumps(item))
        assert aux_reads(calls) == []

        fresh, got = lst.item_at(pairs[1][0])
        assert got == item
        assert fresh == pairs[1][0]

    def test_to_list_from_rows_resolve_false(
        self, config: Config, store: dict[Any, Any], calls: list[tuple[Any, ...]]
    ) -> None:
        lst = _lst(config)
        lst.extend(["small", big("a")])
        dump = actor_rows(store)
        calls.clear()
        assert lst.to_list_from_rows(dump, resolve=False) == ["small", UNRESOLVED]
        assert aux_reads(calls) == []

    def test_item_at_on_a_gone_rank(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        lst = _lst(config)
        lst.append(big("a"))
        handle, _ = lst.items_with_handles(resolve=False)[0]
        assert lst.delete_by_handle(handle)
        with pytest.raises(IndexError):
            lst.item_at(handle)

    def test_item_at_on_a_reissued_rank(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        lst = _lst(config)
        lst.append(big("a"))
        handle, _ = lst.items_with_handles(resolve=False)[0]
        assert lst.delete_by_handle(handle)
        lst.append(big("b"))  # the trailing rank is reissued
        fresh, got = lst.item_at(handle)
        assert got == big("b")
        assert fresh.rank == handle.rank
        assert fresh.raw_value != handle.raw_value


class TestEnvelopeRefusals:
    def test_reserved_key_refused_before_any_write(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        lst = _lst(config)
        with pytest.raises(ValueError, match="__aw_env"):
            lst.append({"__aw_env": 1})

        class Sneaky:
            def __str__(self) -> str:
                return '{"__aw_env": 1}'

        with pytest.raises(ValueError):
            lst.append(Sneaky())
        assert store == {}

    def test_malformed_head_raises_without_a_body_read(
        self, config: Config, store: dict[Any, Any], calls: list[tuple[Any, ...]]
    ) -> None:
        lst = _lst(config)
        lst.append("x")
        (name,) = heads(store)
        store[(ACTOR, name)] = '{"__aw_env": 1, "span": {"gen": "bad"}}'
        calls.clear()
        with pytest.raises(ListItemSpanError, match="malformed"):
            lst.to_list()
        assert aux_reads(calls) == []
        report = lst.verify()
        assert report["malformed_heads"] and report["healthy"] is False

    def test_migrate_refuses_an_envelope_shaped_v1_item(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        store[(ACTOR, "list:old-0")] = json.dumps({"__aw_env": 1, "v": 2})
        store[(ACTOR, "list:old-meta")] = json.dumps(
            {"length": 1, "item_type": "json", "chunk_size": 1, "version": "1.0"}
        )
        before = dict(store)
        result = _lst(config, "old").migrate_to_v2()
        assert result == {"migrated": False, "reason": "envelope-shaped item"}
        assert store == before

    def test_dollar_in_new_list_name_refused(self, config: Config) -> None:
        with pytest.raises(ValueError, match=r"\$"):
            _lst(config, "a$b").append("x")


class TestCascade:
    def _one(self, config: Config, store: dict[Any, Any], item: Any) -> ListProperty:
        lst = _lst(config)
        lst.append(item)
        return lst

    @pytest.mark.parametrize(
        "old, new",
        [(big("a"), big("b")), (big("a"), "small"), ("small", big("b"))],
        ids=["spanned-spanned", "spanned-plain", "plain-spanned"],
    )
    def test_update_by_handle_leaves_only_the_new_generation(
        self, config: Config, store: dict[Any, Any], old: Any, new: Any
    ) -> None:
        lst = self._one(config, store, old)
        handle, _ = lst.items_with_handles()[0]
        assert lst.update_by_handle(handle, new)
        assert lst.to_list() == [new]
        (head,) = heads(store).values()
        env = parse(head)
        expected = (
            set(part_names(NAME, env.span.gen, env.span.parts))
            if env is not None and env.span is not None
            else set()
        )
        assert set(aux_rows(store)) == expected

    def test_unknown_envelope_field_is_carried_across(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        lst = self._one(config, store, big("a"))
        (name, head) = next(iter(heads(store).items()))
        env = parse(head)
        assert env is not None and env.span is not None
        store[(ACTOR, name)] = wrap(span=env.span, extra={"future": "kept"})
        handle, _ = lst.items_with_handles()[0]
        assert lst.update_by_handle(handle, big("b"))
        new_env = parse(next(iter(heads(store).values())))
        assert new_env is not None and new_env.extra == {"future": "kept"}
        handle, _ = lst.items_with_handles()[0]
        assert lst.update_by_handle(handle, "small")
        small_env = parse(next(iter(heads(store).values())))
        assert small_env is not None
        assert small_env.extra == {"future": "kept"}
        assert small_env.value == "small"
        assert lst.to_list() == ["small"]
        assert aux_rows(store) == {}

    @pytest.mark.parametrize(
        "remove",
        [
            lambda lst: lst.delete_by_handle(lst.items_with_handles()[0][0]),
            lambda lst: lst.pop(0),
            lambda lst: lst.remove(big("a")),
            lambda lst: lst.__delitem__(0),
            lambda lst: lst.__setitem__(0, "small"),
            lambda lst: lst.remove_where("id", "a"),
            lambda lst: lst.update_where("id", "a", "small"),
        ],
        ids=[
            "delete_by_handle",
            "pop",
            "remove",
            "delitem",
            "setitem",
            "remove_where",
            "update_where",
        ],
    )
    def test_removing_the_item_removes_its_bodies(
        self, config: Config, store: dict[Any, Any], remove: Any
    ) -> None:
        lst = self._one(config, store, big("a"))
        assert aux_rows(store)
        remove(lst)
        assert aux_rows(store) == {}

    def test_pop_returns_the_resolved_item(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        lst = self._one(config, store, big("a"))
        assert lst.pop() == big("a")

    def test_clear_and_delete(self, config: Config, store: dict[Any, Any]) -> None:
        lst = _lst(config)
        lst.extend([big("a"), big("b"), "c"])
        key_row = f"list:{NAME}-$key-{'a' * 64}"
        store[(AUX, key_row)] = "{}"
        lst.clear()
        assert aux_rows(store) == {}
        assert lst.to_list() == []
        lst.extend([big("a")])
        store[(AUX, f"{span_prefix(NAME)}{OLD_GEN}-p0000")] = "orphan"
        lst.delete()
        assert aux_rows(store) == {}
        assert actor_rows(store) == {}

    def test_stale_handle_update_writes_no_bodies(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        lst = self._one(config, store, "small")
        handle, _ = lst.items_with_handles()[0]
        lst[0] = "changed"
        assert lst.update_by_handle(handle, big("b")) is False
        assert aux_rows(store) == {}
        assert lst.to_list() == ["changed"]


class TestReaderRaces:
    def test_old_generation_deleted_under_the_reader(
        self,
        config: Config,
        store: dict[Any, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        lst = _lst(config)
        lst.append(big("a"))
        handle, _ = lst.items_with_handles()[0]

        class SwapOnFirstBodyRead(RecordingDb):
            fired = False

            def get_prefix(
                self,
                actor_id: str | None = None,
                prefix: str | None = None,
                keys_only: bool = False,
                consistent_read: bool = True,
            ) -> dict[str, str]:
                if actor_id == AUX and not SwapOnFirstBodyRead.fired:
                    SwapOnFirstBodyRead.fired = True
                    # A concurrent update lands: new head, old gen deleted.
                    _lst(config).update_by_handle(handle, big("b"))
                return super().get_prefix(
                    actor_id=actor_id,
                    prefix=prefix,
                    keys_only=keys_only,
                    consistent_read=consistent_read,
                )

        for consistent in (True, False):
            SwapOnFirstBodyRead.fired = False
            handle, _ = lst.items_with_handles()[0]
            calls: list[Any] = []
            monkeypatch.setattr(
                "actingweb.property_list.get_property",
                lambda config, calls=calls: SwapOnFirstBodyRead(store, calls),
            )
            assert lst.to_list(consistent=consistent) == [big("b")]
            monkeypatch.setattr(
                "actingweb.property_list.get_property",
                lambda config: RecordingDb(store, []),
            )
            # Reset to the original value for the second pass.
            h, _ = lst.items_with_handles()[0]
            lst.update_by_handle(h, big("a"))

    def test_eventually_short_strongly_complete(
        self,
        config: Config,
        store: dict[Any, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        lst = _lst(config)
        lst.append(big("a"))

        class ShortWhenEventual(RecordingDb):
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
                if actor_id == AUX and not consistent_read:
                    rows.pop(sorted(rows)[-1])
                return rows

        calls: list[Any] = []
        monkeypatch.setattr(
            "actingweb.property_list.get_property",
            lambda config: ShortWhenEventual(store, calls),
        )
        assert lst.to_list(consistent=False) == [big("a")]
        reads = aux_reads(calls)
        assert [r[3] for r in reads] == [False, True]
        head_gets = [c for c in calls if c[0] == "get" and "-#" in str(c[2])]
        assert len(head_gets) == 1

    def test_head_with_a_new_generation_every_time_stops_after_two_rereads(
        self,
        config: Config,
        store: dict[Any, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        lst = _lst(config)
        lst.append(big("a"))
        (head_name,) = heads(store)
        counter = [0]

        class ChurningHead(RecordingDb):
            def get(
                self, actor_id: str | None = None, name: str | None = None
            ) -> str | None:
                if name == head_name:
                    self.calls.append(("get", actor_id, name, True))
                    counter[0] += 1
                    gen = f"{counter[0]:013d}-{'f' * 16}"
                    return json.dumps(
                        {"__aw_env": 1, "span": {"gen": gen, "parts": 1, "bytes": 9}}
                    )
                return super().get(actor_id=actor_id, name=name)

            def get_prefix(
                self,
                actor_id: str | None = None,
                prefix: str | None = None,
                keys_only: bool = False,
                consistent_read: bool = True,
            ) -> dict[str, str]:
                self.calls.append(("get_prefix", actor_id, prefix, consistent_read))
                return {}  # every generation is short

        calls: list[Any] = []
        monkeypatch.setattr(
            "actingweb.property_list.get_property",
            lambda config: ChurningHead(store, calls),
        )
        with pytest.raises(ListItemSpanError):
            lst.to_list()
        head_gets = [c for c in calls if c[0] == "get" and c[2] == head_name]
        assert len(head_gets) == 2
        assert len(aux_reads(calls)) == 3


class TestBrokenSpans:
    def test_a_missing_body_row_is_broken_everywhere(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        lst = _lst(config)
        lst.extend(["ok", big("a")])
        victim = sorted(aux_rows(store))[1]
        del store[(AUX, victim)]

        report = lst.verify(spans=True)
        assert len(report["broken_spans"]) == 1
        assert report["healthy"] is False

        with pytest.raises(ListItemSpanError) as exc:
            lst.to_list()
        text = str(exc.value)
        assert NAME in text and "3 body row(s)" in text and "2 matching" in text
        assert "aaaa" not in text
        assert exc.value.remedy.startswith("run actingweb-verify-property-lists")

        swept = lst.compact(sweep_span_orphans=True)
        assert swept["broken_spans_removed"] == 1
        assert lst.to_list() == ["ok"]
        assert aux_rows(store) == {}

    def test_the_409_names_the_span_remedy(self) -> None:
        from actingweb.aw_web_request import AWWebObj
        from actingweb.handlers.properties import _write_list_corrupted_response

        webobj = AWWebObj()
        err = ListItemSpanError(NAME, "a0", expected_parts=3, found_parts=2)
        _write_list_corrupted_response(webobj.response, NAME, err)
        assert webobj.response.status_code == 409
        body = json.loads(webobj.response.body)
        assert body["error"] == "list_corrupted"
        assert body["remedy"] == ListItemSpanError.remedy


class TestOrphansAndVerify:
    def test_verify_without_spans_reads_no_bodies(
        self, config: Config, store: dict[Any, Any], calls: list[tuple[Any, ...]]
    ) -> None:
        lst = _lst(config)
        lst.extend([big("a"), "b"])
        calls.clear()
        report = lst.verify()
        # The only side-partition read is the (small) key-row enumeration.
        assert [c for c in aux_reads(calls) if "$span-" in c[2]] == []
        assert [c[2] for c in aux_reads(calls)] == [f"list:{NAME}-$key-"]
        assert report["spanned_items"] == 1
        assert report["span_bytes"] == len(json.dumps(big("a")))
        assert "orphan_span_gens" not in report

    def test_aged_orphan_swept_fresh_one_kept(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        from actingweb.property_list_span import new_gen

        lst = _lst(config)
        lst.append(big("a"))
        fresh = new_gen()
        store[(AUX, f"{span_prefix(NAME, fresh)}p0000")] = "fresh"
        store[(AUX, f"{span_prefix(NAME, OLD_GEN)}p0000")] = "aged"
        assert lst.verify(spans=True)["orphan_span_gens"] == 2
        report = lst.compact(sweep_span_orphans=True)
        assert report["orphan_span_gens_removed"] == 1
        remaining = aux_rows(store)
        assert f"{span_prefix(NAME, fresh)}p0000" in remaining
        assert f"{span_prefix(NAME, OLD_GEN)}p0000" not in remaining
        assert lst.to_list() == [big("a")]

    def test_identity_verify_resolves_each_spanned_item(
        self, config: Config, store: dict[Any, Any], calls: list[tuple[Any, ...]]
    ) -> None:
        lst = _lst(config)
        lst.extend([big("a"), big("b"), {"id": "c"}])
        calls.clear()
        report = lst.verify(identity_key="id")
        assert report["identity_checked_count"] == 3
        assert len([c for c in aux_reads(calls) if "$span-" in c[2]]) == 2

    def test_small_value_scans_read_no_bodies(
        self, config: Config, store: dict[Any, Any], calls: list[tuple[Any, ...]]
    ) -> None:
        lst = _lst(config)
        lst.extend([big("a"), "needle", big("b")])
        calls.clear()
        assert lst.index("needle") == 1
        assert lst.count("needle") == 1
        lst.remove("needle")
        assert aux_reads(calls) == []
        assert lst.to_list() == [big("a"), big("b")]


class TestCompact:
    def _scattered(self, config: Config) -> ListProperty:
        lst = _lst(config)
        # insert(0, ...) leaves ranks below a0, so compact() moves them.
        for tag in ("c", "b", "a"):
            lst.insert(0, big(tag))
        return lst

    def test_compact_gives_moved_spanned_heads_fresh_generations(
        self, config: Config, store: dict[Any, Any], calls: list[tuple[Any, ...]]
    ) -> None:
        lst = self._scattered(config)
        before = {parse(v).span.gen for v in heads(store).values()}  # type: ignore[union-attr]
        calls.clear()
        lst.compact()
        assert not any(
            c[0] == "get_prefix" and c[2] == span_prefix(NAME) for c in calls
        )
        after = {parse(v).span.gen for v in heads(store).values()}  # type: ignore[union-attr]
        assert before.isdisjoint(after)
        assert lst.to_list() == [big("a"), big("b"), big("c")]
        assert lst.verify(spans=True)["orphan_span_gens"] == 0

    def test_crash_between_write_and_cleanup_leaves_independent_copies(
        self,
        config: Config,
        store: dict[Any, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        lst = self._scattered(config)

        class FailCleanup(RecordingDb):
            def set(
                self,
                actor_id: str | None = None,
                name: str | None = None,
                value: str | None = None,
            ) -> bool:
                if value is None and actor_id == ACTOR and "-#" in (name or ""):
                    raise DbError("property write", actor_id)
                return super().set(actor_id=actor_id, name=name, value=value)

        monkeypatch.setattr(
            "actingweb.property_list.get_property",
            lambda config: FailCleanup(store, []),
        )
        with pytest.raises(DbError):
            lst.compact()
        monkeypatch.setattr(
            "actingweb.property_list.get_property",
            lambda config: RecordingDb(store, []),
        )
        pairs = lst.items_with_handles()
        assert len(pairs) == 6  # every item twice
        first_a = next(h for h, i in pairs if i == big("a"))
        assert lst.delete_by_handle(first_a)
        assert sorted(i["id"] for i in lst.to_list()) == ["a", "b", "b", "c", "c"]

    def test_point_read_race_leaves_an_orphan_never_a_broken_span(
        self,
        config: Config,
        store: dict[Any, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        lst = _lst(config)
        lst.append(big("a"))
        original = ListProperty._read_head_tolerant

        def racing(self: ListProperty, rank: str) -> Any:
            result = original(self, rank)
            other = _lst(config)
            h, _ = other.items_with_handles(resolve=False)[0]
            other.update_by_handle(h, big("z"))
            return result

        monkeypatch.setattr(ListProperty, "_read_head_tolerant", racing)
        lst[0] = big("b")
        monkeypatch.setattr(ListProperty, "_read_head_tolerant", original)
        report = lst.verify(spans=True)
        assert report["broken_spans"] == []
        assert report["orphan_span_gens"] == 1
        assert lst.to_list() == [big("b")]


class TestResidueAndDowngrade:
    def _seed_aux(self, store: dict[Any, Any], name: str) -> None:
        store[(AUX, f"{span_prefix(name, OLD_GEN)}p0000")] = "x"
        store[(AUX, f"list:{name}-$key-{'b' * 64}")] = "{}"

    def test_deleted_list_residue_swept(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        self._seed_aux(store, "gone")
        assert _lst(config, "gone").sweep_foreign_format_rows() == 2
        assert aux_rows(store) == {}

    def test_v1_list_residue_swept(self, config: Config, store: dict[Any, Any]) -> None:
        store[(ACTOR, "list:old-0")] = '"a"'
        store[(ACTOR, "list:old-meta")] = json.dumps({"length": 1})
        self._seed_aux(store, "old")
        assert _lst(config, "old").sweep_foreign_format_rows() == 2
        assert aux_rows(store) == {}

    def test_v2_list_keeps_its_rows(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        lst = _lst(config)
        lst.append(big("a"))
        meta = json.loads(store[(ACTOR, f"list:{NAME}-meta")])
        meta["format_ever_changed"] = True
        store[(ACTOR, f"list:{NAME}-meta")] = json.dumps(meta)
        before = aux_rows(store)
        assert lst.sweep_foreign_format_rows() == 0
        assert aux_rows(store) == before

    def test_downgrade_refuses_a_list_with_a_spanned_item(
        self, config: Config, store: dict[Any, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from actingweb.maintenance.migrate_property_lists import downgrade_to_v1

        lst = _lst(config)
        lst.extend(["a", big("b")])
        before = dict(store)
        monkeypatch.setattr(
            "actingweb.db.get_property", lambda config: RecordingDb(store, [])
        )
        result = downgrade_to_v1(ACTOR, NAME, config)
        assert result == {"downgraded": False, "reason": "envelopes"}
        assert store == before


class TestPartialExtend:
    def test_unlanded_items_lose_their_bodies(
        self,
        config: Config,
        store: dict[Any, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        landed = [0]

        class TwoThenCollide(RecordingDb):
            def create_if_not_exists(
                self,
                actor_id: str | None = None,
                name: str | None = None,
                value: str | None = None,
            ) -> bool:
                if actor_id == ACTOR and "-#" in (name or ""):
                    if landed[0] >= 2:
                        return False
                    landed[0] += 1
                return super().create_if_not_exists(
                    actor_id=actor_id, name=name, value=value
                )

        monkeypatch.setattr(
            "actingweb.property_list.get_property",
            lambda config: TwoThenCollide(store, []),
        )
        lst = _lst(config)
        with pytest.raises(RuntimeError, match="collisions"):
            lst.extend([big("a"), big("b"), big("c"), big("d")])
        monkeypatch.setattr(
            "actingweb.property_list.get_property",
            lambda config: RecordingDb(store, []),
        )
        assert lst.to_list() == [big("a"), big("b")]
        gens = {parse(v).span.gen for v in heads(store).values()}  # type: ignore[union-attr]
        assert {n.split("-$span-")[1][:30] for n in aux_rows(store)} == gens


class TestDiffs:
    def _notifying(self, config: Config) -> tuple[Any, mock.Mock]:
        from actingweb.interface.property_store import NotifyingListProperty

        actor = mock.Mock()
        return NotifyingListProperty(_lst(config), NAME, actor), actor

    @staticmethod
    def _blobs(actor: mock.Mock) -> list[dict[str, Any]]:
        return [
            json.loads(c.kwargs["blob"]) for c in actor.register_diffs.call_args_list
        ]

    def test_spanned_mutations_register_references(self, config: Config) -> None:
        lst, actor = self._notifying(config)
        lst.append(big("a"))
        lst.insert(0, big("b"))
        lst.extend([big("c")])
        handle = next(h for h, _ in lst.items_with_handles(resolve=False) if h.spanned)
        lst.update_by_handle(handle, "small")
        handle = next(h for h, _ in lst.items_with_handles(resolve=False) if h.spanned)
        lst.delete_by_handle(handle)
        blobs = self._blobs(actor)
        assert [b["operation"] for b in blobs] == [
            "append",
            "insert",
            "extend",
            "update",
            "remove",
        ]
        for blob in blobs:
            assert blob["spanned"] is True
            assert blob["bytes"] > 0
            assert not {"item", "old_item", "items", "value"} & set(blob)

    def test_plain_items_carry_their_values(self, config: Config) -> None:
        lst, actor = self._notifying(config)
        lst.append({"spanned": True, "bytes": 5})
        (blob,) = self._blobs(actor)
        assert blob["item"] == {"spanned": True, "bytes": 5}
        assert "spanned" not in blob

    def test_two_300kb_values_become_a_reference_at_the_default_threshold(self) -> None:
        cfg = Config(database="dynamodb")
        diff = {
            "list": NAME,
            "operation": "update",
            "length": 1,
            "item": "x" * 300_000,
            "old_item": "y" * 300_000,
        }
        ref = diff_reference(diff, cfg)
        assert ref["spanned"] is True
        assert ref["bytes"] == 2 * 300_002
        assert len(json.dumps(ref)) < 390_000

    def test_many_small_extend_items_become_one_reference(self, config: Config) -> None:
        lst, actor = self._notifying(config)
        lst.extend([f"item-{i}" for i in range(300)])
        (blob,) = self._blobs(actor)
        assert blob["operation"] == "extend"
        assert blob["spanned"] is True and "items" not in blob

    def test_no_threshold_keeps_values(self) -> None:
        cfg = Config(database="postgresql")
        diff = {"list": NAME, "operation": "append", "item": "x" * 500_000}
        assert diff_reference(diff, cfg) is diff


class TestReceiver:
    def _store(self) -> Any:
        from actingweb.remote_storage import RemotePeerStore

        actor = mock.Mock()
        actor.id = "receiver"
        rps = RemotePeerStore(actor, "peer1", validate_peer_id=False)
        lst = mock.MagicMock()
        rps._list_store = mock.Mock()
        rps._list_store.docs = lst
        return rps, lst

    def test_reference_is_not_applied(self, caplog: pytest.LogCaptureFixture) -> None:
        rps, lst = self._store()
        ref = {
            "list": NAME,
            "operation": "append",
            "length": 1,
            "spanned": True,
            "bytes": 9,
        }
        with caplog.at_level(logging.WARNING, logger="actingweb.remote_storage"):
            result = rps._apply_list_operation(NAME, "append", ref)
        assert result == {"operation": "append", "success": False, "spanned": True}
        assert "out of sync" in caplog.text
        lst.append.assert_not_called()

    def test_a_pre_316_receiver_answers_unknown_operation(self) -> None:
        rps, lst = self._store()
        ref = {
            "list": NAME,
            "operation": "append",
            "length": 1,
            "spanned": True,
            "bytes": 9,
        }
        # A receiver without the spanned check sees no "item" field.
        old = {k: v for k, v in ref.items() if k != "spanned"}
        result = rps._apply_list_operation(NAME, "append", old)
        assert result["error"] == "unknown operation"
        lst.append.assert_not_called()


class TestFullStateFallback:
    def test_full_state_of_a_spanned_list_is_stored_as_a_reference(
        self, config: Config
    ) -> None:
        from actingweb.actor import Actor

        actor = Actor(config=config)
        actor.id = ACTOR
        state = {
            NAME: {"list": NAME, "operation": "extend", "items": [big("a", 400_000)]}
        }
        stored: list[dict[str, Any]] = []

        def store_diff(
            peer_id: str, sub_id: str, seq: int, data: dict[str, Any]
        ) -> str:
            stored.append(data)
            return ""

        trust = mock.Mock()
        trust.get.return_value = {"baseuri": "https://peer.example/p1"}
        caps = mock.Mock()
        caps.supports_resync_callbacks_cached.return_value = False
        with (
            mock.patch("actingweb.trust.Trust", return_value=trust),
            mock.patch(
                "actingweb.peer_capabilities.PeerCapabilities", return_value=caps
            ),
            mock.patch("actingweb.interface.actor_interface.ActorInterface"),
            mock.patch.object(
                actor,
                "_get_full_state_for_subscription",
                side_effect=lambda t, st, keys=None: (
                    keys.add(NAME) if keys is not None else None,
                    state,
                )[1],
            ),
            mock.patch.object(
                actor, "_store_subscription_diff", side_effect=store_diff
            ),
            mock.patch.object(
                actor, "_increment_subscription_sequence", return_value=7
            ),
        ):
            actor._callback_subscription_resync(
                {
                    "peerid": "p1",
                    "subscriptionid": "s1",
                    "target": "properties",
                    "subtarget": NAME,
                    "sequence": 1,
                }
            )
        assert stored, "the fallback never reached the diff store"
        inner = stored[0][NAME]
        assert inner["spanned"] is True
        assert "items" not in inner


class TestActorLevel:
    def test_actor_create_refuses_dollar_and_long_ids(self, config: Config) -> None:
        from actingweb.actor import Actor

        for bad in ("a$b", "x" * 252):
            actor = Actor(config=config)
            actor.handle = mock.Mock()
            with pytest.raises(ValueError):
                actor.create(
                    url="https://x", creator="c@x", passphrase="p", actor_id=bad
                )
            # Refused before any write: the backend handle was never used.
            assert actor.handle.method_calls == []

    def test_properties_delete_sweeps_the_side_partition(
        self, config: Config, store: dict[Any, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from actingweb import property as property_module

        class FakeList:
            def fetch(self, actor_id: str | None = None) -> Any:
                return {}

            def delete(self) -> None:
                for key in [k for k in store if k[0] == ACTOR]:
                    del store[key]

        lst = _lst(config)
        lst.append(big("a"))
        inserts = [1]

        class LateWriter(RecordingDb):
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
                if inserts[0]:
                    # A spanned write lands after this pass's read.
                    inserts[0] -= 1
                    store[(AUX, f"{span_prefix(NAME, OLD_GEN)}p0009")] = "late"
                return rows

        monkeypatch.setattr(property_module, "get_property_list", lambda c: FakeList())
        monkeypatch.setattr(
            property_module,
            "get_actor",
            lambda c: mock.Mock(get=mock.Mock(return_value=None)),
        )
        monkeypatch.setattr(
            property_module, "get_property", lambda c: LateWriter(store, [])
        )
        props = property_module.Properties(ACTOR, config)
        assert props.delete()
        assert store == {}

    def test_properties_delete_stops_after_three_passes(
        self, config: Config, store: dict[Any, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from actingweb import property as property_module

        class FakeList:
            def fetch(self, actor_id: str | None = None) -> Any:
                return {}

            def delete(self) -> None:
                return None

        class AlwaysWriting(RecordingDb):
            n = 0

            def get_prefix(
                self,
                actor_id: str | None = None,
                prefix: str | None = None,
                keys_only: bool = False,
                consistent_read: bool = True,
            ) -> dict[str, str]:
                AlwaysWriting.n += 1
                rows = super().get_prefix(
                    actor_id=actor_id,
                    prefix=prefix,
                    keys_only=keys_only,
                    consistent_read=consistent_read,
                )
                # A writer that never stops: a row lands after every read.
                store[(AUX, f"list:x-$span-{OLD_GEN}-p{AlwaysWriting.n:04d}")] = "w"
                return rows

        monkeypatch.setattr(property_module, "get_property_list", lambda c: FakeList())
        monkeypatch.setattr(
            property_module,
            "get_actor",
            lambda c: mock.Mock(get=mock.Mock(return_value=None)),
        )
        monkeypatch.setattr(
            property_module, "get_property", lambda c: AlwaysWriting(store, [])
        )
        store[(AUX, f"list:x-$span-{OLD_GEN}-p0000")] = "w"
        props = property_module.Properties(ACTOR, config)
        assert props.delete()
        assert AlwaysWriting.n == 4  # three sweep passes, then the leak check
        assert aux_rows(store)  # the documented leak, no raise


class TestNoThreshold:
    def test_postgresql_defaults_never_span(self, store: dict[Any, Any]) -> None:
        lst = ListProperty(ACTOR, NAME, Config(database="postgresql"))
        lst.append("x" * 3_000)
        assert aux_rows(store) == {}
        (head,) = heads(store).values()
        assert parse(head) is None

    def test_v1_lists_never_span(self, config: Config, store: dict[Any, Any]) -> None:
        store[(ACTOR, "list:old-meta")] = json.dumps({"length": 0})
        with pytest.raises(Exception, match="span"):
            _lst(config, "old").append(big("a"))
        assert aux_rows(store) == {}


def test_handle_defaults_are_plain() -> None:
    handle = ListItemHandle(rank="a0", raw_value='"x"')
    assert handle.spanned is False and handle.bytes is None
