"""Unit tests for the PostgreSQL attribute-DELETE diagnostics.

The diagnostics exist to name the mechanism behind an intermittent CI failure
where a per-actor attribute ``DELETE`` did not take effect
(``thoughts/todo/2026-06-15-postgres-parallel-delete-not-persisting.md``). They
are off by default and must stay that way: they cost two extra queries per
delete, on a path that runs during every actor and trust teardown.

These tests are about the *gate* and the *shape of the evidence*, not about
PostgreSQL — the connection is faked, so they run on any backend.
"""

import pytest

psycopg = pytest.importorskip("psycopg", reason="PostgreSQL extra not installed")

from actingweb.db.postgresql import attribute as pg_attribute  # noqa: E402

_DIAG_ENV = "ACTINGWEB_PG_DELETE_DIAGNOSTICS"


class FakeCursor:
    """Records every statement executed against it."""

    def __init__(self, log: list[str], rowcount: int) -> None:
        self._log = log
        self.rowcount = rowcount

    def execute(self, statement: str, params: object = None) -> None:  # noqa: ARG002
        self._log.append(" ".join(statement.split()))

    def fetchone(self) -> tuple[str, str, bool]:
        return ("test_w0_public", "test_w0_public", False)

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class FakeConnection:
    def __init__(self, log: list[str], rowcount: int) -> None:
        self._log = log
        self._rowcount = rowcount

    def cursor(self) -> FakeCursor:
        return FakeCursor(self._log, self._rowcount)

    def commit(self) -> None:
        self._log.append("COMMIT")

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


@pytest.fixture
def statements(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Patch the module's connection factory and collect executed SQL."""
    log: list[str] = []
    monkeypatch.setattr(
        pg_attribute, "get_connection", lambda: FakeConnection(log, rowcount=1)
    )
    return log


class TestDiagnosticsGate:
    """The gate defaults to off, and only recognised truthy values turn it on."""

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", " 1 ", "Yes"])
    def test_recognised_truthy_values_enable(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        monkeypatch.setenv(_DIAG_ENV, value)
        assert pg_attribute._delete_diagnostics_enabled() is True

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "on", "please"])
    def test_everything_else_leaves_it_off(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        monkeypatch.setenv(_DIAG_ENV, value)
        assert pg_attribute._delete_diagnostics_enabled() is False

    def test_unset_is_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_DIAG_ENV, raising=False)
        assert pg_attribute._delete_diagnostics_enabled() is False


class TestDeletePathCost:
    """With diagnostics off, the delete is exactly one statement plus a commit."""

    def test_off_by_default_costs_nothing(
        self, monkeypatch: pytest.MonkeyPatch, statements: list[str]
    ) -> None:
        monkeypatch.delenv(_DIAG_ENV, raising=False)

        assert (
            pg_attribute.DbAttribute.set_attr(
                actor_id="actor1", bucket="mcp_clients", name="mcp_abc", data=None
            )
            is True
        )

        assert statements == [
            "DELETE FROM attributes WHERE id = %s AND bucket_name = %s",
            "COMMIT",
        ]

    def test_enabled_adds_the_two_diagnostic_reads(
        self, monkeypatch: pytest.MonkeyPatch, statements: list[str]
    ) -> None:
        monkeypatch.setenv(_DIAG_ENV, "1")

        assert (
            pg_attribute.DbAttribute.set_attr(
                actor_id="actor1", bucket="mcp_clients", name="mcp_abc", data=None
            )
            is True
        )

        # In order: the DELETE, the deleting transaction's own schema, the
        # commit, then a post-commit re-read on a freshly checked-out
        # connection. The last one is what separates "matched 0 rows" from
        # "matched but did not persist" — see the module docstring in
        # actingweb/db/postgresql/attribute.py.
        assert statements[0].startswith("DELETE FROM attributes")
        assert "current_schema()" in statements[1]
        assert statements[2] == "COMMIT"
        assert "EXISTS(" in statements[3]
        assert len(statements) == 4


class TestDiagnosticsNeverBreakTheDelete:
    """A diagnostic that breaks the operation it diagnoses is worse than none."""

    def test_a_failing_diagnostic_read_still_reports_success(
        self, monkeypatch: pytest.MonkeyPatch, statements: list[str]
    ) -> None:
        monkeypatch.setenv(_DIAG_ENV, "1")

        def exploding_fetchone(self: FakeCursor) -> tuple[str, str, bool]:
            raise psycopg.OperationalError("connection reset during diagnostics")

        monkeypatch.setattr(FakeCursor, "fetchone", exploding_fetchone)

        assert (
            pg_attribute.DbAttribute.set_attr(
                actor_id="actor1", bucket="mcp_clients", name="mcp_abc", data=None
            )
            is True
        )
        # The DELETE and its COMMIT still happened.
        assert statements[0].startswith("DELETE FROM attributes")
        assert "COMMIT" in statements
