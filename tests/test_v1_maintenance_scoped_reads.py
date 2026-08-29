"""The v1 maintenance methods read one list, not the whole partition.

``verify()``, ``compact()`` and ``migrate_to_v2()`` each dumped the actor's
entire property partition through ``fetch_all_including_lists()`` and then
indexed the result by exact v1 row name. Their v2 counterparts never did:
``_v2_verify()`` goes through ``_v2_load_full()``, a scoped ``get_range()``,
and ``_v1_item_names_in_range()``'s own docstring already argued the case --
*"the bulk migration script avoids those precisely because they cost roughly
one dump per list on a typical actor"*. These three were the callers left
behind.

Three things change together, and each has its own test below:

* the read is scoped to ``_v1_bounds()`` (a name PREFIX would be a
  regression: ``list:output`` also matches ``list:output_embeddings_*``);
* it is strongly consistent, because two of the three rewrite destructively
  from what they read;
* the trailing ``or {}`` is gone, so a backend fault raises ``DbError``
  instead of presenting an empty partition as "every index is missing".

Reuses the dict-backed fakes from ``test_property_list_integrity.py``.
"""

import ast
import json
import pathlib

import pytest

from actingweb.db.exceptions import DbError
from actingweb.property_list import ListProperty
from tests.test_property_list_integrity import (
    FakePropertyDb,
    _patch_get_property,
    _seed_list,
    _seed_v2_list,
)

PROPERTY_LIST_PY = (
    pathlib.Path(__file__).resolve().parent.parent / "actingweb" / "property_list.py"
)

# The three methods this phase converted. Named once so the AST guards below
# and the behavioural tests cannot drift apart.
CONVERTED_METHODS = ("verify", "compact", "migrate_to_v2")


class RangeSpyDb(FakePropertyDb):
    """Records every get_range() call: its bounds and its consistency."""

    def __init__(self, store, fail_range=False):
        super().__init__(store)
        self.range_calls: list[dict] = []
        self.fail_range = fail_range

    def get_range(
        self,
        actor_id=None,
        lower=None,
        upper=None,
        keys_only=False,
        consistent_read=True,
    ):
        self.range_calls.append(
            {
                "lower": lower,
                "upper": upper,
                "keys_only": keys_only,
                "consistent_read": consistent_read,
            }
        )
        if self.fail_range:
            raise DbError("property range read", actor_id)
        return super().get_range(
            actor_id=actor_id,
            lower=lower,
            upper=upper,
            keys_only=keys_only,
            consistent_read=consistent_read,
        )


@pytest.fixture
def fake_store():
    return {}


def _list(store, actor_id, name):
    return ListProperty(actor_id=actor_id, name=name, config=object())


class TestNoPartitionDumpRemains:
    """The whole-partition read is gone from the module, not just from the
    three methods' happy paths. An AST guard rather than a spy: the fake can
    only observe a call that a *test* triggers, while this covers every path
    in the file, including ones no test reaches."""

    def test_property_list_module_never_calls_fetch_all_including_lists(self):
        tree = ast.parse(PROPERTY_LIST_PY.read_text(), filename=str(PROPERTY_LIST_PY))
        offenders = [
            f"line {node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "fetch_all_including_lists"
        ]
        assert offenders == [], (
            f"property_list.py must not dump the actor's whole property "
            f"partition -- every read here is scoped to one list: {offenders}"
        )

    def test_get_property_list_is_not_even_imported(self):
        tree = ast.parse(PROPERTY_LIST_PY.read_text(), filename=str(PROPERTY_LIST_PY))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        assert "get_property_list" not in imported

    def test_verify_issues_only_scoped_reads(self, monkeypatch, fake_store):
        actor_id, name = "actor-scope-verify", "notes"
        _seed_list(fake_store, actor_id, name, ["a", "b", "c"])
        db = RangeSpyDb(fake_store)
        _patch_get_property(monkeypatch, lambda config: db)

        _list(fake_store, actor_id, name).verify()

        assert db.range_calls, "verify() must read the list's rows"
        for call in db.range_calls:
            assert call["lower"].startswith(f"list:{name}-")
            assert call["upper"].startswith(f"list:{name}-")

    def test_compact_and_migrate_issue_only_scoped_reads(self, monkeypatch, fake_store):
        for method, name in (("compact", "c-list"), ("migrate_to_v2", "m-list")):
            store = {}
            actor_id = f"actor-scope-{method}"
            _seed_list(store, actor_id, name, ["a", "b", "c"])
            db = RangeSpyDb(store)
            _patch_get_property(monkeypatch, lambda config, db=db: db)

            getattr(_list(store, actor_id, name), method)()

            assert db.range_calls, f"{method}() must read the list's rows"
            for call in db.range_calls:
                assert call["lower"].startswith(f"list:{name}-"), method
                assert call["upper"].startswith(f"list:{name}-"), method


class TestScopedReadUsesBoundsNotAPrefix:
    """``f"list:{name}"`` would be a REGRESSION here, not an optimisation:
    for list ``output`` it also matches ``list:output_embeddings_*`` -- 403
    rows and 678 RCU on the measured account. ``_v1_bounds()`` spans
    ``list:{name}-0`` .. ``list:{name}-:`` and excludes both the ``-meta``
    row (``m``, 0x6D) and every v2 row (``#``, 0x23)."""

    def test_bounds_exclude_a_prefix_sibling_lists_rows(self, monkeypatch, fake_store):
        actor_id = "actor-prefix-sibling"
        _seed_list(fake_store, actor_id, "output", ["a", "b"])
        _seed_list(fake_store, actor_id, "output_embeddings_0", ["x", "y", "z"])
        db = RangeSpyDb(fake_store)
        _patch_get_property(monkeypatch, lambda config: db)

        report = _list(fake_store, actor_id, "output").verify()

        assert report["healthy"] is True
        assert report["stored_length"] == 2
        assert report["readable_count"] == 2
        assert report["orphan_indices"] == []
        # And the bounds themselves: the sibling's rows sort outside them.
        item_read = db.range_calls[0]
        assert item_read["lower"] == "list:output-0"
        assert item_read["upper"] == "list:output-:"
        assert not ("list:output_embeddings_0-0" <= item_read["upper"])

    def test_a_digit_suffixed_sibling_does_not_perturb_the_report(
        self, monkeypatch, fake_store
    ):
        """``foo-5``'s rows (``list:foo-5-0``) DO sort inside ``foo``'s
        bounds -- the hazard ``_v1_bounds()`` documents. The ``^\\d+$`` shape
        check on the suffix is what keeps them apart, and it is unchanged by
        this phase: the whole-partition dump contained ``list:foo-5-0`` too."""
        actor_id = "actor-digit-sibling"
        _seed_list(fake_store, actor_id, "foo", ["a", "b"])
        _seed_list(fake_store, actor_id, "foo-5", ["x", "y", "z"])
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        report = _list(fake_store, actor_id, "foo").verify()

        assert report["healthy"] is True
        assert report["missing_indices"] == []
        assert report["orphan_indices"] == []
        assert report["adjacent_duplicates"] == []


class TestTheThreeReadsAreStronglyConsistent:
    """Two of the three rewrite destructively from what they read:
    ``compact()`` writes survivors to ``0..n-1`` then deletes
    ``len(ordered_values)..highest_seen``, and ``migrate_to_v2()`` deletes v1
    rows ``0..highest_seen``. A row missed by a stale replica read is
    overwritten by its successor and its slot deleted -- silently, after
    which ``verify()`` reports ``healthy: true``. Once the read is scoped to
    one list, strong consistency costs ~6-13 RCU more, roughly 1% of what the
    scoping itself saved."""

    @pytest.mark.parametrize("method", CONVERTED_METHODS)
    def test_every_range_read_is_strongly_consistent(self, monkeypatch, method):
        store = {}
        actor_id, name = f"actor-cr-{method}", "notes"
        _seed_list(store, actor_id, name, ["a", "b", "c"])
        db = RangeSpyDb(store)
        _patch_get_property(monkeypatch, lambda config: db)

        getattr(_list(store, actor_id, name), method)()

        assert db.range_calls
        assert all(c["consistent_read"] is True for c in db.range_calls), (
            f"{method}() reads the input to a destructive rewrite: {db.range_calls}"
        )

    def test_no_call_site_in_these_methods_passes_a_non_literal_true(self):
        """An AST guard in the style of the handlers guard in
        ``test_v2_consistent_read.py``: ``consistent_read=False`` is the
        obvious spend, but ``consistent_read=some_flag`` is the quiet one."""
        tree = ast.parse(PROPERTY_LIST_PY.read_text(), filename=str(PROPERTY_LIST_PY))
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if node.name not in CONVERTED_METHODS:
                continue
            for inner in ast.walk(node):
                if not isinstance(inner, ast.Call):
                    continue
                for kw in inner.keywords:
                    if kw.arg not in ("consistent", "consistent_read"):
                        continue
                    if not (
                        isinstance(kw.value, ast.Constant) and kw.value.value is True
                    ):
                        offenders.append(f"{node.name}:{inner.lineno}")
        assert offenders == [], (
            f"the v1 maintenance methods must read strongly -- they feed "
            f"destructive rewrites: {offenders}"
        )


class TestAReadFaultNoLongerEmptiesTheList:
    """The strongest argument for the phase, and the easiest thing to lose in
    the edit. All three lines ended in ``or {}``, and PostgreSQL's
    ``fetch_all_including_lists`` returns ``None`` on a CAUGHT exception --
    so a transient read fault made ``compact()`` compute
    ``ordered_values = []``, delete rows ``0..stored_length-1`` and write
    ``length: 0``. ``get_range()`` raises ``DbError`` instead."""

    def test_compact_raises_and_leaves_every_row_intact(self, monkeypatch, fake_store):
        actor_id, name = "actor-fault-compact", "notes"
        _seed_list(fake_store, actor_id, name, ["a", "b", "c"])
        before = dict(fake_store)
        _patch_get_property(
            monkeypatch, lambda config: RangeSpyDb(fake_store, fail_range=True)
        )

        with pytest.raises(DbError):
            _list(fake_store, actor_id, name).compact()

        assert fake_store == before

    @pytest.mark.parametrize("method", CONVERTED_METHODS)
    def test_a_read_fault_propagates_from_all_three(self, monkeypatch, method):
        store = {}
        actor_id, name = f"actor-fault-{method}", "notes"
        _seed_list(store, actor_id, name, ["a", "b", "c"])
        before = dict(store)
        _patch_get_property(
            monkeypatch, lambda config: RangeSpyDb(store, fail_range=True)
        )

        with pytest.raises(DbError):
            getattr(_list(store, actor_id, name), method)()

        assert store == before


class TestTheReportIsUnchanged:
    """Correctness must be identical to the partition-dump version.
    ``orphan_indices`` is drawn from ``present``, already filtered by
    ``^list:{name}-(\\d+)$``, so no orphan shape exists outside the bounds;
    ``stored_length`` comes from ``_load_metadata()``, not from ``rows``."""

    def test_holes_orphans_and_adjacent_duplicates_all_still_report(
        self, monkeypatch, fake_store
    ):
        actor_id, name = "actor-report", "notes"
        _seed_list(fake_store, actor_id, name, ["a", "b", "b", "d", "e"])
        # Punch a hole at 3, and leave an orphan at 7 -- above stored_length.
        del fake_store[(actor_id, f"list:{name}-3")]
        fake_store[(actor_id, f"list:{name}-7")] = json.dumps("orphan")
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        report = _list(fake_store, actor_id, name).verify()

        assert report["stored_length"] == 5
        assert report["missing_indices"] == [3]
        assert report["orphan_indices"] == [7]
        assert report["adjacent_duplicates"] == [(1, 2)]
        assert report["readable_count"] == 4
        assert report["healthy"] is False

    def test_v2_residue_is_still_counted(self, monkeypatch, fake_store):
        """``foreign_format_rows`` used to be counted out of the dump. v2
        rows sort at ``#`` (0x23), BELOW ``_v1_bounds()``' lower bound
        ``list:{name}-0`` (0x30), so the scoped item read cannot see them --
        they now cost one extra keys-only range read, the exact mirror of
        what ``_v2_verify()`` already spends counting v1 residue."""
        actor_id, name = "actor-residue", "notes"
        _seed_list(fake_store, actor_id, name, ["a", "b"])
        import fractional_indexing as fi

        for rank in fi.generate_n_keys_between(None, None, 3):
            fake_store[(actor_id, f"list:{name}-#{rank}")] = json.dumps("residue")
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        report = _list(fake_store, actor_id, name).verify()

        assert report["foreign_format_rows"] == 3
        # An ordinary hole is absent, so the list is still "healthy" -- the
        # residue is reported separately, exactly as before.
        assert report["healthy"] is True


class TestLazyMigrationIsTheUserFacingBeneficiary:
    """``_maybe_lazy_migrate()`` calls ``verify()`` then ``migrate_to_v2()``
    (which calls ``verify()`` again) inside a user's ``append()``. That was
    three whole-partition dumps in one request. Off by default
    (``ACTINGWEB_LAZY_MIGRATION_MAX_LENGTH``), but it is the only user-facing
    caller, so the phase's tests have to cover it."""

    def test_an_append_that_triggers_migration_issues_only_scoped_reads(
        self, monkeypatch, fake_store
    ):
        monkeypatch.setenv("ACTINGWEB_LAZY_MIGRATION_MAX_LENGTH", "50")
        actor_id, name = "actor-lazy", "notes"
        _seed_list(fake_store, actor_id, name, ["a", "b", "c"])
        db = RangeSpyDb(fake_store)
        _patch_get_property(monkeypatch, lambda config: db)

        prop = _list(fake_store, actor_id, name)
        prop.append("d")

        assert db.range_calls, "the migration path must have read the list"
        for call in db.range_calls:
            assert call["lower"].startswith(f"list:{name}-"), call
            assert call["upper"].startswith(f"list:{name}-"), call
        # And it really did migrate, so this exercised the path under test.
        assert _list(fake_store, actor_id, name).to_list() == ["a", "b", "c", "d"]


class TestV2ListsAreUntouched:
    """The v2 paths already read scoped; this phase must not perturb them."""

    def test_v2_verify_still_reports_the_same_way(self, monkeypatch, fake_store):
        actor_id, name = "actor-v2-untouched", "notes"
        _seed_v2_list(fake_store, actor_id, name, ["a", "b", "c"])
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        report = _list(fake_store, actor_id, name).verify()

        assert report == {
            "format": 2,
            "length": 3,
            "max_rank_length": 2,
            "adjacent_duplicates": [],
            "foreign_format_rows": 0,
            "needs_rebalance": False,
            "count_hint": None,
            "count_hint_drift": None,
            "healthy": True,
            "duplicate_identities": None,
            "identity_checked_count": None,
        }
