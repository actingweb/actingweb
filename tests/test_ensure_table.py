"""
Tests for the process-wide DynamoDB table-existence guard (_ensure.py).

The guard replaces the per-accessor `if not Model.exists(): create_table()`
pattern (one live DescribeTable per accessor construction) with at most one
check per model class per process, plus an opt-out for IaC-managed
deployments (AWS_DB_AUTO_CREATE_TABLES / with_dynamodb()).
"""

import threading
from unittest import mock

import pytest

from actingweb.db.dynamodb import _ensure


@pytest.fixture(autouse=True)
def clean_ensure_state(monkeypatch):
    """Reset module-level guard state around every test."""
    monkeypatch.delenv("AWS_DB_AUTO_CREATE_TABLES", raising=False)
    _ensure.reset_ensure_cache()
    _ensure._auto_create_override = None
    _ensure._flag_logged = False
    yield
    _ensure.reset_ensure_cache()
    _ensure._auto_create_override = None
    _ensure._flag_logged = False


def make_fake_model(name: str = "faketable", exists: bool = False):
    """Build a stand-in model class with call-counting exists/create_table."""
    # Bind under a different name: a class-body assignment named `exists`
    # cannot read the enclosing function's `exists` parameter.
    table_exists = exists

    class FakeModel:
        class Meta:
            table_name = name

        exists = mock.MagicMock(return_value=table_exists)
        create_table = mock.MagicMock()

    return FakeModel


class TestEnsureTableMemoisation:
    def test_exists_called_at_most_once(self):
        model = make_fake_model(exists=True)
        for _ in range(50):
            _ensure.ensure_table(model)  # type: ignore[arg-type]
        assert model.exists.call_count == 1
        model.create_table.assert_not_called()

    def test_creates_table_when_absent(self):
        model = make_fake_model(exists=False)
        _ensure.ensure_table(model)  # type: ignore[arg-type]
        model.create_table.assert_called_once_with(wait=True)
        # Second call is fully memoised
        _ensure.ensure_table(model)  # type: ignore[arg-type]
        assert model.exists.call_count == 1

    def test_resource_in_use_race_is_benign(self):
        model = make_fake_model(exists=False)
        model.create_table.side_effect = Exception("ResourceInUseException: race")
        _ensure.ensure_table(model)  # type: ignore[arg-type]
        # Memoised as success despite the benign race
        _ensure.ensure_table(model)  # type: ignore[arg-type]
        assert model.exists.call_count == 1

    def test_other_errors_propagate_and_are_not_cached(self):
        model = make_fake_model(exists=False)
        model.create_table.side_effect = Exception("AccessDeniedException: nope")
        with pytest.raises(Exception, match="AccessDenied"):
            _ensure.ensure_table(model)  # type: ignore[arg-type]
        # Negative result must not be cached: next call re-checks
        model.create_table.side_effect = None
        _ensure.ensure_table(model)  # type: ignore[arg-type]
        assert model.exists.call_count == 2

    def test_distinct_models_tracked_independently(self):
        model_a = make_fake_model("shared_table", exists=True)
        model_b = make_fake_model("shared_table", exists=True)
        _ensure.ensure_table(model_a)  # type: ignore[arg-type]
        _ensure.ensure_table(model_b)  # type: ignore[arg-type]
        # Keyed by class, not table name: both get their own check
        assert model_a.exists.call_count == 1
        assert model_b.exists.call_count == 1

    def test_reset_ensure_cache_forces_recheck(self):
        model = make_fake_model(exists=True)
        _ensure.ensure_table(model)  # type: ignore[arg-type]
        _ensure.reset_ensure_cache()
        _ensure.ensure_table(model)  # type: ignore[arg-type]
        assert model.exists.call_count == 2

    def test_thread_safety_single_check(self):
        model = make_fake_model(exists=True)
        barrier = threading.Barrier(8)

        def worker():
            barrier.wait()
            _ensure.ensure_table(model)  # type: ignore[arg-type]

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert model.exists.call_count == 1


class TestAutoCreateFlag:
    def test_env_false_skips_exists_and_create(self, monkeypatch):
        monkeypatch.setenv("AWS_DB_AUTO_CREATE_TABLES", "false")
        model = make_fake_model(exists=False)
        _ensure.ensure_table(model)  # type: ignore[arg-type]
        model.exists.assert_not_called()
        model.create_table.assert_not_called()

    @pytest.mark.parametrize("value", ["false", "0", "no", " False "])
    def test_env_disabling_values(self, monkeypatch, value):
        monkeypatch.setenv("AWS_DB_AUTO_CREATE_TABLES", value)
        assert _ensure.auto_create_enabled() is False

    @pytest.mark.parametrize("value", ["true", "1", "yes", "anything"])
    def test_env_enabling_values(self, monkeypatch, value):
        monkeypatch.setenv("AWS_DB_AUTO_CREATE_TABLES", value)
        assert _ensure.auto_create_enabled() is True

    def test_default_is_enabled(self):
        assert _ensure.auto_create_enabled() is True

    def test_set_auto_create_beats_env(self, monkeypatch):
        monkeypatch.setenv("AWS_DB_AUTO_CREATE_TABLES", "true")
        _ensure.set_auto_create(False)
        assert _ensure.auto_create_enabled() is False
        model = make_fake_model(exists=False)
        _ensure.ensure_table(model)  # type: ignore[arg-type]
        model.exists.assert_not_called()

    def test_set_auto_create_warns_when_late(self, caplog):
        model = make_fake_model(exists=True)
        _ensure.ensure_table(model)  # type: ignore[arg-type]
        with caplog.at_level("WARNING"):
            _ensure.set_auto_create(False)
        assert any("already" in r.message for r in caplog.records)


class TestPreviouslyUnguardedModels:
    """Regression: these accessors had no auto-create guard at all, so first
    use on a fresh deployment crashed with table-not-found."""

    @pytest.fixture(autouse=True)
    def _require_dynamodb(self):
        import os

        if os.getenv("DATABASE_BACKEND", "dynamodb") != "dynamodb":
            pytest.skip("DynamoDB-only test")

    def test_subscription_suspension_autocreates_table(self):
        from actingweb.db.dynamodb.subscription_suspension import (
            DbSubscriptionSuspension,
            SubscriptionSuspension,
        )

        db = DbSubscriptionSuspension("ensure-test-actor")
        assert db.is_suspended("some-target") is False
        assert SubscriptionSuspension.exists()

    def test_peertrustee_list_autocreates_table(self):
        from actingweb.db.dynamodb.peertrustee import (
            DbPeerTrusteeList,
            PeerTrustee,
        )

        DbPeerTrusteeList()
        assert PeerTrustee.exists()


class TestFluentApi:
    def test_with_dynamodb_disables_auto_create(self):
        from actingweb.interface import ActingWebApp

        app = ActingWebApp(
            aw_type="urn:actingweb:test:ensure",
            database="dynamodb",
            fqdn="test.example.com",
        )
        app.with_dynamodb(auto_create_tables=False)
        assert _ensure.auto_create_enabled() is False
        app.with_dynamodb(auto_create_tables=True)
        assert _ensure.auto_create_enabled() is True
