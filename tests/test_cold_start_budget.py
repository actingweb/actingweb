"""
Phase 1 of the v2 list read cost release (thoughts/plans/2026-08-20-v2-
positional-access-cost.md): pin the cold-start DescribeTable/CreateTable
budget before the release adds any new backend surface.

`_ensure.py` collapsed the old per-accessor `if not Model.exists():
create_table()` pattern -- measured at >1,000 DescribeTable calls/minute
in a near-idle production deployment -- to at most one check per model
class per process, and to zero when AWS_DB_AUTO_CREATE_TABLES=false. That
guarantee is keyed on the model CLASS, so the way to lose it silently is
to add one: a new PynamoDB Model subclass costs one more control-plane
call on every container cold start, and `tests/test_ensure_table.py`
would not catch it, because it exercises the guard with fake models
rather than counting calls across the real model set.

This file changes no production code and must pass UNMODIFIED through
every later phase of the release. A phase that needs it edited introduced
a new Model subclass, which the plan forbids outright.
"""

import os
import uuid
from contextlib import contextmanager
from unittest import mock

import pytest


@pytest.fixture(autouse=True)
def _require_dynamodb():
    if os.getenv("DATABASE_BACKEND", "dynamodb") != "dynamodb":
        pytest.skip("DynamoDB-only test")


@pytest.fixture(autouse=True)
def clean_ensure_state(monkeypatch):
    """Reset the process-wide ensure-table cache around every test, so each
    test simulates the cold-start state the guard is meant to bound."""
    from actingweb.db.dynamodb import _ensure

    monkeypatch.delenv("AWS_DB_AUTO_CREATE_TABLES", raising=False)
    _ensure.reset_ensure_cache()
    _ensure._auto_create_override = None
    _ensure._flag_logged = False
    yield
    _ensure.reset_ensure_cache()
    _ensure._auto_create_override = None
    _ensure._flag_logged = False


@pytest.fixture
def config():
    from actingweb.config import Config

    return Config(database="dynamodb")


@pytest.fixture
def actor_id():
    return f"cold-start-{uuid.uuid4()}"


@contextmanager
def _spy_control_plane(models):
    """Wrap exists()/create_table() on each model with call-counting spies,
    restored on exit. Returns {model: (exists_spy, create_table_spy)}."""
    patchers = []
    spies = {}
    for model in models:
        p_exists = mock.patch.object(model, "exists", wraps=model.exists)
        p_create = mock.patch.object(
            model, "create_table", wraps=model.create_table
        )
        spies[model] = (p_exists.start(), p_create.start())
        patchers.append(p_exists)
        patchers.append(p_create)
    try:
        yield spies
    finally:
        for p in reversed(patchers):
            p.stop()


def _exercise_all_paths(config, actor_id):
    """Touch the property, property-list, actor, trust, peer-trustee,
    subscription and attribute paths -- one construction (and, where
    ensure_table lives behind a method rather than __init__, one call) per
    accessor, so every model in required_models() gets a chance to be
    ensured."""
    from actingweb.db import (
        get_actor,
        get_actor_list,
        get_attribute,
        get_attribute_bucket_list,
        get_peer_trustee,
        get_peer_trustee_list,
        get_property,
        get_property_list,
        get_subscription,
        get_subscription_diff,
        get_subscription_diff_list,
        get_subscription_list,
        get_subscription_suspension,
        get_trust,
        get_trust_list,
    )
    from actingweb.property_list import ListProperty

    # Property + property-list -- this release's actual subject.
    prop_db = get_property(config)
    prop_db.set(actor_id=actor_id, name="greeting", value="hi")
    prop_db.get(actor_id=actor_id, name="greeting")
    get_property_list(config).fetch_all_including_lists(actor_id=actor_id)
    notes = ListProperty(actor_id, "notes", config)
    notes.append("first note")
    notes.to_list()

    # Actor
    get_actor(config).get(actor_id=actor_id)
    get_actor_list(config)

    # Trust
    get_trust(config).get(actor_id=actor_id, peerid="nobody")
    get_trust_list(config).fetch(actor_id)

    # Peer trustee
    get_peer_trustee(config).get(actor_id=actor_id, peer_type="app")
    get_peer_trustee_list(config).fetch(actor_id=actor_id)

    # Subscription
    get_subscription(config).get(actor_id=actor_id, peerid="nobody", subid="none")
    get_subscription_list(config).fetch(actor_id)
    get_subscription_diff(config).get(actor_id=actor_id, subid="none", seqnr=0)
    get_subscription_diff_list(config).fetch(actor_id=actor_id, subid="none")
    get_subscription_suspension(config, actor_id).is_suspended("properties")

    # Attribute
    get_attribute(config)
    get_attribute_bucket_list(config).fetch(actor_id=actor_id)


class TestColdStartDescribeTableBudget:
    def test_at_most_one_describe_table_per_model(self, config, actor_id):
        from actingweb.db.verify_tables import required_models

        models = required_models()
        with _spy_control_plane(models) as spies:
            _exercise_all_paths(config, actor_id)
            # Exercise a second time -- the guard must not re-check on a
            # warm process either.
            _exercise_all_paths(config, actor_id)

        for model, (exists_spy, create_table_spy) in spies.items():
            assert exists_spy.call_count <= 1, (
                f"{model.__name__}.exists() called "
                f"{exists_spy.call_count} times; the cold-start guard "
                "must check at most once per model class per process"
            )
            # create_table is only called when exists() reported False;
            # the test tables already exist, so it should never fire here.
            create_table_spy.assert_not_called()

    def test_auto_create_disabled_issues_zero_control_plane_calls(
        self, config, actor_id, monkeypatch
    ):
        from actingweb.db.verify_tables import required_models

        monkeypatch.setenv("AWS_DB_AUTO_CREATE_TABLES", "false")
        models = required_models()
        with _spy_control_plane(models) as spies:
            _exercise_all_paths(config, actor_id)

        for exists_spy, create_table_spy in spies.values():
            exists_spy.assert_not_called()
            create_table_spy.assert_not_called()

    def test_repeated_get_property_construction_ensures_once(self, config):
        """property_list.py deliberately reconstructs get_property(config)
        on every list operation, to avoid handle conflicts. That must not
        cost a DescribeTable beyond the first construction."""
        from actingweb.db import get_property
        from actingweb.db.verify_tables import required_models

        models = required_models()
        with _spy_control_plane(models) as spies:
            for _ in range(20):
                get_property(config)

        property_model = next(
            m for m in models if m.__name__ in ("Property", "PropertyLegacy")
        )
        assert spies[property_model][0].call_count <= 1
