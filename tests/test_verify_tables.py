"""
Tests for the operator-facing table verifier (actingweb.db.verify_tables).

With AWS_DB_AUTO_CREATE_TABLES=false the library never issues DescribeTable,
so "all required tables exist" becomes a precondition nothing checks. This
module is the out-of-band check; these tests pin the required-table set (the
authoritative list operators pre-create from) and the CLI's exit codes.
"""

from unittest import mock

import pytest

from actingweb.db import verify_tables

# Table names carry AWS_DB_PREFIX, which pynamodb bakes into Meta.table_name
# at *model import* time. Other test modules reassign AWS_DB_PREFIX (per-xdist
# -worker prefixes) without restoring it, so the ambient value at call time is
# not necessarily the one in the name — assert on suffixes only, never by
# stripping a prefix read from the environment.
LOOKUP_SUFFIXES = [
    "_actors",
    "_attributes",
    "_peertrustees",
    "_properties",
    "_subscriptions",
    "_subscriptiondiffs",
    "_subscription_suspensions",
    "_trusts",
    "_property_lookup_v2",
]


def assert_suffixes(names: list[str], expected: list[str]) -> None:
    """Assert names end with `expected`, in order, whatever the prefix is."""
    assert len(names) == len(expected), f"{names} != {expected}"
    for name, suffix in zip(names, expected, strict=True):
        assert name.endswith(suffix), f"{name!r} does not end with {suffix!r}"


class TestRequiredTables:
    def test_lookup_mode_requires_nine_tables(self):
        """The v2 lookup table is required only in lookup-table mode."""
        names = verify_tables.required_table_names(use_lookup_table=True)
        assert_suffixes(names, LOOKUP_SUFFIXES)

    def test_legacy_mode_omits_the_lookup_table(self):
        names = verify_tables.required_table_names(use_lookup_table=False)
        assert_suffixes(names, LOOKUP_SUFFIXES[:-1])

    def test_suspensions_table_is_required(self):
        """Regression: this table was the one missing in a real deployment.

        Pre-3.13 the suspension accessor had no auto-create guard, so it was
        never created; with auto-creation off nothing reports it missing.
        """
        names = verify_tables.required_table_names(use_lookup_table=True)
        assert any(n.endswith("_subscription_suspensions") for n in names)

    def test_deprecated_v1_lookup_table_is_not_required(self):
        """v1 is a read-only fallback — operators must not pre-create it."""
        names = verify_tables.required_table_names(use_lookup_table=True)
        assert not any(n.endswith("_property_lookup") for n in names)

    def test_matches_what_prewarm_creates(self):
        """The verifier and the pre-warm sweep share one source of truth.

        If these ever diverge, operators pre-create a set that differs from
        what the library needs — the exact failure the verifier exists to
        prevent.
        """
        import inspect

        from actingweb.interface import app

        source = inspect.getsource(app.ActingWebApp._prewarm_dynamodb_tables)
        assert "required_models(" in source


class TestLookupModeDetection:
    @pytest.mark.parametrize("value", ["false", "FALSE", "0", "no", " No "])
    def test_falsey_values_select_legacy(self, monkeypatch, value):
        monkeypatch.setenv("USE_PROPERTY_LOOKUP_TABLE", value)
        assert verify_tables.lookup_mode_enabled() is False

    @pytest.mark.parametrize("value", ["true", "TRUE", "1", "anything"])
    def test_other_values_select_lookup_mode(self, monkeypatch, value):
        monkeypatch.setenv("USE_PROPERTY_LOOKUP_TABLE", value)
        assert verify_tables.lookup_mode_enabled() is True

    def test_defaults_to_lookup_mode(self, monkeypatch):
        """Matches Config.use_lookup_table, which defaults to True in 3.13."""
        monkeypatch.delenv("USE_PROPERTY_LOOKUP_TABLE", raising=False)
        assert verify_tables.lookup_mode_enabled() is True


class TestVerifyTables:
    def test_splits_present_from_missing(self):
        names = verify_tables.required_table_names(use_lookup_table=True)
        missing_name = names[-1]

        # Model.exists() is a classmethod — patch it as one, or pynamodb
        # calls it unbound and the test fails on the signature instead of
        # the behaviour.
        def fake_exists(cls):
            return str(cls.Meta.table_name) != missing_name

        with mock.patch("pynamodb.models.Model.exists", new=classmethod(fake_exists)):
            present, missing = verify_tables.verify_tables(use_lookup_table=True)

        assert missing == [missing_name]
        assert len(present) == 8

    def test_permission_errors_propagate(self):
        """A role without DescribeTable must fail loudly, not report all
        tables as missing (which would read as a broken deployment)."""
        with mock.patch(
            "pynamodb.models.Model.exists", side_effect=RuntimeError("AccessDenied")
        ):
            with pytest.raises(RuntimeError, match="AccessDenied"):
                verify_tables.verify_tables(use_lookup_table=True)


class TestCli:
    @pytest.fixture(autouse=True)
    def dynamodb_backend(self, monkeypatch):
        """The CLI exits 2 for non-DynamoDB backends.

        The suite also runs with DATABASE_BACKEND=postgresql (CI matrix), so
        pin the backend here or every exit-code assertion below becomes an
        assertion about the wrong branch.
        """
        monkeypatch.setenv("DATABASE_BACKEND", "dynamodb")

    def test_list_does_not_query_aws(self, capsys):
        with mock.patch("pynamodb.models.Model.exists") as exists:
            rc = verify_tables.main(["--list", "--lookup-table"])
        assert rc == 0
        assert exists.call_count == 0
        assert "_property_lookup_v2" in capsys.readouterr().out

    def test_exit_zero_when_all_present(self, monkeypatch, capsys):
        monkeypatch.setattr(
            verify_tables, "verify_tables", lambda use_lookup_table=None: (["a"], [])
        )
        assert verify_tables.main([]) == 0
        assert "All 1 required tables exist." in capsys.readouterr().out

    def test_exit_one_when_tables_missing(self, monkeypatch, capsys):
        monkeypatch.setattr(
            verify_tables,
            "verify_tables",
            lambda use_lookup_table=None: (["a"], ["b_subscription_suspensions"]),
        )
        assert verify_tables.main([]) == 1
        captured = capsys.readouterr()
        assert "MISSING  b_subscription_suspensions" in captured.out
        assert "1 required table(s) missing" in captured.err

    def test_exit_two_when_check_fails(self, monkeypatch, capsys):
        def boom(use_lookup_table=None):
            raise RuntimeError("AccessDenied")

        monkeypatch.setattr(verify_tables, "verify_tables", boom)
        assert verify_tables.main([]) == 2
        assert "AccessDenied" in capsys.readouterr().err

    def test_exit_two_on_non_dynamodb_backend(self, monkeypatch, capsys):
        monkeypatch.setenv("DATABASE_BACKEND", "postgresql")
        assert verify_tables.main([]) == 2
        assert "Alembic" in capsys.readouterr().err

    def test_legacy_and_lookup_flags_are_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            verify_tables.main(["--legacy", "--lookup-table"])
