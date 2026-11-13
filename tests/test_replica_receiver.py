"""The replica receiver on the list core
(thoughts/plans/2026-11-13-attribute-list-v2-port.md, Phase 3): what a
callback or a baseline does to a ``RemotePeerStore``, by subscription level,
on the in-memory attribute backend."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from actingweb.db.exceptions import DbError
from actingweb.remote_storage import RemotePeerStore
from tests.mcp_token_double import MemoryStore, make_config

ACTOR = "actor123"
PEER = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"


@pytest.fixture
def env() -> tuple[RemotePeerStore, MemoryStore, Any]:
    actor = MagicMock()
    actor.id = ACTOR
    actor.config, store = make_config()
    return RemotePeerStore(actor, PEER), store, actor.config


def _diff(name: str, operation: str, **fields: Any) -> dict[str, Any]:
    return {"list": name, "operation": operation, **fields}


class TestTheDamageThisPlanExistsFor:
    @pytest.mark.parametrize("operation", ["insert", "delete"])
    @pytest.mark.parametrize("crash_at", range(0, 4))
    def test_a_crash_after_any_write_leaves_the_list_before_or_after(
        self, env, operation, crash_at
    ):
        remote, _, config = env
        remote.set_list("notes", ["a", "b", "c"])
        before = remote.get_list("notes")
        after = ["a", "x", "b", "c"] if operation == "insert" else ["a", "c"]
        diff = (
            _diff("notes", "insert", index=1, item="x")
            if operation == "insert"
            else _diff("notes", "delete", index=1)
        )
        from tests.test_attribute_list import _crash_after

        real = config.DbAttribute.DbAttribute
        _crash_after(config, crash_at)
        try:
            remote.apply_callback_data({"notes": diff})
        except DbError:
            pass
        config.DbAttribute.DbAttribute = real
        assert remote.get_list("notes") in (before, after)
        lst = remote._get_list_store().get("notes")  # noqa: SLF001
        assert lst.verify()["healthy"]


class TestBinding:
    def test_a_value_naming_another_list_is_a_scalar(self, env):
        remote, _, _ = env
        remote.set_list("victim", ["keep"])
        result = remote.apply_callback_data(
            {"color": {"list": "victim", "operation": "clear"}}
        )
        assert result["color"]["type"] == "scalar"
        assert remote.get_list("victim") == ["keep"]
        assert remote.get_value("color") == {"list": "victim", "operation": "clear"}

    def test_the_legacy_list_key_binds_to_its_own_name(self, env):
        remote, _, _ = env
        remote.set_list("victim", ["keep"])
        result = remote.apply_callback_data(
            {"list:notes": {"list": "victim", "operation": "clear"}}
        )
        assert "error" in result["list:notes"]
        assert remote.get_list("victim") == ["keep"]
        remote.apply_callback_data(
            {"list:notes": {"list": "notes", "operation": "append", "item": 1}}
        )
        assert remote.get_list("notes") == [1]


class TestReceiverBranches:
    def test_pop_with_a_negative_index(self, env):
        remote, _, _ = env
        remote.set_list("n", [1, 2, 3])
        remote.apply_callback_data({"n": _diff("n", "pop", index=-2)})
        assert remote.get_list("n") == [1, 3]

    def test_misses_are_not_out_of_step(self, env):
        remote, _, _ = env
        remote.set_list("n", ["a"])
        r = remote.apply_callback_data({"n": _diff("n", "remove", item="gone")})
        assert r.out_of_step is None and r["n"].get("noop")
        r = remote.apply_callback_data(
            {"n": _diff("n", "update", old_item="gone", item="a")}
        )
        assert r.out_of_step is None and r["n"].get("noop")
        assert remote.get_list("n") == ["a"]

    @pytest.mark.parametrize(
        "name", ["bad\nname", "has#hash", "has$dollar", "_private", "x" * 900]
    )
    def test_a_refused_name_on_create_is_accepted_on_delete(self, env, name, caplog):
        remote, store, _ = env
        with caplog.at_level("WARNING"):
            r = remote.apply_callback_data({name: _diff(name, "append", item=1)})
        assert r[name]["error"] == "refused name"
        assert repr(name)[:20] in caplog.text
        assert not [
            n for n in store.names(ACTOR, remote.bucket) if n.startswith("list:")
        ]
        r = remote.apply_callback_data({name: _diff(name, "delete_all")})
        assert r[name]["success"] is True

    def test_a_list_scalar_key_is_refused_in_a_diff_and_a_baseline(self, env):
        remote, store, _ = env
        r = remote.apply_callback_data({"list:x": "plain"})
        assert r["list:x"]["error"] == "refused"
        r = remote.apply_resync_data({"list:y": {"v": 1}})
        assert r["list:y"]["error"] == "refused"
        assert not store.names(ACTOR, remote.bucket)

    def test_an_enveloped_item_and_one_over_the_limit(self, env):
        from actingweb.property_list_span import ENVELOPE_MARKER

        remote, _, config = env
        r = remote.apply_callback_data(
            {"n": _diff("n", "append", item={ENVELOPE_MARKER: 1, "x": 1})}
        )
        assert "error" in r["n"]
        config.list_item_max_bytes = 100
        r = remote.apply_callback_data({"n": _diff("n", "append", item="x" * 500)})
        assert "error" in r["n"]
        remote.set_list("big", ["ok"])
        with pytest.raises(Exception):  # noqa: B017 -- the item cannot be stored
            remote.set_list("big", ["x" * 500])
        assert remote.get_list("big") == []

    @pytest.mark.parametrize(
        "scalar",
        [
            {"action": "add", "index": 0, "value": "x"},
            {"index": 0, "value": "x"},
            {"value": "Updated 3 items"},
        ],
    )
    def test_a_pre_316_scalar_for_a_lists_name_is_out_of_step(self, env, scalar):
        remote, _, _ = env
        remote.set_list("notes", ["a"])
        r = remote.apply_callback_data({"notes": scalar})
        assert r.out_of_step["list"] == "notes"
        assert remote.get_list("notes") == ["a"]

    def test_a_pre_316_list_delete_deletes_the_list(self, env):
        remote, _, _ = env
        remote.set_list("notes", ["a"])
        r = remote.apply_callback_data({"notes": ""})
        assert r["notes"] == {"deleted": True, "type": "list"}
        assert remote.list_all_lists() == []


class TestShapes:
    def test_subtarget_level(self, env):
        remote, _, _ = env
        r = remote.apply_callback_data(
            _diff("notes", "append", item="a"), subtarget="notes"
        )
        assert r["notes"]["success"] is True and remote.get_list("notes") == ["a"]
        remote.apply_callback_data({"hex": "#fff"}, subtarget="color")
        assert remote.get_value("color") == {"hex": "#fff"}
        assert remote.get_value("hex") is None
        # An object whose one key is the subtarget is a value, not a wrapper
        # (verification 2026-11-13, CR6): a subtarget's diffs are bare.
        remote.apply_callback_data({"color": {"hex": "#000"}}, subtarget="color")
        assert remote.get_value("color") == {"color": {"hex": "#000"}}

    def test_resource_level_merges(self, env):
        remote, _, _ = env
        remote.apply_callback_data({"i": 1}, subtarget="p", resource="k")
        remote.apply_callback_data({"j": 2}, subtarget="p", resource="m")
        assert remote.get_value("p") == {"k": {"i": 1}, "m": {"j": 2}}
        remote.apply_callback_data({"z": 3}, subtarget="p", resource="k/deep/er")
        assert remote.get_value("p")["k"]["deep"]["er"] == {"z": 3}
        remote.apply_callback_data("", subtarget="p", resource="k/deep")  # type: ignore[arg-type]
        assert "deep" not in remote.get_value("p")["k"]
        remote.set_value("s", {"k": "a string parent"})
        remote.apply_callback_data({"v": 1}, subtarget="s", resource="k/x")
        assert remote.get_value("s") == {"k": {"x": {"v": 1}}}

    def test_a_subtarget_baseline_creates_no_top_level_keys(self, env):
        remote, store, _ = env
        remote.apply_resync_data({"hex": "#fff", "shade": 3}, subtarget="color")
        assert remote.get_value("color") == {"hex": "#fff", "shade": 3}
        assert set(store.names(ACTOR, remote.bucket)) == {"color"}
        remote.apply_resync_data(
            {"notes": {"_list": True, "items": [1, 2]}}, subtarget="notes"
        )
        assert remote.get_list("notes") == [1, 2]


class TestOutOfStep:
    @pytest.mark.parametrize(
        ("diff", "why"),
        [
            (_diff("n", "delete", index=9), "out of range"),
            (_diff("n", "update", index=9, item=1), "out of range"),
            (_diff("n", "insert", index=9, item=1), "out of range"),
            (_diff("n", "pop", index=9), "out of range"),
            (_diff("n", "append", spanned=True, bytes=9, length=2), "spanned"),
        ],
    )
    def test_each_cause_reports_and_applies_the_rest(self, env, diff, why):
        remote, _, _ = env
        remote.set_list("n", ["a"])
        r = remote.apply_callback_data({"n": diff, "other": {"v": 1}})
        assert why in r.out_of_step["why"]
        assert remote.get_value("other") == {"v": 1}

    def test_a_layout_conflict_is_out_of_step(self, env):
        remote, store, _ = env
        remote.set_list("n", ["a"])
        store.bucket(ACTOR, remote.bucket)["list:n:meta"] = {"data": {"length": 0}}
        r = remote.apply_callback_data({"n": _diff("n", "append", item="b")})
        assert "ListLayoutConflictError" in r.out_of_step["why"]

    def test_a_fault_raises_and_marks_nothing(self, env):
        remote, store, _ = env
        remote.set_list("n", ["a"])
        store.write_faults.add(remote.bucket)
        with pytest.raises(DbError):
            remote.apply_callback_data({"n": _diff("n", "append", item="b")})


class TestOutsideVoiceFindings:
    """The Phase 3 outside-voice findings on the receiver."""

    def test_a_property_named_out_of_step_is_only_a_property(self, env):
        remote, _, _ = env
        r = remote.apply_callback_data({"out_of_step": {"v": 1}})
        assert r.out_of_step is None
        assert r["out_of_step"]["stored"] is True
        assert remote.get_value("out_of_step") == {"v": 1}
        r = remote.apply_resync_data({"out_of_step": {"v": 2}})
        assert r.out_of_step is None and r.failed == []

    @pytest.mark.parametrize("operation", ["clear", "update", "remove", "metadata"])
    def test_any_operation_on_a_new_list_validates_its_name(self, env, operation):
        remote, store, _ = env
        name = "x" * 900
        r = remote.apply_callback_data(
            {name: _diff(name, operation, item=1, old_item=0, index=0)}
        )
        assert r[name]["error"] == "refused name"
        assert not [
            n for n in store.names(ACTOR, remote.bucket) if n.startswith("list:")
        ]

    def test_an_existing_list_with_a_refused_name_can_still_change(self, env):
        remote, store, _ = env
        rows = store.bucket(ACTOR, remote.bucket)
        rows["list:_old:meta"] = {"data": {"length": 1, "version": "1.0"}}
        rows["list:_old:0"] = {"data": "a"}
        r = remote.apply_callback_data({"_old": _diff("_old", "clear")})
        assert r["_old"]["success"] is True

    def test_a_resource_write_does_not_shadow_a_list(self, env):
        remote, _, _ = env
        remote.set_list("items", ["a"])
        r = remote.apply_callback_data({"v": 1}, subtarget="items", resource="3")
        assert r["items"]["error"] == "refused"
        assert remote.get_value("items") is None
        assert remote.get_list("items") == ["a"]

    def test_a_baseline_entry_that_cannot_be_stored_is_failed(self, env):
        remote, _, config = env
        config.list_item_max_bytes = 100
        r = remote.apply_resync_data(
            {"big": {"_list": True, "items": ["x" * 500]}, "ok": {"v": 1}}
        )
        assert r.failed == ["big"]
        r = remote.apply_resync_data({"list:k": "scalar"})
        assert r.failed == []  # a refused key is the peer's own, not a failure


class TestVerificationFindings:
    """Verification 2026-11-13: the receiver's side of the new shapes."""

    def test_a_delete_with_old_item_takes_the_one_at_its_index(self, env):
        remote, _, _ = env
        # A bulk "move to top" on [A, B, C]: update 0 to C, delete 2 (C).
        remote.set_list("n", ["A", "B", "C"])
        remote.apply_callback_data(
            {"n": _diff("n", "update", index=0, old_item="A", item="C")}
        )
        r = remote.apply_callback_data(
            {"n": _diff("n", "delete", index=2, old_item="C")}
        )
        assert r.out_of_step is None
        assert remote.get_list("n") == ["C", "B"]

    def test_a_delete_with_old_item_finds_a_moved_item(self, env):
        remote, _, _ = env
        remote.set_list("n", ["x", "A", "B"])
        remote.apply_callback_data({"n": _diff("n", "delete", index=0, old_item="B")})
        assert remote.get_list("n") == ["x", "A"]

    def test_a_delete_of_an_absent_item_is_a_noop_and_a_drifted_duplicate_out_of_step(
        self, env
    ):
        remote, _, _ = env
        remote.set_list("n", ["A", "A", "B"])
        r = remote.apply_callback_data(
            {"n": _diff("n", "delete", index=0, old_item="gone")}
        )
        assert r.out_of_step is None and r["n"].get("noop")
        r = remote.apply_callback_data(
            {"n": _diff("n", "delete", index=2, old_item="A")}
        )
        assert r.out_of_step is not None
        assert remote.get_list("n") == ["A", "A", "B"]

    def test_a_refused_list_name_in_a_baseline_is_not_a_failure(self, env):
        remote, _, _ = env
        r = remote.apply_resync_data({"_x": {"_list": True, "items": [1]}})
        assert r["_x"]["error"] == "refused name"
        assert r.failed == []

    def test_a_baseline_repairs_a_list_in_both_layouts(self, env):
        remote, store, _ = env
        remote.set_list("n", ["a"])
        rows = store.bucket(ACTOR, remote.bucket)
        rows["list:n:meta"] = {"data": {"length": 1, "version": "1.0"}}
        rows["list:n:0"] = {"data": "old"}
        r = remote.apply_resync_data({"n": {"_list": True, "items": ["b"]}})
        assert r.failed == []
        assert remote.get_list("n") == ["b"]
        assert "list:n:meta" not in store.bucket(ACTOR, remote.bucket)

    def test_an_object_whose_one_key_is_its_name_is_a_value(self, env):
        remote, _, _ = env
        remote.apply_callback_data({"status": "ok"}, subtarget="status")
        assert remote.get_value("status") == {"status": "ok"}
        remote.apply_resync_data({"status": "fine"}, subtarget="status")
        assert remote.get_value("status") == {"status": "fine"}
