"""Unit tests for the PostgreSQL attribute-DELETE diagnostics.

The diagnostics exist to name the mechanism behind an intermittent CI failure
where a per-actor attribute ``DELETE`` did not take effect
(``thoughts/todo/2026-06-15-postgres-parallel-delete-not-persisting.md``). They
are off by default and must stay that way: they cost a savepoint-wrapped schema
read plus a post-commit re-read per delete, on a path that runs during every
actor and trust teardown.

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

    def test_enabled_reads_schema_before_the_delete_inside_a_savepoint(
        self, monkeypatch: pytest.MonkeyPatch, statements: list[str]
    ) -> None:
        monkeypatch.setenv(_DIAG_ENV, "1")

        assert (
            pg_attribute.DbAttribute.set_attr(
                actor_id="actor1", bucket="mcp_clients", name="mcp_abc", data=None
            )
            is True
        )

        # Order is the point, not just the presence of the extra queries. The
        # schema read is savepoint-wrapped and runs BEFORE the DELETE so a
        # server-side failure in it cannot abort the transaction the DELETE
        # then commits — see TestDiagnosticsCannotCauseTheBugTheyDiagnose.
        assert statements[0] == f"SAVEPOINT {pg_attribute._DIAG_SAVEPOINT}"
        assert "current_schema()" in statements[1]
        assert statements[2] == f"RELEASE SAVEPOINT {pg_attribute._DIAG_SAVEPOINT}"
        assert statements[3].startswith("DELETE FROM attributes")
        assert statements[4] == "COMMIT"
        # Post-commit re-read on a freshly checked-out connection. This is what
        # separates "matched 0 rows" from "matched but did not persist".
        assert "EXISTS(" in statements[5]
        assert len(statements) == 6


class TestDiagnosticsCannotCauseTheBugTheyDiagnose:
    """The failure mode Codex review caught on PR #128.

    A server-side error in the schema query (statement timeout, cancellation)
    aborts the whole PostgreSQL transaction. Catching the Python exception does
    not un-abort it — the subsequent ``conn.commit()`` degrades to a rollback
    while ``set_attr()`` still returns ``True``. The instrumentation would then
    be *producing* the non-persisting DELETE it was added to explain.

    The savepoint plus the before-the-DELETE ordering is what makes that
    impossible. These tests assert the recovery, not just the absence of a
    raised exception.
    """

    def test_a_failing_schema_read_rolls_back_to_the_savepoint(
        self, monkeypatch: pytest.MonkeyPatch, statements: list[str]
    ) -> None:
        monkeypatch.setenv(_DIAG_ENV, "1")

        def exploding_fetchone(self: FakeCursor) -> tuple[str, str, bool]:
            raise psycopg.OperationalError("statement timeout during diagnostics")

        monkeypatch.setattr(FakeCursor, "fetchone", exploding_fetchone)

        assert (
            pg_attribute.DbAttribute.set_attr(
                actor_id="actor1", bucket="mcp_clients", name="mcp_abc", data=None
            )
            is True
        )

        assert statements[0] == f"SAVEPOINT {pg_attribute._DIAG_SAVEPOINT}"
        # The recovery, without which the transaction stays aborted.
        assert f"ROLLBACK TO SAVEPOINT {pg_attribute._DIAG_SAVEPOINT}" in statements, (
            "a failed schema read must roll back to the savepoint"
        )
        assert f"RELEASE SAVEPOINT {pg_attribute._DIAG_SAVEPOINT}" not in statements

    def test_the_delete_still_runs_and_commits_after_a_failed_schema_read(
        self, monkeypatch: pytest.MonkeyPatch, statements: list[str]
    ) -> None:
        monkeypatch.setenv(_DIAG_ENV, "1")

        def exploding_fetchone(self: FakeCursor) -> tuple[str, str, bool]:
            raise psycopg.OperationalError("statement timeout during diagnostics")

        monkeypatch.setattr(FakeCursor, "fetchone", exploding_fetchone)

        pg_attribute.DbAttribute.set_attr(
            actor_id="actor1", bucket="mcp_clients", name="mcp_abc", data=None
        )

        delete_index = next(
            i
            for i, s in enumerate(statements)
            if s.startswith("DELETE FROM attributes")
        )
        # The DELETE comes after the recovery, and the commit after the DELETE.
        assert (
            statements.index(f"ROLLBACK TO SAVEPOINT {pg_attribute._DIAG_SAVEPOINT}")
            < delete_index
        )
        assert statements.index("COMMIT") > delete_index

    def test_schema_is_reported_as_unknown_rather_than_guessed(
        self,
        monkeypatch: pytest.MonkeyPatch,
        statements: list[str],  # noqa: ARG002
    ) -> None:
        """A diagnostic that cannot read the state must say so, not invent it."""
        monkeypatch.setenv(_DIAG_ENV, "1")

        def exploding_fetchone(self: FakeCursor) -> tuple[str, str, bool]:
            raise psycopg.OperationalError("statement timeout during diagnostics")

        monkeypatch.setattr(FakeCursor, "fetchone", exploding_fetchone)
        assert pg_attribute._read_schema_state(FakeCursor([], 1)) is None
