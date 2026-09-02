"""A fully-loaded attribute bucket becomes authoritative.

Three changes, in dependency order, all inside ``actingweb/attribute.py``:

* **6a** — ``_bucket_loaded`` is set only when the backend actually returned
  a DICT. Otherwise "I could not read the bucket" becomes "the bucket has no
  such attribute", permanently, for the life of the instance.
* **6b** — ``set_attr()`` mirrors the backends' falsy delete. Both treat a
  falsy ``data`` as a delete and return ``True`` (``delete_attr()`` is
  literally ``set_attr(data=None)``), so caching an entry made the dict
  disagree with storage about presence -- and a dict knowingly wrong about
  presence cannot be authoritative about absence.
* **6c** — ``get_attr()`` honours the flag: a name absent from a loaded
  bucket returns ``None`` without a query, and stops polluting the bucket
  with keys that have no row.

The measured saving today is ZERO: no library call site pairs
``get_bucket()`` with ``get_attr()`` on one instance, and the miss was
already negatively cached, so only the FIRST lookup per absent name ever
cost anything. The argument is the contract -- ``InternalStore``, held for
an ``Actor``'s lifetime, already loads the bucket once and thereafter reads
its own ``__dict__``, which is the same bypass a consumer wrote a seven-line
comment to justify.
"""

import pytest

from actingweb.attribute import Attributes, InternalStore


class CountingBackend:
    """A dict-backed DbAttribute, counting every backend call.

    ``get_bucket`` can be told to fault. Both real backends return ``None``
    for a CAUGHT exception and ``{}`` for an empty bucket (PostgreSQL since
    3.14.4) -- ``empty_returns=None`` models a fault that arrives on the
    empty path.
    """

    def __init__(self, rows=None, fault=False, empty_returns={}):  # noqa: B006
        self.rows = dict(rows or {})
        self.fault = fault
        # PostgreSQL's falsy set_attr() returns False on a caught exception;
        # the row then survives. Models a failed delete.
        self.fail_deletes = False
        self.empty_returns = empty_returns
        self.get_bucket_calls = 0
        self.get_attr_calls: list[object] = []
        self.set_attr_calls: list[tuple[object, object]] = []

    def get_bucket(self, actor_id=None, bucket=None):
        self.get_bucket_calls += 1
        if self.fault:
            return None
        if not self.rows:
            return self.empty_returns
        return {k: dict(v) for k, v in self.rows.items()}

    def get_attr(self, actor_id=None, bucket=None, name=None):
        self.get_attr_calls.append(name)
        row = self.rows.get(name)
        return dict(row) if row is not None else None

    def set_attr(
        self,
        actor_id=None,
        bucket=None,
        name=None,
        data=None,
        timestamp=None,
        ttl_seconds=None,
    ):
        self.set_attr_calls.append((name, data))
        if not data:
            if self.fail_deletes:
                return False
            self.rows.pop(name, None)
        else:
            self.rows[name] = {"data": data, "timestamp": timestamp}
        return True

    def delete_attr(self, actor_id=None, bucket=None, name=None):
        return self.set_attr(actor_id=actor_id, bucket=bucket, name=name, data=None)

    def delete_bucket(self, actor_id=None, bucket=None):
        self.rows.clear()
        return True


def _attrs(monkeypatch, backend, bucket="b"):
    monkeypatch.setattr("actingweb.attribute.get_attribute", lambda config: backend)
    return Attributes(actor_id="actor1", bucket=bucket, config=object())


def _row(value):
    return {"data": value, "timestamp": None}


def _loaded(attrs) -> dict:
    """get_bucket() narrowed to a dict — it is Optional in the protocol."""
    bucket = attrs.get_bucket()
    assert bucket is not None
    return bucket


class TestAFaultedLoadIsNotAuthoritative:
    """6a. Fails before this phase: the flag was set unconditionally, so one
    faulted load turned every later miss into a permanent 'absent'."""

    def test_a_faulting_backend_leaves_the_flag_unset(self, monkeypatch):
        backend = CountingBackend(fault=True)
        attrs = _attrs(monkeypatch, backend)

        assert attrs.get_bucket() == {}
        assert attrs._bucket_loaded is False

    def test_get_attr_still_reads_through_after_a_faulted_load(self, monkeypatch):
        backend = CountingBackend({"present": _row("v")}, fault=True)
        attrs = _attrs(monkeypatch, backend)

        attrs.get_bucket()
        result = attrs.get_attr("present")

        assert backend.get_attr_calls == ["present"]
        assert result == _row("v")

    def test_a_later_successful_load_sets_the_flag(self, monkeypatch):
        backend = CountingBackend({"a": _row(1)}, fault=True)
        attrs = _attrs(monkeypatch, backend)

        attrs.get_bucket()
        assert attrs._bucket_loaded is False

        backend.fault = False
        assert attrs.get_bucket() == {"a": _row(1)}
        assert attrs._bucket_loaded is True


class TestEmptyIsAuthoritativeAndNoneIsAFault:
    """Both backends return ``{}`` for an empty bucket and reserve ``None``
    for a caught exception (the 3.14.4 contract; before it PostgreSQL also
    returned ``None`` for empty, so an empty bucket was never trusted
    there)."""

    def test_an_empty_bucket_is_trusted(self, monkeypatch):
        backend = CountingBackend({}, empty_returns={})
        attrs = _attrs(monkeypatch, backend)

        assert attrs.get_bucket() == {}
        assert attrs._bucket_loaded is True
        assert attrs.get_attr("anything") is None
        assert backend.get_attr_calls == [], "an empty bucket costs nothing"

    def test_a_none_return_is_a_fault_and_is_not_trusted(self, monkeypatch):
        backend = CountingBackend({}, empty_returns=None)
        attrs = _attrs(monkeypatch, backend)

        assert attrs.get_bucket() == {}
        assert attrs._bucket_loaded is False
        assert attrs.get_attr("anything") is None
        assert backend.get_attr_calls == ["anything"], (
            "a bucket that could not be read must not become "
            "'the bucket has no such attribute'"
        )


class TestALoadedBucketIsAuthoritative:
    """6c."""

    def test_an_absent_name_costs_no_backend_call(self, monkeypatch):
        backend = CountingBackend({"present": _row("v")})
        attrs = _attrs(monkeypatch, backend)

        attrs.get_bucket()
        assert attrs.get_attr("absent") is None
        assert backend.get_attr_calls == []

    def test_a_present_name_is_served_from_the_loaded_dict(self, monkeypatch):
        backend = CountingBackend({"present": _row("v")})
        attrs = _attrs(monkeypatch, backend)

        attrs.get_bucket()
        assert attrs.get_attr("present") == _row("v")
        assert backend.get_attr_calls == []

    def test_get_attr_no_longer_pollutes_the_loaded_bucket(self, monkeypatch):
        """Fails before this phase. ``get_attr()`` cached ``None`` on a miss
        and ``get_bucket()`` returns ``self.data`` BY IDENTITY, so a loaded
        bucket grew keys with no stored row."""
        backend = CountingBackend({"present": _row("v")})
        attrs = _attrs(monkeypatch, backend)

        first = _loaded(attrs)
        attrs.get_attr("absent")
        second = _loaded(attrs)

        assert "absent" not in second
        assert "absent" not in first, "same dict, returned by identity"
        assert set(second) == {"present"}

    def test_without_a_loaded_bucket_the_read_through_is_unchanged(self, monkeypatch):
        backend = CountingBackend({"present": _row("v")})
        attrs = _attrs(monkeypatch, backend)

        assert attrs.get_attr("present") == _row("v")
        assert attrs.get_attr("absent") is None
        assert backend.get_attr_calls == ["present", "absent"]
        # The negative cache still works: a second miss costs nothing.
        assert attrs.get_attr("absent") is None
        assert backend.get_attr_calls == ["present", "absent"]


class TestSetAttrMirrorsTheBackendsDelete:
    """6b. Both backends treat a falsy ``data`` as a delete and return
    ``True``; ``delete_attr()`` IS ``set_attr(data=None)``."""

    @pytest.mark.parametrize("falsy", [None, {}, [], "", 0, False])
    def test_a_falsy_write_leaves_the_name_absent(self, monkeypatch, falsy):
        backend = CountingBackend({"a": _row("v")})
        attrs = _attrs(monkeypatch, backend)
        attrs.get_bucket()

        assert attrs.set_attr("a", data=falsy) is True

        assert "a" not in attrs.data
        assert "a" not in backend.rows
        # And the loaded bucket now agrees with storage about absence.
        before = len(backend.get_attr_calls)
        assert attrs.get_attr("a") is None
        assert len(backend.get_attr_calls) == before

    @pytest.mark.parametrize("falsy", [None, {}, [], "", 0, False])
    def test_a_falsy_write_on_an_unloaded_bucket_also_drops_it(
        self, monkeypatch, falsy
    ):
        backend = CountingBackend({"a": _row("v")})
        attrs = _attrs(monkeypatch, backend)

        assert attrs.set_attr("a", data=falsy) is True

        assert "a" not in attrs.data
        assert "a" not in backend.rows

    def test_a_truthy_write_still_caches_and_stores(self, monkeypatch):
        backend = CountingBackend()
        attrs = _attrs(monkeypatch, backend)
        attrs.get_bucket()

        assert attrs.set_attr("a", data={"x": 1}) is True

        cached = attrs.data["a"]
        assert cached is not None
        assert cached["data"] == {"x": 1}
        assert backend.rows["a"]["data"] == {"x": 1}
        assert attrs.get_attr("a") == attrs.data["a"]

    def test_delete_attr_leaves_the_flag_set_and_the_name_absent(self, monkeypatch):
        backend = CountingBackend({"a": _row("v"), "b": _row("w")})
        attrs = _attrs(monkeypatch, backend)
        attrs.get_bucket()

        assert attrs.delete_attr("a") is True

        assert attrs._bucket_loaded is True
        assert set(_loaded(attrs)) == {"b"}
        before = len(backend.get_attr_calls)
        assert attrs.get_attr("a") is None
        assert len(backend.get_attr_calls) == before

    @pytest.mark.parametrize("via", ["delete_attr", "set_attr"])
    def test_a_failed_delete_does_not_leave_a_stale_authoritative_miss(
        self, monkeypatch, via
    ):
        """Codex P2 on PR #139. The cache entry goes BEFORE the backend
        call; if the backend then reports failure the row still exists, and
        a loaded bucket must not go on asserting its absence. Before the
        bucket was authoritative the cache miss point-read and recovered the
        value -- this pins that it still does."""
        backend = CountingBackend({"a": _row("v"), "b": _row("w")})
        attrs = _attrs(monkeypatch, backend)
        attrs.get_bucket()
        backend.fail_deletes = True

        if via == "delete_attr":
            assert attrs.delete_attr("a") is False
        else:
            assert attrs.set_attr("a", data=None) is False

        assert "a" in backend.rows
        assert attrs._bucket_loaded is False
        got = attrs.get_attr("a")
        assert got is not None
        assert got["data"] == "v"
        assert backend.get_attr_calls == ["a"]
        # And a following get_bucket() re-reads rather than serving the dict.
        assert set(_loaded(attrs)) == {"a", "b"}
        assert backend.get_bucket_calls == 2

    def test_a_confirmed_delete_keeps_the_bucket_authoritative(self, monkeypatch):
        backend = CountingBackend({"a": _row("v")})
        attrs = _attrs(monkeypatch, backend)
        attrs.get_bucket()

        assert attrs.set_attr("a", data=None) is True

        assert attrs._bucket_loaded is True

    def test_a_stored_null_is_still_distinguishable_from_absence(self, monkeypatch):
        """A stored row holding ``null`` reads back as the TRUTHY dict
        ``{"data": None, ...}``; absence is ``None``. The two must not
        collapse, or "present but unset" becomes "not there"."""
        backend = CountingBackend({"nullish": _row(None)})
        attrs = _attrs(monkeypatch, backend)

        loaded = _loaded(attrs)

        assert loaded["nullish"] == {"data": None, "timestamp": None}
        assert attrs.get_attr("nullish") == {"data": None, "timestamp": None}
        assert attrs.get_attr("truly-absent") is None
        assert attrs.get_attr("nullish") is not None


class TestInternalStoreIsUnchanged:
    """``InternalStore`` loads the bucket once and thereafter reads its own
    ``__dict__`` -- the bypass this phase makes unnecessary. Its observable
    behaviour must not move."""

    def _store(self, monkeypatch, backend):
        monkeypatch.setattr("actingweb.attribute.get_attribute", lambda config: backend)
        return InternalStore(actor_id="actor1", config=object(), bucket="_internal")

    def test_reads_and_writes_round_trip(self, monkeypatch):
        backend = CountingBackend({"existing": _row("v")})
        store = self._store(monkeypatch, backend)

        assert store.existing == "v"
        assert store.missing is None

        store.fresh = {"x": 1}
        assert store.fresh == {"x": 1}
        assert backend.rows["fresh"]["data"] == {"x": 1}

    def test_a_none_write_deletes(self, monkeypatch):
        backend = CountingBackend({"gone": _row("v")})
        store = self._store(monkeypatch, backend)

        store.gone = None

        assert store.gone is None
        assert "gone" not in backend.rows

    def test_the_bucket_is_loaded_exactly_once(self, monkeypatch):
        backend = CountingBackend({"a": _row(1), "b": _row(2)})
        store = self._store(monkeypatch, backend)

        assert store.a == 1
        assert store.b == 2
        assert store.absent is None

        assert backend.get_bucket_calls == 1
        assert backend.get_attr_calls == []

    def test_a_faulted_load_does_not_freeze_the_store_empty(self, monkeypatch):
        """InternalStore has its own ``_loaded`` latch, so a faulted load
        still leaves it looking empty for this instance -- unchanged by this
        phase, and recorded so the difference from ``Attributes`` is not
        mistaken for a regression here. A fresh store re-reads."""
        backend = CountingBackend({"a": _row(1)}, fault=True)
        store = self._store(monkeypatch, backend)

        assert store.a is None

        backend.fault = False
        assert self._store(monkeypatch, backend).a == 1
