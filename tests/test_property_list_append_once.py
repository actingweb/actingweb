"""Idempotent appends (``ListProperty.append_once``), on the dict-backed fake.

Phase 3 of thoughts/plans/2026-10-30-spanned-list-items.md. A low span
threshold (2,000 bytes; ceiling 20,000) makes the spanned cases run on small
data. ``HookDb`` records every backend call and lets a test run code just
before a key-row create (another writer landing in the window), make one
create write and then answer ``False`` (an SDK retry of a write that landed),
or fault a delete -- so each branch of the protocol is reached on purpose,
with no clock and no sleep.
"""

import hashlib
import hmac
import json
import logging
from collections.abc import Callable
from typing import Any
from unittest import mock

import pytest

from actingweb import AppendOnceResult
from actingweb.config import Config
from actingweb.db.exceptions import DbError
from actingweb.property_list import ListItemTooLargeError, ListProperty
from actingweb.property_list_span import AUX_SUFFIX, key_row_name, new_gen, parse, wrap
from tests.test_property_list_integrity import FakePropertyDb

ACTOR = "actorkeyed"
AUX = ACTOR + AUX_SUFFIX
NAME = "docs"
KEY = "client-minted-0f3c9a1e-7d2b-4c55-9e61-2a8f4b7c1d90"


class Ctl:
    """Shared controls and the call log for every ``HookDb`` instance."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any, Any]] = []
        # Called (once per key-row create) just before it runs.
        self.before_key_create: Callable[[], None] | None = None
        # Name substrings whose next create_if_not_exists writes, then
        # answers False (once each).
        self.ambiguous_create: set[str] = set()
        # Name substrings whose delete_if_value_equals raises DbError.
        self.fail_delete: set[str] = set()
        # Name substrings whose create_if_not_exists raises DbError.
        self.fail_create: set[str] = set()
        # Name substrings whose set_if_value_equals raises DbError.
        self.fail_cas: set[str] = set()
        # Called (once) just before the next prefix read of key rows.
        self.before_key_prefix: Callable[[], None] | None = None


class HookDb(FakePropertyDb):
    def __init__(self, store: dict[Any, Any], ctl: Ctl) -> None:
        super().__init__(store)
        self.ctl = ctl

    def get(self, actor_id: Any = None, name: Any = None) -> Any:
        self.ctl.calls.append(("get", actor_id, name))
        return super().get(actor_id=actor_id, name=name)

    def get_range(
        self,
        actor_id: Any = None,
        lower: Any = None,
        upper: Any = None,
        keys_only: bool = False,
        consistent_read: bool = True,
    ) -> dict[str, str]:
        self.ctl.calls.append(("get_range", actor_id, lower))
        return super().get_range(
            actor_id=actor_id,
            lower=lower,
            upper=upper,
            keys_only=keys_only,
            consistent_read=consistent_read,
        )

    def get_prefix(
        self,
        actor_id: Any = None,
        prefix: Any = None,
        keys_only: bool = False,
        consistent_read: bool = True,
    ) -> dict[str, str]:
        self.ctl.calls.append(("get_prefix", actor_id, prefix))
        if "-$key-" in prefix and self.ctl.before_key_prefix is not None:
            hook, self.ctl.before_key_prefix = self.ctl.before_key_prefix, None
            hook()
        return super().get_prefix(
            actor_id=actor_id,
            prefix=prefix,
            keys_only=keys_only,
            consistent_read=consistent_read,
        )

    def create_if_not_exists(
        self, actor_id: Any = None, name: Any = None, value: Any = None
    ) -> bool:
        self.ctl.calls.append(("create", actor_id, name))
        if "-$key-" in name and self.ctl.before_key_create is not None:
            self.ctl.before_key_create()
        for marker in list(self.ctl.fail_create):
            if marker in name:
                raise DbError("property write", actor_id)
        for marker in list(self.ctl.ambiguous_create):
            if marker in name:
                self.ctl.ambiguous_create.discard(marker)
                super().create_if_not_exists(actor_id=actor_id, name=name, value=value)
                return False
        return super().create_if_not_exists(actor_id=actor_id, name=name, value=value)

    def set_if_value_equals(
        self,
        actor_id: Any = None,
        name: Any = None,
        expected: Any = None,
        value: Any = None,
    ) -> bool:
        self.ctl.calls.append(("cas", actor_id, name))
        for marker in self.ctl.fail_cas:
            if marker in name:
                raise DbError("property write", actor_id)
        return super().set_if_value_equals(
            actor_id=actor_id, name=name, expected=expected, value=value
        )

    def delete_if_value_equals(
        self, actor_id: Any = None, name: Any = None, value: Any = None
    ) -> bool:
        self.ctl.calls.append(("delete_if", actor_id, name))
        for marker in self.ctl.fail_delete:
            if marker in name:
                raise DbError("property write", actor_id)
        return super().delete_if_value_equals(actor_id=actor_id, name=name, value=value)


@pytest.fixture
def store() -> dict[Any, Any]:
    return {}


@pytest.fixture
def ctl() -> Ctl:
    return Ctl()


@pytest.fixture
def config() -> Config:
    return Config(
        database="dynamodb", list_item_span_threshold=2_000, list_item_max_bytes=20_000
    )


@pytest.fixture(autouse=True)
def _fake(monkeypatch: pytest.MonkeyPatch, store: dict[Any, Any], ctl: Ctl) -> None:
    monkeypatch.setattr(
        "actingweb.property_list.get_property", lambda config: HookDb(store, ctl)
    )


@pytest.fixture
def aged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every writer token counts as old: verify(), compact() and
    repair_keys() treat what the test wrote as finished, not in flight."""
    monkeypatch.setattr("actingweb.property_list._KEYED_IN_FLIGHT_SECONDS", 0)


OLD_TOK = "1700000000000-" + "f" * 16  # minted 2023: never in flight


def _lst(config: Config, actor: str = ACTOR) -> ListProperty:
    return ListProperty(actor, NAME, config)


def _hash(key: str = KEY, actor: str = ACTOR) -> str:
    return hmac.new(actor.encode(), key.encode(), hashlib.sha256).hexdigest()


def big(tag: str, size: int = 5_000) -> dict[str, Any]:
    return {"id": tag, "body": tag[0] * size}


def heads(store: dict[Any, Any]) -> dict[str, str]:
    prefix = f"list:{NAME}-#"
    return {n: v for (a, n), v in store.items() if a == ACTOR and n.startswith(prefix)}


def key_rows(store: dict[Any, Any]) -> dict[str, str]:
    return {n: v for (a, n), v in store.items() if a == AUX and "-$key-" in n}


def span_rows(store: dict[Any, Any]) -> dict[str, str]:
    return {n: v for (a, n), v in store.items() if a == AUX and "-$span-" in n}


def key_row(store: dict[Any, Any], key: str = KEY) -> dict[str, Any]:
    return json.loads(store[(AUX, key_row_name(NAME, _hash(key)))])


def plant_winner(
    store: dict[Any, Any], rank: str, value: Any, tok: str = "1700000000000-" + "f" * 16
) -> str:
    """Another writer's head and key row, as if it won the key race."""
    head = wrap(value=value, key=_hash(), tok=tok)
    store[(ACTOR, f"list:{NAME}-#{rank}")] = head
    store[(AUX, key_row_name(NAME, _hash()))] = json.dumps({"rank": rank, "tok": tok})
    return head


class TestFirstCallAndRepeat:
    def test_first_call_creates_and_stores_only_the_hash(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        lst = _lst(config)
        result = lst.append_once({"title": "a"}, key=KEY)
        assert isinstance(result, AppendOnceResult)
        assert result.created is True
        assert result.item == {"title": "a"}
        assert result.handle.key_hash == _hash()
        assert lst.to_list() == [{"title": "a"}]
        ((handle, item),) = lst.items_with_handles()
        assert item == {"title": "a"}
        assert handle.key_hash == _hash()
        assert handle.rank == result.handle.rank
        row = key_row(store)
        assert row["rank"] == result.handle.rank
        env = parse(next(iter(heads(store).values())))
        assert env is not None and env.tok == row["tok"] and env.key == _hash()
        # The key itself is stored nowhere.
        assert not any(KEY in str(k) or KEY in str(v) for k, v in store.items())

    def test_repeat_returns_the_stored_item_with_two_point_reads(
        self, config: Config, store: dict[Any, Any], ctl: Ctl
    ) -> None:
        first = _lst(config).append_once({"title": "a"}, key=KEY)
        ctl.calls.clear()
        again = _lst(config).append_once({"title": "a"}, key=KEY)
        assert again.created is False
        assert again.item == {"title": "a"}
        assert again.handle.rank == first.handle.rank
        assert len(heads(store)) == 1
        assert json.loads(store[(ACTOR, f"list:{NAME}-meta")])["count_hint"] == 1
        # Besides the meta-row reads every mutator makes (the lazy-migration
        # check and the dispatch): the key row and the head. No range read.
        reads = [c for c in ctl.calls if c[2] != f"list:{NAME}-meta"]
        assert reads == [
            ("get", AUX, key_row_name(NAME, _hash())),
            ("get", ACTOR, f"list:{NAME}-#{first.handle.rank}"),
        ]

    def test_a_different_key_appends_and_actors_hash_differently(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        lst = _lst(config)
        lst.append_once("a", key=KEY)
        assert lst.append_once("b", key=KEY + "-2").created is True
        assert lst.to_list() == ["a", "b"]
        assert _hash(KEY, ACTOR) != _hash(KEY, "otheractor")
        other = _lst(config, actor="otheractor").append_once("a", key=KEY)
        assert other.handle.key_hash == _hash(KEY, "otheractor")

    def test_same_key_different_payload_returns_the_first(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        _lst(config).append_once({"v": 1}, key=KEY)
        before = dict(store)
        again = _lst(config).append_once({"v": 2}, key=KEY)
        assert again.created is False and again.item == {"v": 1}
        assert store == before

    @pytest.mark.parametrize(
        "bad", ["", "x" * 513, "ab\ncd", "ab\x00", "\x9f", 42, None, b"bytes"]
    )
    def test_invalid_keys_are_refused_before_any_write(
        self,
        config: Config,
        store: dict[Any, Any],
        ctl: Ctl,
        bad: Any,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.DEBUG)
        with pytest.raises(ValueError, match="append_once\\(\\) key"):
            _lst(config).append_once("a", key=bad)
        assert store == {}
        assert ctl.calls == []
        if isinstance(bad, str) and bad:
            assert bad not in caplog.text
            assert bad not in str(ctl.calls)

    def test_a_512_character_key_is_accepted(self, config: Config) -> None:
        assert _lst(config).append_once("a", key="k" * 512).created is True

    def test_v1_list_names_migrate_to_v2(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        store[(ACTOR, f"list:{NAME}-meta")] = json.dumps({"format": 1, "length": 0})
        with pytest.raises(ValueError, match="migrate_to_v2"):
            _lst(config).append_once("a", key=KEY)
        assert key_rows(store) == {}


class TestCrashAndDangling:
    def test_head_without_key_row_is_found_and_finished(
        self, config: Config, store: dict[Any, Any], ctl: Ctl, aged: None
    ) -> None:
        # The first call stops after its head write (the key-row create
        # faults), leaving a keyed head and no key row.
        ctl.fail_create.add("-$key-")
        with pytest.raises(DbError):
            _lst(config).append_once("a", key=KEY)
        ctl.fail_create.clear()
        assert len(heads(store)) == 1 and key_rows(store) == {}
        report = _lst(config).verify()
        assert report["unkeyed_keyed_items"] == [n.split("-#")[1] for n in heads(store)]
        assert report["healthy"] is True
        again = _lst(config).append_once("a", key=KEY)
        assert again.created is False and again.item == "a"
        assert key_row(store)["rank"] == again.handle.rank
        assert len(heads(store)) == 1

    def test_dangling_key_row_is_reported_then_replaced(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        store[(AUX, key_row_name(NAME, _hash()))] = json.dumps(
            {"rank": "a5", "tok": "1700000000000-" + "0" * 16}
        )
        _lst(config).append("unrelated")
        report = _lst(config).verify()
        assert report["dangling_key_rows"] == ["a5"]
        assert report["key_rows"] == 1
        result = _lst(config).append_once("a", key=KEY)
        assert result.created is True
        assert key_row(store)["rank"] == result.handle.rank
        assert _lst(config).to_list() == ["unrelated", "a"]

    def test_rank_reuse_never_deletes_our_own_new_head(
        self, config: Config, store: dict[Any, Any], ctl: Ctl
    ) -> None:
        # The architecture evaluator's sequence: a keyed item at the last
        # rank is deleted and its key-row delete faults, leaving a row whose
        # hint is the rank the next append reuses. The row appears inside
        # the window step 2 cannot see (just before our key-row create).
        lst = _lst(config)
        lst.append("first")
        first = lst.append_once("a", key=KEY)
        ctl.fail_delete.add("-$key-")
        assert lst.delete_by_handle(first.handle) is True
        ctl.fail_delete.clear()
        stale = store.pop((AUX, key_row_name(NAME, _hash())))

        def reappear() -> None:
            ctl.before_key_create = None
            store[(AUX, key_row_name(NAME, _hash()))] = stale

        ctl.before_key_create = reappear
        result = _lst(config).append_once("a", key=KEY)
        assert result.created is True
        assert result.handle.rank == first.handle.rank  # the reused rank
        assert _lst(config).to_list() == ["first", "a"]
        assert key_row(store)["tok"] == parse(result.handle.raw_value).tok  # type: ignore[union-attr]

    def test_a_stale_hint_after_compact_is_repaired(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        lst = _lst(config)
        first = lst.append_once("a", key=KEY)
        for i in range(3):
            lst.insert(0, f"front-{i}")
        lst.compact()
        assert key_row(store)["rank"] == first.handle.rank  # not remapped
        again = _lst(config).append_once("a", key=KEY)
        assert again.created is False and again.item == "a"
        assert again.handle.rank != first.handle.rank
        assert key_row(store)["rank"] == again.handle.rank


class TestSizeAndMetaBeforeKeyRows:
    def test_size_refusal_writes_nothing(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        with pytest.raises(ListItemTooLargeError):
            _lst(config).append_once(big("a", 30_000), key=KEY)
        assert store == {}

    def test_meta_row_fault_writes_no_key_row_and_no_head(
        self, config: Config, store: dict[Any, Any], ctl: Ctl
    ) -> None:
        ctl.fail_create.add("-meta")
        with pytest.raises(DbError):
            _lst(config).append_once("a", key=KEY)
        assert store == {}


class TestOverlap:
    def test_a_writer_that_lands_first_wins_and_ours_is_deleted(
        self, config: Config, store: dict[Any, Any], ctl: Ctl
    ) -> None:
        def other_writer() -> None:
            ctl.before_key_create = None
            plant_winner(store, "Zz", {"from": "winner"})

        ctl.before_key_create = other_writer
        result = _lst(config).append_once(big("ours"), key=KEY)
        assert result.created is False
        assert result.item == {"from": "winner"}
        assert result.handle.rank == "Zz"
        assert _lst(config).to_list() == [{"from": "winner"}]
        assert span_rows(store) == {}  # our bodies went with our head

    def test_a_concurrent_repeat_that_adopts_our_head_lets_us_win(
        self, config: Config, store: dict[Any, Any], ctl: Ctl
    ) -> None:
        # The other call runs its whole protocol in our window: its scan
        # finds our head, writes the key row naming it, and returns it.
        seen: list[AppendOnceResult] = []

        def other_call() -> None:
            ctl.before_key_create = None
            seen.append(_lst(config).append_once("a", key=KEY))

        ctl.before_key_create = other_call
        ours = _lst(config).append_once("a", key=KEY)
        assert ours.created is True
        assert seen[0].created is False
        assert seen[0].handle.rank == ours.handle.rank
        assert _lst(config).to_list() == ["a"]

    def test_loser_finds_its_head_by_token_after_compact_moved_it(
        self, config: Config, store: dict[Any, Any], ctl: Ctl
    ) -> None:
        def winner_then_move() -> None:
            ctl.before_key_create = None
            ((name, head),) = heads(store).items()
            del store[(ACTOR, name)]
            store[(ACTOR, f"list:{NAME}-#b5")] = head  # compact() moved ours
            plant_winner(store, "Zz", "winner")

        ctl.before_key_create = winner_then_move
        result = _lst(config).append_once("ours", key=KEY)
        assert result.created is False and result.item == "winner"
        assert _lst(config).to_list() == ["winner"]

    def test_loser_delete_fault_leaves_a_duplicate_compact_removes(
        self, config: Config, store: dict[Any, Any], ctl: Ctl, aged: None
    ) -> None:
        def winner_and_fault() -> None:
            ctl.before_key_create = None
            plant_winner(store, "Zz", "winner")
            ctl.fail_delete.add(f"list:{NAME}-#")

        ctl.before_key_create = winner_and_fault
        with pytest.raises(DbError):
            _lst(config).append_once("ours", key=KEY)
        ctl.fail_delete.clear()
        assert len(heads(store)) == 2
        report = _lst(config).verify()
        assert report["healthy"] is False
        assert len(report["duplicate_keyed_items"]) == 2
        compacted = _lst(config).compact()
        assert compacted["duplicate_keyed_items_removed"] == 1
        assert _lst(config).to_list() == ["winner"]
        assert _lst(config).verify()["healthy"] is True
        assert _lst(config).append_once("x", key=KEY).item == "winner"

    def test_attempt_budget_keeps_the_head_for_a_repeat_to_finish(
        self, config: Config, store: dict[Any, Any], ctl: Ctl
    ) -> None:
        # Every key-row create loses to a row naming a head that does not
        # exist (dangling each time): three passes, then RuntimeError. The
        # head stays (deleting it could remove an item a repeat is adopting);
        # a repeat finishes it and announces it once.
        from actingweb.interface.property_store import NotifyingListProperty

        def phantom() -> None:
            store[(AUX, key_row_name(NAME, _hash()))] = json.dumps(
                {"rank": "zz", "tok": "1700000000000-" + "e" * 16}
            )

        ctl.before_key_create = phantom
        with pytest.raises(RuntimeError, match="append_once"):
            _lst(config).append_once(big("a"), key=KEY)
        assert sum(1 for c in ctl.calls if c[0] == "create" and "-$key-" in c[2]) == 3
        assert len(heads(store)) == 1
        ctl.before_key_create = None
        store.pop((AUX, key_row_name(NAME, _hash())), None)
        actor = mock.Mock()
        again = NotifyingListProperty(_lst(config), NAME, actor).append_once(
            big("a"), key=KEY
        )
        assert again.created is False and again.announced is True
        assert again.item == big("a")
        assert len(actor.register_diffs.call_args_list) == 1
        assert _lst(config).to_list() == [big("a")]


class TestAmbiguousConditionalWrites:
    def test_head_and_key_creates_that_landed_but_answered_false(
        self, config: Config, store: dict[Any, Any], ctl: Ctl
    ) -> None:
        ctl.ambiguous_create.update({f"list:{NAME}-#", "-$key-"})
        result = _lst(config).append_once("a", key=KEY)
        assert result.created is True
        assert _lst(config).to_list() == ["a"]
        assert key_row(store)["rank"] == result.handle.rank

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "thoughts/todo/conditional-write-ambiguous-after-sdk-retry.md: a "
            "plain append() cannot tell its own landed write from a rank "
            "collision, so it writes the item again"
        ),
    )
    def test_plain_append_still_duplicates(
        self, config: Config, store: dict[Any, Any], ctl: Ctl
    ) -> None:
        ctl.ambiguous_create.add(f"list:{NAME}-#")
        _lst(config).append("a")
        assert _lst(config).to_list() == ["a"]


class TestSpannedAndKeyed:
    def test_spanned_keyed_item_found_by_hash_reading_one_body_set(
        self, config: Config, store: dict[Any, Any], ctl: Ctl
    ) -> None:
        lst = _lst(config)
        lst.append(big("x"))
        lst.append(big("y"))
        first = lst.append_once(big("k"), key=KEY)
        assert first.handle.spanned is True
        del store[(AUX, key_row_name(NAME, _hash()))]  # force the scan
        ctl.calls.clear()
        again = _lst(config).append_once(big("k"), key=KEY)
        assert again.created is False and again.item == big("k")
        body_reads = [c for c in ctl.calls if c[0] == "get_prefix" and "$span-" in c[2]]
        assert len(body_reads) == 1  # the returned item's, not every head's


class TestLifetime:
    def test_a_rewrite_keeps_the_key(self, config: Config) -> None:
        lst = _lst(config)
        first = lst.append_once("a", key=KEY)
        assert lst.update_by_handle(first.handle, big("b")) is True
        again = _lst(config).append_once("a", key=KEY)
        assert again.created is False and again.item == big("b")
        lst[0] = "c"
        assert _lst(config).append_once("a", key=KEY).item == "c"

    @pytest.mark.parametrize("how", ["handle", "pop", "remove", "delitem"])
    def test_deletion_frees_the_key(
        self, config: Config, store: dict[Any, Any], how: str
    ) -> None:
        lst = _lst(config)
        first = lst.append_once("a", key=KEY)
        if how == "handle":
            assert lst.delete_by_handle(first.handle) is True
        elif how == "pop":
            assert lst.pop() == "a"
        elif how == "remove":
            lst.remove("a")
        else:
            del lst[0]
        assert key_rows(store) == {}
        assert _lst(config).append_once("b", key=KEY).created is True
        assert _lst(config).to_list() == ["b"]

    def test_a_duplicate_deleted_does_not_free_the_winners_key(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        lst = _lst(config)
        lst.append_once("winner", key=KEY)
        loser = wrap(value="loser", key=_hash(), tok="1600000000000-" + "1" * 16)
        store[(ACTOR, f"list:{NAME}-#Zz")] = loser
        ((handle, _),) = [(h, i) for h, i in lst.items_with_handles() if i == "loser"]
        assert lst.delete_by_handle(handle) is True
        assert len(key_rows(store)) == 1
        assert _lst(config).append_once("x", key=KEY).item == "winner"

    @pytest.mark.parametrize("how", ["clear", "delete"])
    def test_clear_and_delete_remove_key_rows(
        self, config: Config, store: dict[Any, Any], how: str
    ) -> None:
        lst = _lst(config)
        lst.append_once("a", key=KEY)
        getattr(lst, how)()
        assert key_rows(store) == {}
        assert _lst(config).append_once("b", key=KEY).created is True


class TestCompactKeys:
    def test_compact_creates_missing_key_rows_at_final_ranks(
        self, config: Config, store: dict[Any, Any], ctl: Ctl, aged: None
    ) -> None:
        lst = _lst(config)
        for i in range(3):
            lst.insert(0, f"front-{i}")
        ctl.fail_create.add("-$key-")
        with pytest.raises(DbError):
            lst.append_once("a", key=KEY)
        ctl.fail_create.clear()
        report = _lst(config).compact()
        assert report["key_rows_created"] == 1
        ((handle, _),) = [
            (h, i) for h, i in _lst(config).items_with_handles() if i == "a"
        ]
        assert key_row(store)["rank"] == handle.rank
        assert _lst(config).verify()["unkeyed_keyed_items"] == []

    def test_compact_removes_dangling_key_rows(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        _lst(config).append("x")
        store[(AUX, key_row_name(NAME, _hash()))] = json.dumps(
            {"rank": "a9", "tok": "1700000000000-" + "0" * 16}
        )
        report = _lst(config).compact()
        assert report["dangling_key_rows_removed"] == 1
        assert key_rows(store) == {}


class TestWrappers:
    def test_notifying_list_registers_one_diff_on_create_only(
        self, config: Config
    ) -> None:
        from actingweb.interface.property_store import NotifyingListProperty

        actor = mock.Mock()
        lst = NotifyingListProperty(_lst(config), NAME, actor)
        assert lst.append_once({"t": 1}, key=KEY).created is True
        assert lst.append_once({"t": 2}, key=KEY).created is False
        (call,) = actor.register_diffs.call_args_list
        blob = json.loads(call.kwargs["blob"])
        assert blob["operation"] == "append"
        assert blob["item"] == {"t": 1}

    def test_permission_view_requires_write(self, config: Config) -> None:
        from actingweb.interface.authenticated_views import (
            _PermissionEnforcingListView,
        )

        parent = mock.Mock()
        parent._check_permission.side_effect = PermissionError("denied")
        view = _PermissionEnforcingListView(_lst(config), NAME, parent)
        with pytest.raises(PermissionError):
            view.append_once("a", key=KEY)
        parent._check_permission.assert_called_once_with(NAME, "write")


class TestVerification8:
    """thoughts/verifications/2026-10-31-spanned-list-items-8.md, V8-1 to
    V8-10: in-flight states, adopted heads, announcements and the cache."""

    def test_v8_1_an_item_deleted_before_adoption_is_not_returned(
        self, config: Config, store: dict[Any, Any], ctl: Ctl
    ) -> None:
        # A head with no key row (a crashed call); it is deleted between the
        # repeat's scan and its key-row create. The repeat must not return it.
        ctl.fail_create.add("-$key-")
        with pytest.raises(DbError):
            _lst(config).append_once("old", key=KEY)
        ctl.fail_create.clear()

        def delete_it() -> None:
            ctl.before_key_create = None
            for name in list(heads(store)):
                del store[(ACTOR, name)]

        ctl.before_key_create = delete_it
        result = _lst(config).append_once("new", key=KEY)
        assert result.created is True and result.item == "new"
        assert _lst(config).to_list() == ["new"]
        assert key_row(store)["rank"] == result.handle.rank

    def test_v8_2_the_crash_hole_scan_is_strongly_consistent(
        self, config: Config, store: dict[Any, Any], ctl: Ctl
    ) -> None:
        ctl.fail_create.add("-$key-")
        with pytest.raises(DbError):
            _lst(config).append_once("a", key=KEY)
        ctl.fail_create.clear()
        calls: list[bool] = []
        original = HookDb.get_range

        def recording(self: HookDb, **kwargs: Any) -> dict[str, str]:
            calls.append(kwargs.get("consistent_read", True))
            return original(self, **kwargs)

        with mock.patch.object(HookDb, "get_range", recording):
            _lst(config).append_once("a", key=KEY)
        assert calls and all(calls)

    def test_v8_3_young_duplicates_and_unkeyed_heads_are_left_alone(
        self, config: Config, store: dict[Any, Any], ctl: Ctl
    ) -> None:
        # Two running calls' heads, neither key row written yet.
        for tok_tail, rank in (("1", "a5"), ("2", "a6")):
            tok = new_gen()[:14] + tok_tail * 16  # minted now
            store[(ACTOR, f"list:{NAME}-#{rank}")] = wrap(
                value=f"call-{tok_tail}", key=_hash(), tok=tok
            )
        _lst(config).append("x")
        before = dict(store)
        report = _lst(config).verify()
        assert report["duplicate_keyed_items"] == []
        assert report["unkeyed_keyed_items"] == []
        assert report["healthy"] is True
        repaired = _lst(config).repair_keys()
        assert repaired == {
            "duplicate_keyed_items_removed": 0,
            "dangling_key_rows_removed": 0,
            "key_rows_created": 0,
        }
        assert store == before

    def test_v8_3_compact_keeps_a_key_row_written_after_it_read_the_heads(
        self, config: Config, store: dict[Any, Any], ctl: Ctl
    ) -> None:
        _lst(config).append("x")

        def late_append() -> None:
            # An append_once that lands between compact's head read and its
            # key-row read, with an old token so the age guard does not hide
            # it: only the strong re-read can save its key row.
            plant_winner(store, "b5", "late", tok=OLD_TOK)

        ctl.before_key_prefix = late_append
        report = _lst(config).repair_keys()
        assert report["dangling_key_rows_removed"] == 0
        assert key_row(store)["rank"] == "b5"

    def test_v8_3_repair_keys_removes_an_aged_duplicate_without_rebalancing(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        lst = _lst(config)
        for i in range(3):
            lst.insert(0, f"front-{i}")
        plant_winner(store, "b5", "winner", tok=OLD_TOK)
        store[(ACTOR, f"list:{NAME}-#b6")] = wrap(
            value="loser", key=_hash(), tok="1600000000000-" + "1" * 16
        )
        ranks_before = sorted(n for n in heads(store) if not n.endswith(("b5", "b6")))
        report = _lst(config).verify()
        assert report["duplicate_keyed_items"] == ["b5", "b6"]
        assert report["healthy"] is False
        assert _lst(config).repair_keys()["duplicate_keyed_items_removed"] == 1
        assert sorted(n for n in heads(store) if not n.endswith("b5")) == ranks_before
        assert "winner" in _lst(config).to_list()
        assert "loser" not in _lst(config).to_list()

    def test_v8_4_a_repeat_that_finishes_a_crashed_call_announces_it(
        self, config: Config, store: dict[Any, Any], ctl: Ctl
    ) -> None:
        from actingweb.interface.property_store import NotifyingListProperty

        ctl.fail_create.add("-$key-")
        with pytest.raises(DbError):
            _lst(config).append_once({"t": 1}, key=KEY)
        ctl.fail_create.clear()
        meta = json.loads(store[(ACTOR, f"list:{NAME}-meta")])
        assert meta["count_hint"] == 0
        actor = mock.Mock()
        result = NotifyingListProperty(_lst(config), NAME, actor).append_once(
            {"t": 2}, key=KEY
        )
        assert result.created is False and result.item == {"t": 1}
        (call,) = actor.register_diffs.call_args_list
        assert json.loads(call.kwargs["blob"])["item"] == {"t": 1}
        assert json.loads(store[(ACTOR, f"list:{NAME}-meta")])["count_hint"] == 1

    def test_v8_4_an_adopted_running_call_and_its_adopter_announce_once(
        self, config: Config, store: dict[Any, Any], ctl: Ctl
    ) -> None:
        from actingweb.interface.property_store import NotifyingListProperty

        actor = mock.Mock()
        seen: list[AppendOnceResult] = []

        def other_call() -> None:
            ctl.before_key_create = None
            seen.append(
                NotifyingListProperty(_lst(config), NAME, actor).append_once(
                    "a", key=KEY
                )
            )

        ctl.before_key_create = other_call
        ours = NotifyingListProperty(_lst(config), NAME, actor).append_once(
            "a", key=KEY
        )
        assert ours.created is True and seen[0].created is False
        assert len(actor.register_diffs.call_args_list) == 1
        assert json.loads(store[(ACTOR, f"list:{NAME}-meta")])["count_hint"] == 1

    def test_v8_7_len_is_right_after_a_dangling_retry_and_a_lost_race(
        self, config: Config, store: dict[Any, Any], ctl: Ctl
    ) -> None:
        lst = _lst(config)
        lst.append("first")
        assert len(lst) == 1

        def phantom_once() -> None:
            ctl.before_key_create = None
            store[(AUX, key_row_name(NAME, _hash()))] = json.dumps(
                {"rank": "zz", "tok": OLD_TOK}
            )

        ctl.before_key_create = phantom_once
        assert lst.append_once("a", key=KEY).created is True
        assert len(lst) == 2 == len(_lst(config))

    def test_v8_7_len_is_right_after_a_lost_race(
        self, config: Config, store: dict[Any, Any], ctl: Ctl
    ) -> None:
        lst = _lst(config)
        lst.append("first")
        assert len(lst) == 1

        def winner() -> None:
            ctl.before_key_create = None
            plant_winner(store, "Zz", "winner", tok=OLD_TOK)

        ctl.before_key_create = winner
        result = lst.append_once("ours", key=KEY)
        assert result.created is False and result.item == "winner"
        assert len(lst) == 2 == len(_lst(config))

    def test_v8_8_a_keyed_non_ascii_fallback_item_spans_when_escaped(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        class Opaque:
            def __str__(self) -> str:
                return "é" * 900  # 1,800 UTF-8 bytes; 5,400 once JSON-escaped

        result = _lst(config).append_once(Opaque(), key=KEY)
        assert result.handle.spanned is True
        assert all(len(v) <= 2_000 for v in heads(store).values())
        assert _lst(config).to_list() == ["é" * 900]

    def test_v8_9_a_failed_hint_repair_does_not_fail_the_repeat(
        self, config: Config, store: dict[Any, Any], ctl: Ctl
    ) -> None:
        lst = _lst(config)
        first = lst.append_once("a", key=KEY)
        for i in range(3):
            lst.insert(0, f"front-{i}")
        lst.compact()
        ctl.fail_cas.add("-$key-")
        again = _lst(config).append_once("a", key=KEY)
        assert again.created is False and again.item == "a"
        assert key_row(store)["rank"] == first.handle.rank  # not repaired yet


class TestRepairScript:
    """V8-10: --repair runs repair_keys() for a list whose only repairable
    finding is duplicate keyed items, and compact() when ranks need it."""

    @staticmethod
    def _sweep(monkeypatch: pytest.MonkeyPatch, report: dict[str, Any]) -> list[str]:
        from actingweb.maintenance import verify_property_lists as script

        ran: list[str] = []
        monkeypatch.setattr(
            "actingweb.property.PropertyListStore.list_all", lambda self: ["l"]
        )
        reports = iter([report, {**report, "healthy": True}])
        monkeypatch.setattr(ListProperty, "verify", lambda self, **kw: next(reports))
        monkeypatch.setattr(
            ListProperty, "repair_keys", lambda self: ran.append("repair_keys") or {}
        )
        monkeypatch.setattr(
            ListProperty, "compact", lambda self, **kw: ran.append("compact") or {}
        )
        result = script.sweep_actor(
            "a1",
            Config(database="dynamodb"),
            repair=True,
            limiter=script.RateLimiter(0),
        )
        assert result == (1, 0, 0)
        return ran

    BASE = {
        "format": 2,
        "healthy": False,
        "length": 3,
        "max_rank_length": 2,
        "adjacent_duplicates": [],
        "duplicate_keyed_items": ["a0", "a1"],
    }

    def test_keys_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        report = {**self.BASE, "needs_rebalance": False}
        assert self._sweep(monkeypatch, report) == ["repair_keys"]

    def test_keys_and_ranks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        report = {**self.BASE, "needs_rebalance": True}
        assert self._sweep(monkeypatch, report) == ["compact"]


class TestVerification9:
    """thoughts/verifications/2026-10-31-spanned-list-items-9.md: the
    in-flight guard's clock bound, clear() and the key, the adopted item's
    position, a budget exit after adoption, following a key row bound
    elsewhere, and repair_keys() on the wrappers."""

    def test_a_token_far_in_the_future_counts_as_old(self) -> None:
        far = f"{9_999_999_999_999:013d}-" + "0" * 16
        assert ListProperty._in_flight(far) is False
        assert ListProperty._in_flight(new_gen()) is True
        assert ListProperty._in_flight(OLD_TOK) is False

    def test_clear_keeps_the_key_row_of_a_head_it_did_not_delete(
        self, config: Config, store: dict[Any, Any], ctl: Ctl
    ) -> None:
        lst = _lst(config)
        lst.append_once("gone", key=KEY + "-old")

        def racing_append() -> None:
            ctl.before_key_prefix = None
            plant_winner(store, "b5", "racing", tok=new_gen())  # a running call

        ctl.before_key_prefix = racing_append
        lst.clear()
        assert list(key_rows(store)) == [key_row_name(NAME, _hash())]
        again = _lst(config).append_once("x", key=KEY)
        assert again.created is False and again.item == "racing"

    def test_an_adopted_item_is_announced_as_an_insert_at_its_position(
        self, config: Config, store: dict[Any, Any], ctl: Ctl
    ) -> None:
        from actingweb.interface.property_store import NotifyingListProperty

        ctl.fail_create.add("-$key-")
        with pytest.raises(DbError):
            _lst(config).append_once("x", key=KEY)
        ctl.fail_create.clear()
        _lst(config).append("y")
        _lst(config).append("z")
        actor = mock.Mock()
        result = NotifyingListProperty(_lst(config), NAME, actor).append_once(
            "x", key=KEY
        )
        assert result.created is False and result.announced is True
        assert result.announce_index == 0
        (call,) = actor.register_diffs.call_args_list
        blob = json.loads(call.kwargs["blob"])
        assert blob["operation"] == "insert" and blob["index"] == 0

    def test_a_budget_exit_keeps_a_head_another_call_adopted(
        self, config: Config, store: dict[Any, Any], ctl: Ctl
    ) -> None:
        passes = {"n": 0}

        def phantom_then_adopt() -> None:
            passes["n"] += 1
            if passes["n"] < 3:
                store[(AUX, key_row_name(NAME, _hash()))] = json.dumps(
                    {"rank": "zz", "tok": OLD_TOK}
                )
                return
            # Third pass: a repeat adopts our head just before our create.
            ctl.before_key_create = None
            seen.append(_lst(config).append_once("a", key=KEY))

        seen: list[AppendOnceResult] = []
        ctl.before_key_create = phantom_then_adopt
        result = _lst(config).append_once("a", key=KEY)
        assert result.created is True and result.announced is False
        assert seen[0].created is False and seen[0].announced is True
        assert _lst(config).to_list() == ["a"]

    def test_a_lost_adoption_follows_the_row_to_its_head(
        self, config: Config, store: dict[Any, Any], ctl: Ctl, aged: None
    ) -> None:
        ctl.fail_create.add("-$key-")
        with pytest.raises(DbError):
            _lst(config).append_once("crashed", key=KEY)
        ctl.fail_create.clear()

        def bound_elsewhere() -> None:
            ctl.before_key_create = None
            plant_winner(store, "b5", "winner", tok=OLD_TOK)

        ctl.before_key_create = bound_elsewhere
        result = _lst(config).append_once("x", key=KEY)
        assert result.created is False and result.item == "winner"
        assert len(heads(store)) == 2  # no third copy written

    def test_repair_keys_on_the_notifying_list_and_the_view(
        self, config: Config
    ) -> None:
        from actingweb.interface.authenticated_views import (
            _PermissionEnforcingListView,
        )
        from actingweb.interface.property_store import NotifyingListProperty

        actor = mock.Mock()
        report = NotifyingListProperty(_lst(config), NAME, actor).repair_keys()
        assert set(report) == {
            "duplicate_keyed_items_removed",
            "dangling_key_rows_removed",
            "key_rows_created",
        }
        (call,) = actor.register_diffs.call_args_list
        assert json.loads(call.kwargs["blob"])["operation"] == "metadata"
        parent = mock.Mock()
        parent._check_permission.side_effect = PermissionError("denied")
        with pytest.raises(PermissionError):
            _PermissionEnforcingListView(_lst(config), NAME, parent).repair_keys()
        parent._check_permission.assert_called_once_with(NAME, "write")


class TestVerification10:
    """thoughts/verifications/2026-10-31-spanned-list-items-10.md: an SDK
    retry of an adoption announces; the span sweep frees a removed head's
    key; clear() removes aged dangling rows; repair_keys() checks its
    connection. (The adoption mark of entry 75 was withdrawn in entry 78.)"""

    def test_an_sdk_retry_of_an_adoption_create_still_announces(
        self, config: Config, store: dict[Any, Any], ctl: Ctl
    ) -> None:
        ctl.fail_create.add("-$key-")
        with pytest.raises(DbError):
            _lst(config).append_once("x", key=KEY)
        ctl.fail_create.clear()
        ctl.ambiguous_create.add("-$key-")
        result = _lst(config).append_once("x", key=KEY)
        assert result.created is False and result.announced is True

    def test_the_span_sweep_frees_a_removed_heads_key(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        lst = _lst(config)
        lst.append_once(big("k"), key=KEY)
        for name in [n for (a, n) in store if a == AUX and "-$span-" in n][:1]:
            del store[(AUX, name)]
        report = lst.sweep_span_orphans()
        assert report["broken_spans_removed"] == 1
        assert key_rows(store) == {}

    def test_clear_removes_an_aged_dangling_key_row(
        self, config: Config, store: dict[Any, Any]
    ) -> None:
        _lst(config).append("x")
        store[(AUX, key_row_name(NAME, _hash()))] = json.dumps(
            {"rank": "a9", "tok": OLD_TOK}
        )
        _lst(config).clear()
        assert key_rows(store) == {}

    def test_repair_keys_needs_a_connection(self, config: Config) -> None:
        lst = _lst(config)
        lst._db = None
        with pytest.raises(RuntimeError, match="database connection"):
            lst.repair_keys()


class TestPr163Review:
    """PR #163 review: churn that makes every adoption see its item vanish
    spends the attempt budget and raises, writing nothing of its own."""

    def test_repeated_item_gone_exhausts_the_budget(
        self, config: Config, store: dict[Any, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from actingweb.property_list import _ItemGone

        calls = {"n": 0}

        def gone(self: ListProperty, key_hash: str, tok: str) -> Any:
            calls["n"] += 1
            raise _ItemGone("deleted under the read")

        monkeypatch.setattr(ListProperty, "_find_keyed", gone)
        with pytest.raises(RuntimeError, match="append_once"):
            _lst(config).append_once("a", key=KEY)
        assert calls["n"] == 3
        assert heads(store) == {}
        assert key_rows(store) == {}
