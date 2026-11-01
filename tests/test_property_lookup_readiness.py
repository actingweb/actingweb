"""Reverse-lookup readiness: the startup check and the four backend functions.

``ActingWebApp.check_ready()`` refuses a store whose properties hold data but
whose indexed names carry no backfill-complete marker, names the command that
fixes it, and records the indexed-name set. The probe logic is tested against
an in-memory backend (same four functions as the real ones); the real
functions are tested against whichever backend ``DATABASE_BACKEND`` selects.
"""

from __future__ import annotations

import os
import threading
import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest

from actingweb.db.exceptions import DbError
from actingweb.interface import (
    ActingWebApp,
    PropertyLookupNotReady,
    StoreNotReady,
    UniqueCreatorNotReady,
)
from actingweb.maintenance import property_lookup as command

# The recorded name set is one shared row per store: tests that write it run
# in one xdist group so parallel workers do not overwrite each other's set.
pytestmark = [
    pytest.mark.usefixtures("real_lookup_probe", "real_unique_probe"),
    pytest.mark.xdist_group(name="property_lookup_markers"),
]


class FakeBackend:
    """The four readiness functions over a dict, with call counts."""

    def __init__(self) -> None:
        self.marked: set[str] = set()
        self.recorded: set[str] | None = None
        self.reads = 0
        self.mark_calls: list[list[str]] = []
        self.record_calls: list[list[str]] = []
        self.read_error: Exception | None = None

    def read_readiness(self, names: list[str]) -> tuple[set[str], set[str] | None]:
        self.reads += 1
        if self.read_error is not None:
            raise self.read_error
        return set(self.marked), None if self.recorded is None else set(self.recorded)

    def mark_backfilled(self, names: list[str]) -> None:
        self.mark_calls.append(list(names))
        self.marked |= set(names)

    def unmark(self, names: list[str]) -> None:
        self.marked -= set(names)

    def record_configured(self, names: list[str]) -> None:
        self.record_calls.append(list(names))
        self.recorded = set(names)


@pytest.fixture
def store() -> Iterator[SimpleNamespace]:
    """A fake lookup backend and a switchable 'properties table is empty'."""
    backend = FakeBackend()
    state = SimpleNamespace(backend=backend, empty=False)
    with (
        mock.patch.object(command, "lookup_backend", return_value=backend),
        mock.patch.object(
            command, "properties_table_empty", side_effect=lambda database: state.empty
        ),
    ):
        yield state


def _app(*, indexed: list[str] | None = None) -> ActingWebApp:
    app = ActingWebApp(
        aw_type="urn:actingweb:test:readiness",
        database=os.getenv("DATABASE_BACKEND", "dynamodb"),
        fqdn="test.example.com",
    ).with_unique_creator(enable=False)
    if indexed is not None:
        app.with_indexed_properties(indexed)
    return app


def _check(app: ActingWebApp) -> None:
    """``check_ready()`` without the DynamoDB pre-warm."""
    with mock.patch.object(ActingWebApp, "_prewarm_dynamodb_tables"):
        app.check_ready()


class TestProbe:
    def test_data_without_markers_refuses(self, store: SimpleNamespace) -> None:
        with pytest.raises(PropertyLookupNotReady) as raised:
            _check(_app(indexed=["email", "oauthId"]))
        message = str(raised.value)
        assert "email" in message and "oauthId" in message
        assert "actingweb-property-lookup backfill --apply" in message
        assert "with_indexed_properties([])" in message
        assert store.backend.mark_calls == []

    def test_marked_names_pass_and_the_set_is_recorded_once(
        self, store: SimpleNamespace
    ) -> None:
        store.backend.marked = {"email", "oauthId"}
        _check(_app(indexed=["email", "oauthId"]))
        assert store.backend.record_calls == [["email", "oauthId"]]
        # A second start with the same set writes nothing.
        _check(_app(indexed=["email", "oauthId"]))
        assert store.backend.record_calls == [["email", "oauthId"]]
        assert store.backend.mark_calls == []

    def test_markers_without_a_recorded_set_pass_and_record_it(
        self, store: SimpleNamespace
    ) -> None:
        """The state ``mark-complete`` or the 3.13 backfill left behind."""
        store.backend.marked = {"email"}
        store.backend.recorded = None
        _check(_app(indexed=["email"]))
        assert store.backend.record_calls == [["email"]]

    def test_an_empty_properties_table_marks_itself_ready(
        self, store: SimpleNamespace
    ) -> None:
        store.empty = True
        _check(_app(indexed=["email", "oauthId"]))
        assert store.backend.marked == {"email", "oauthId"}
        assert store.backend.recorded == {"email", "oauthId"}

    def test_a_name_added_after_the_markers_refuses_until_marked(
        self, store: SimpleNamespace
    ) -> None:
        store.backend.marked = {"email"}
        store.backend.recorded = {"email"}
        with pytest.raises(PropertyLookupNotReady) as raised:
            _check(_app(indexed=["email", "slackId"]))
        assert "slackId" in str(raised.value)
        # What 'backfill --apply' leaves behind: the marker and the set.
        store.backend.marked.add("slackId")
        store.backend.recorded = {"email", "slackId"}
        _check(_app(indexed=["email", "slackId"]))
        assert store.backend.recorded == {"email", "slackId"}

    def test_a_name_dropped_for_a_deploy_and_restored_refuses(
        self, store: SimpleNamespace
    ) -> None:
        """D16: its values written while it was unindexed have no lookup row."""
        store.backend.marked = {"email", "oauthId"}
        store.backend.recorded = {"email", "oauthId"}
        _check(_app(indexed=["email"]))  # oauthId dropped: set recorded as {email}
        assert store.backend.recorded == {"email"}
        with pytest.raises(PropertyLookupNotReady) as raised:
            _check(_app(indexed=["email", "oauthId"]))  # restored, still marked
        assert "oauthId" in str(raised.value)

    def test_no_indexed_names_reads_nothing(self, store: SimpleNamespace) -> None:
        _check(_app(indexed=[]))
        assert store.backend.reads == 0
        assert store.backend.record_calls == []

    def test_a_read_fault_says_it_could_not_be_checked(
        self, store: SimpleNamespace
    ) -> None:
        store.backend.read_error = DbError("property lookup readiness read")
        with pytest.raises(PropertyLookupNotReady) as raised:
            _check(_app(indexed=["email"]))
        message = str(raised.value)
        assert "could not be checked" in message
        assert "with_indexed_properties([])" in message

    def test_a_missing_table_names_it(self, store: SimpleNamespace) -> None:
        store.backend.read_error = DbError("lookup table missing: x_property_lookup_v2")
        with pytest.raises(PropertyLookupNotReady) as raised:
            _check(_app(indexed=["email"]))
        assert "x_property_lookup_v2" in str(
            raised.value
        ) or "x_property_lookup_v2" in str(raised.value.__cause__)

    def test_it_runs_once_per_instance(self, store: SimpleNamespace) -> None:
        store.backend.marked = {"email"}
        app = _app(indexed=["email"])
        _check(app)
        _check(app)
        _check(app)
        assert store.backend.reads == 1

    def test_a_refusal_is_not_cached(self, store: SimpleNamespace) -> None:
        app = _app(indexed=["email"])
        with pytest.raises(PropertyLookupNotReady):
            _check(app)
        store.backend.marked = {"email"}
        _check(app)  # fixed by the operator; the same instance now passes

    def test_a_standalone_check_ready_prewarms_first(
        self, store: SimpleNamespace
    ) -> None:
        store.backend.marked = {"email"}
        order: list[str] = []
        app = _app(indexed=["email"])
        with mock.patch.object(
            ActingWebApp,
            "_prewarm_dynamodb_tables",
            side_effect=lambda: order.append("prewarm"),
        ):
            with mock.patch.object(
                command,
                "settle",
                side_effect=lambda config: (
                    order.append("probe")
                    or command.Readiness(["email"], {"email"}, {"email"})
                ),
            ):
                app.check_ready()
        assert order == ["prewarm", "probe"]


class TestBothRefusals:
    def _creator_refuses(self) -> Any:
        return mock.patch(
            "actingweb.maintenance.unique_creators.missing_enforcement",
            return_value="the DynamoDB table x_creators does not exist",
        )

    def test_both_refusing_raise_one_store_not_ready_with_both_messages(
        self, store: SimpleNamespace
    ) -> None:
        app = _app(indexed=["email"]).with_unique_creator(enable=True)
        with self._creator_refuses():
            with pytest.raises(StoreNotReady) as raised:
                _check(app)
        assert type(raised.value) is StoreNotReady
        message = str(raised.value)
        assert "actingweb-property-lookup" in message
        assert "actingweb-unique-creators" in message

    def test_a_single_refusal_keeps_its_own_type(self, store: SimpleNamespace) -> None:
        app = _app(indexed=["email"]).with_unique_creator(enable=True)
        store.backend.marked = {"email"}
        with self._creator_refuses():
            with pytest.raises(UniqueCreatorNotReady):
                _check(app)
        store.backend.marked = set()
        with pytest.raises(PropertyLookupNotReady):
            _check(_app(indexed=["email"]))

    def test_the_specific_classes_are_store_not_ready(self) -> None:
        assert issubclass(UniqueCreatorNotReady, StoreNotReady)
        assert issubclass(PropertyLookupNotReady, StoreNotReady)
        assert issubclass(StoreNotReady, RuntimeError)


# ---------------------------------------------------------------------------
# The four backend functions, against the real backend
# ---------------------------------------------------------------------------

BACKEND = os.getenv("DATABASE_BACKEND", "dynamodb")


@pytest.fixture
def lookup_module() -> Any:
    import importlib

    return importlib.import_module(f"actingweb.db.{BACKEND}.property_lookup")


@pytest.fixture
def names(lookup_module: Any) -> Iterator[list[str]]:
    """Two unique names; the shared table is left as found."""
    unique = [f"rdy{uuid.uuid4().hex[:8]}", f"rdy{uuid.uuid4().hex[:8]}"]
    if BACKEND == "dynamodb":
        from actingweb.db.dynamodb.property_lookup import DbPropertyLookup

        DbPropertyLookup()  # ensure the table
    saved = lookup_module.read_readiness(unique)[1]
    yield unique
    lookup_module.unmark(unique)
    if saved is None:
        # Nothing was recorded before; remove what this test recorded.
        if BACKEND == "postgresql":
            from actingweb.db.postgresql.connection import get_connection

            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM property_lookup_backfill WHERE kind = 'configured'"
                )
                conn.commit()
        else:
            from actingweb.db.dynamodb.property_lookup import (
                LOOKUP_CONFIGURED_KEY,
                PropertyLookupV2,
            )

            try:
                PropertyLookupV2.get(LOOKUP_CONFIGURED_KEY).delete()
            except Exception:  # noqa: BLE001
                pass
    else:
        lookup_module.record_configured(sorted(saved))


class TestBackendFunctions:
    def test_mark_read_unmark_roundtrip(
        self, lookup_module: Any, names: list[str]
    ) -> None:
        a, b = names
        marked, _ = lookup_module.read_readiness(names)
        assert marked == set()
        lookup_module.mark_backfilled([a])
        marked, _ = lookup_module.read_readiness(names)
        assert marked == {a}
        lookup_module.mark_backfilled([a, b])  # idempotent
        marked, _ = lookup_module.read_readiness(names)
        assert marked == {a, b}
        lookup_module.unmark([a])
        marked, _ = lookup_module.read_readiness(names)
        assert marked == {b}

    def test_the_configured_set_is_replaced_not_accumulated(
        self, lookup_module: Any, names: list[str]
    ) -> None:
        lookup_module.record_configured(names)
        assert lookup_module.read_readiness(names)[1] == set(names)
        lookup_module.record_configured([names[0]])
        assert lookup_module.read_readiness(names)[1] == {names[0]}

    def test_two_concurrent_first_starts_both_pass(
        self, lookup_module: Any, names: list[str]
    ) -> None:
        errors: list[BaseException] = []

        def start() -> None:
            try:
                lookup_module.mark_backfilled(names)
            except BaseException as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=start) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        assert lookup_module.read_readiness(names)[0] == set(names)

    def test_marker_rows_are_not_lookup_rows(
        self, lookup_module: Any, names: list[str]
    ) -> None:
        """A marker can never answer a reverse lookup."""
        lookup_module.mark_backfilled(names)
        if BACKEND == "dynamodb":
            from actingweb.db.dynamodb.property_lookup import (
                DbPropertyLookup,
                compute_lookup_key,
            )

            row_key = compute_lookup_key(names[0], "#meta")
            assert not row_key.startswith("#meta#")
            assert DbPropertyLookup().get(names[0], names[0]) is None


class TestFaults:
    def test_dynamodb_missing_table_is_named(self) -> None:
        if BACKEND != "dynamodb":
            pytest.skip("DynamoDB-only")
        from pynamodb.exceptions import GetError

        from actingweb.db.dynamodb import property_lookup as pl

        class _Cause(Exception):
            response = {"Error": {"Code": "ResourceNotFoundException"}}

        err = GetError("Failed to batch get items")
        err.cause = _Cause()  # type: ignore[attr-defined]
        with mock.patch.object(pl.PropertyLookupV2, "batch_get", side_effect=err):
            with pytest.raises(DbError) as raised:
                pl.read_readiness(["email"])
        assert "lookup table missing" in str(raised.value)
        assert pl.PropertyLookupV2.Meta.table_name in str(raised.value)

    def test_dynamodb_other_fault_is_a_db_error(self) -> None:
        if BACKEND != "dynamodb":
            pytest.skip("DynamoDB-only")
        from actingweb.db.dynamodb import property_lookup as pl

        with mock.patch.object(
            pl.PropertyLookupV2, "batch_get", side_effect=RuntimeError("AccessDenied")
        ):
            with pytest.raises(DbError) as raised:
                pl.read_readiness(["email"])
        assert "lookup table missing" not in str(raised.value)

    def test_postgresql_missing_relation_is_named(self) -> None:
        if BACKEND != "postgresql":
            pytest.skip("PostgreSQL-only")
        from actingweb.db.postgresql import property_lookup as pl

        def down() -> Any:
            raise RuntimeError('relation "property_lookup_backfill" does not exist')

        with mock.patch.object(pl, "get_connection", down):
            with pytest.raises(DbError) as raised:
                pl.read_readiness(["email"])
        assert "property_lookup_backfill" in str(raised.value)
        assert "alembic upgrade head" in str(raised.value)

    def test_postgresql_other_fault_is_a_db_error(self) -> None:
        if BACKEND != "postgresql":
            pytest.skip("PostgreSQL-only")
        from actingweb.db.postgresql import property_lookup as pl

        def down() -> Any:
            raise RuntimeError("connection refused")

        with mock.patch.object(pl, "get_connection", down):
            with pytest.raises(DbError):
                pl.read_readiness(["email"])


class TestEmptyStoreProbe:
    """``properties_table_empty`` ignores the system actors' rows and pages on."""

    @pytest.mark.skipif(BACKEND != "dynamodb", reason="DynamoDB scan paging")
    def test_many_system_rows_do_not_hide_an_actor_row(self) -> None:
        from actingweb.db.dynamodb.property import Property

        system = [SimpleNamespace(id="_actingweb_oauth2") for _ in range(60)]
        actor = [SimpleNamespace(id="real-actor")]
        seen: dict[str, Any] = {}

        def scan(**kwargs: Any) -> Any:
            seen.update(kwargs)
            return iter(system + actor)

        with mock.patch.object(Property, "scan", side_effect=scan):
            assert command.properties_table_empty("dynamodb") is False
        assert "limit" not in seen  # ``limit`` would cap the total read

    @pytest.mark.skipif(BACKEND != "dynamodb", reason="DynamoDB scan paging")
    def test_only_system_rows_is_empty(self) -> None:
        from actingweb.db.dynamodb.property import Property

        system = [SimpleNamespace(id="_actingweb_system") for _ in range(60)]
        with mock.patch.object(Property, "scan", return_value=iter(system)):
            assert command.properties_table_empty("dynamodb") is True
