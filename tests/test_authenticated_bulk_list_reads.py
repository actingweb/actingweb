"""``AuthenticatedPropertyListStore``'s bulk list readers.

Before this, ``authed.property_lists.list_all_with_rows()`` fell through
``__getattr__``, which permission-checked the *method name* as a list name --
which PASSES, since an unmatched target evaluates to ``NOT_FOUND`` and only
``DENIED`` raises -- and returned a ``_PermissionEnforcingListView`` wrapping
a bound method. Calling it raised ``TypeError``. That is verbatim the bug the
class already documents about its own removed ``create()`` and its fixed
``delete()``.

**The obvious repair is the hazard.** Fixing ``__getattr__`` as "if the name
resolves to a method on ``self._store``, return it" would hand a
permission-scoped accessor the UNAUTHENTICATED store's bound
``list_all_with_rows()`` -- a full unfiltered partition dump. That converts a
``TypeError`` into a read bypass. So the three readers are defined explicitly
and ``__getattr__`` raises ``AttributeError`` on a method-name collision
rather than choosing either interpretation.
"""

import json
import logging
from unittest.mock import Mock, patch

import pytest

from actingweb.db.exceptions import DbError
from actingweb.interface.authenticated_views import (
    _PROPERTY_LIST_STORE_METHOD_NAMES,
    AuthContext,
    AuthenticatedPropertyListStore,
)
from actingweb.permission_evaluator import PermissionResult

PATCH_TARGET = "actingweb.interface.authenticated_views.get_permission_evaluator"


def _v1_rows(name, items):
    rows = {f"list:{name}-meta": json.dumps({"length": len(items)})}
    for i, item in enumerate(items):
        rows[f"list:{name}-{i}"] = json.dumps(item)
    return rows


def _v2_rows(name, items):
    import fractional_indexing as fi

    rows = {f"list:{name}-meta": json.dumps({"format": 2})}
    ranks = fi.generate_n_keys_between(None, None, len(items))
    for rank, item in zip(ranks, items, strict=True):
        rows[f"list:{name}-#{rank}"] = json.dumps(item)
    return rows


class FakeListStore:
    """Stands in for the unauthenticated ``PropertyListStore``."""

    def __init__(self, lists, prefix_error=None):
        self.lists = lists  # {name: rows dict}
        self.prefix_error = prefix_error
        self.prefix_calls: list[str] = []

    def list_all(self):
        return list(self.lists)

    def list_all_with_rows(self):
        rows = {}
        for list_rows in self.lists.values():
            rows.update(list_rows)
        return list(self.lists), rows

    def list_prefix_with_rows(self, prefix):
        self.prefix_calls.append(prefix)
        if self.prefix_error is not None:
            raise self.prefix_error
        if not prefix:
            raise ValueError("needs a non-empty prefix")
        names = [n for n in self.lists if n.startswith(prefix)]
        rows = {}
        for name in names:
            rows.update(self.lists[name])
        return names, rows

    def exists(self, name):
        return name in self.lists


def _evaluator(mock_get_evaluator, by_name, raise_on_call=False):
    """Patch get_permission_evaluator with a bulk evaluator resolving each
    name through ``by_name`` (a dict or a callable)."""
    resolver = by_name if callable(by_name) else by_name.get

    def evaluate_bulk(actor_id, accessor_id, property_paths, operation):
        if raise_on_call:
            raise RuntimeError("permission store unreachable")
        return {
            path: resolver(path) or PermissionResult.NOT_FOUND
            for path in property_paths
        }

    evaluator = Mock()
    evaluator.evaluate_bulk_property_access = Mock(side_effect=evaluate_bulk)
    mock_get_evaluator.return_value = evaluator
    return evaluator


def _authed(store, accessor_id="peer123"):
    return AuthenticatedPropertyListStore(
        store, AuthContext(peer_id=accessor_id), "actor123", Mock()
    )


class TestTheReadersAreCallableAtAll:
    """Fails today with TypeError -- ``__getattr__`` returned a view
    wrapping a bound method."""

    def test_list_all_with_rows_returns_data(self):
        store = FakeListStore({"notes": _v1_rows("notes", ["a", "b"])})
        with patch(PATCH_TARGET) as m:
            _evaluator(m, {"notes": PermissionResult.ALLOWED})
            names, rows = _authed(store).list_all_with_rows()

        assert names == ["notes"]
        assert rows == _v1_rows("notes", ["a", "b"])

    def test_list_all_returns_data(self):
        store = FakeListStore({"notes": _v1_rows("notes", ["a"])})
        with patch(PATCH_TARGET) as m:
            _evaluator(m, {"notes": PermissionResult.ALLOWED})
            assert _authed(store).list_all() == ["notes"]

    def test_list_prefix_with_rows_returns_data(self):
        store = FakeListStore(
            {
                "memory_a": _v1_rows("memory_a", ["x"]),
                "notes": _v1_rows("notes", ["y"]),
            }
        )
        with patch(PATCH_TARGET) as m:
            _evaluator(m, {"memory_a": PermissionResult.ALLOWED})
            names, rows = _authed(store).list_prefix_with_rows("memory_")

        assert names == ["memory_a"]
        assert store.prefix_calls == ["memory_"]
        assert not any(n.startswith("list:notes") for n in rows)

    def test_all_three_are_defined_not_inherited_from_getattr(self):
        """Shipping only the scoped one would leave the documented API a
        latent TypeError."""
        for name in ("list_all", "list_all_with_rows", "list_prefix_with_rows"):
            assert name in vars(AuthenticatedPropertyListStore), name


class TestNoMethodNameEverResolvesToTheStore:
    """The bypass guard. Asserted directly, because the dangerous repair
    (return `getattr(self._store, name)`) also makes the tests above pass."""

    @pytest.mark.parametrize("name", sorted(_PROPERTY_LIST_STORE_METHOD_NAMES))
    def test_a_colliding_name_raises_attribute_error(self, name):
        store = FakeListStore({})
        authed = _authed(store)
        if name in vars(AuthenticatedPropertyListStore):
            # Defined here, so __getattr__ is never consulted for it.
            assert callable(getattr(authed, name))
            return
        with pytest.raises(AttributeError):
            getattr(authed, name)

    def test_the_collision_set_tracks_both_stores(self):
        """Hand-listing these would rot: a method added to either store
        must land in the set without anyone remembering."""
        from actingweb.interface.property_store import (
            PropertyListStore as WrappedStore,
        )
        from actingweb.property import PropertyListStore as CoreStore

        for cls in (CoreStore, WrappedStore):
            for attr in vars(cls):
                if not attr.startswith("_"):
                    assert attr in _PROPERTY_LIST_STORE_METHOD_NAMES, (cls, attr)

    def test_nothing_unwrapped_from_the_store_is_ever_returned(self):
        """A sentinel on the unauthenticated store: if __getattr__ ever
        resolves to it, this catches the bypass whatever its shape."""
        sentinel = object()
        store = FakeListStore({})
        store.list_all_with_rows = sentinel  # type: ignore[assignment]

        authed = _authed(store)
        with pytest.raises(AttributeError):
            object.__getattribute__(authed, "__getattr__")("list_all_with_rows")


class TestDeniedListsAreRemovedFromBothHalves:
    def test_a_denied_list_appears_in_neither_names_nor_rows(self):
        store = FakeListStore(
            {
                "public": _v1_rows("public", ["p"]),
                "secret": _v1_rows("secret", ["s"]),
            }
        )
        with patch(PATCH_TARGET) as m:
            _evaluator(
                m,
                {
                    "public": PermissionResult.ALLOWED,
                    "secret": PermissionResult.DENIED,
                },
            )
            names, rows = _authed(store).list_all_with_rows()

        assert names == ["public"]
        assert not any("secret" in n for n in rows)

    def test_not_found_is_treated_as_allowed(self):
        """Matching ``_check_permission()``, which denies only on DENIED,
        and ``handlers/properties.py``'s bulk filter."""
        store = FakeListStore({"unmatched": _v1_rows("unmatched", ["x"])})
        with patch(PATCH_TARGET) as m:
            _evaluator(m, {"unmatched": PermissionResult.NOT_FOUND})
            names, rows = _authed(store).list_all_with_rows()

        assert names == ["unmatched"]
        assert rows == _v1_rows("unmatched", ["x"])

    def test_bulk_filtering_agrees_with_n_individual_reads(self):
        names = ["a_allowed", "b_denied", "c_notfound"]
        perms = {
            "a_allowed": PermissionResult.ALLOWED,
            "b_denied": PermissionResult.DENIED,
            "c_notfound": PermissionResult.NOT_FOUND,
        }
        store = FakeListStore({n: _v1_rows(n, ["x"]) for n in names})

        with patch(PATCH_TARGET) as m:
            evaluator = _evaluator(m, perms)
            evaluator.evaluate_property_access = Mock(
                side_effect=lambda a, p, n, op: perms[n]
            )
            authed = _authed(store)
            bulk, _rows = authed.list_all_with_rows()

            individually = []
            for name in names:
                try:
                    authed._check_permission(name, "read")
                    individually.append(name)
                except Exception:
                    pass

        assert bulk == individually == ["a_allowed", "c_notfound"]

    def test_one_bulk_call_not_one_per_name(self):
        store = FakeListStore({f"l{i}": _v1_rows(f"l{i}", ["x"]) for i in range(5)})
        with patch(PATCH_TARGET) as m:
            evaluator = _evaluator(m, lambda n: PermissionResult.ALLOWED)
            _authed(store).list_all_with_rows()

        assert evaluator.evaluate_bulk_property_access.call_count == 1

    def test_an_owner_context_is_not_filtered(self):
        """No accessor id means owner access -- the same short-circuit
        ``_check_permission()`` makes."""
        store = FakeListStore({"secret": _v1_rows("secret", ["s"])})
        authed = AuthenticatedPropertyListStore(
            store, AuthContext(), "actor123", Mock()
        )

        names, rows = authed.list_all_with_rows()

        assert names == ["secret"]
        assert rows == _v1_rows("secret", ["s"])


class TestASiblingKeepsAllOfItsRows:
    """The test that fails under a bare ``startswith`` prune, in both
    storage formats. Pruning ``list:foo-`` for denied ``foo`` also strips
    permitted ``foo-old``'s ITEM rows while leaving its ``-meta`` row, and
    ``to_list_from_rows()`` then reports ``foo-old`` as empty -- a
    permitted list silently emptied, with nothing raised."""

    @pytest.mark.parametrize("seed", [_v1_rows, _v2_rows], ids=["v1", "v2"])
    def test_the_permitted_sibling_survives_intact(self, seed):
        store = FakeListStore(
            {"foo": seed("foo", ["a", "b"]), "foo-old": seed("foo-old", ["p", "q"])}
        )
        with patch(PATCH_TARGET) as m:
            _evaluator(
                m,
                {
                    "foo": PermissionResult.DENIED,
                    "foo-old": PermissionResult.ALLOWED,
                },
            )
            names, rows = _authed(store).list_all_with_rows()

        assert names == ["foo-old"]
        assert rows == seed("foo-old", ["p", "q"])
        assert not any(n in seed("foo", ["a", "b"]) for n in rows)

    @pytest.mark.parametrize("seed", [_v1_rows, _v2_rows], ids=["v1", "v2"])
    def test_the_survivor_reads_as_its_real_contents_not_empty(self, seed, monkeypatch):
        from actingweb.property_list import ListProperty

        store = FakeListStore(
            {"foo": seed("foo", ["a", "b"]), "foo-old": seed("foo-old", ["p", "q"])}
        )
        all_rows = {n: v for lr in store.lists.values() for n, v in lr.items()}

        class _RowBackedDb:
            def get(self, actor_id=None, name=None):
                return all_rows.get(name)

        monkeypatch.setattr(
            "actingweb.property_list.get_property", lambda config: _RowBackedDb()
        )
        with patch(PATCH_TARGET) as m:
            _evaluator(
                m,
                {
                    "foo": PermissionResult.DENIED,
                    "foo-old": PermissionResult.ALLOWED,
                },
            )
            _names, rows = _authed(store).list_all_with_rows()

        prop = ListProperty(actor_id="actor123", name="foo-old", config=object())
        assert prop.to_list_from_rows(rows) == ["p", "q"]


class TestFailureModes:
    def test_an_evaluator_exception_yields_empty_not_partial(self):
        store = FakeListStore(
            {
                "a": _v1_rows("a", ["x"]),
                "b": _v1_rows("b", ["y"]),
            }
        )
        with patch(PATCH_TARGET) as m:
            _evaluator(m, {}, raise_on_call=True)
            authed = _authed(store)

            assert authed.list_all_with_rows() == ([], {})
            assert authed.list_all() == []
            assert authed.list_prefix_with_rows("a") == ([], {})

    def test_a_get_evaluator_failure_also_yields_empty(self):
        store = FakeListStore({"a": _v1_rows("a", ["x"])})
        with patch(PATCH_TARGET, side_effect=RuntimeError("no config")):
            assert _authed(store).list_all_with_rows() == ([], {})

    def test_no_denied_name_reaches_a_message_or_this_modules_log(self, caplog):
        """Scoped to this module's logger on purpose:
        ``evaluate_bulk_property_access`` logs denied names itself, at
        WARNING, under ``actingweb.permission_evaluator``. That is
        owner-side volume, not disclosure. What must never happen is this
        code re-emitting a name it learned from STORAGE -- in the
        single-list path the name came from the caller, here it did not."""
        store = FakeListStore({"top-secret-list": _v1_rows("top-secret-list", ["s"])})
        with (
            patch(PATCH_TARGET) as m,
            caplog.at_level(
                logging.DEBUG, logger="actingweb.interface.authenticated_views"
            ),
        ):
            _evaluator(m, {"top-secret-list": PermissionResult.DENIED})
            names, rows = _authed(store).list_all_with_rows()

        assert (names, rows) == ([], {})
        emitted = [
            r.getMessage()
            for r in caplog.records
            if r.name == "actingweb.interface.authenticated_views"
        ]
        assert not any("top-secret-list" in msg for msg in emitted), emitted

    def test_an_evaluator_error_names_the_actor_not_the_lists(self, caplog):
        store = FakeListStore({"top-secret-list": _v1_rows("top-secret-list", ["s"])})
        with (
            patch(PATCH_TARGET) as m,
            caplog.at_level(
                logging.DEBUG, logger="actingweb.interface.authenticated_views"
            ),
        ):
            _evaluator(m, {}, raise_on_call=True)
            _authed(store).list_all_with_rows()

        emitted = [
            r.getMessage()
            for r in caplog.records
            if r.name == "actingweb.interface.authenticated_views"
        ]
        assert emitted, "a permission-system error must be logged owner-side"
        assert not any("top-secret-list" in msg for msg in emitted)

    def test_value_error_and_db_error_propagate_through_the_scoped_reader(self):
        """Neither is a permission outcome, and both would be
        indistinguishable from 'you may read nothing here' if swallowed."""
        with patch(PATCH_TARGET) as m:
            _evaluator(m, lambda n: PermissionResult.ALLOWED)

            with pytest.raises(ValueError):
                _authed(FakeListStore({})).list_prefix_with_rows("")

            faulting = FakeListStore({}, prefix_error=DbError("prefix read", "a"))
            with pytest.raises(DbError):
                _authed(faulting).list_prefix_with_rows("memory_")
