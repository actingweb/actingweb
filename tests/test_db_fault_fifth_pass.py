"""Fifth iteration on the fault contract: the follow-ons from
``thoughts/verifications/2026-10-29-db-fault-semantics-and-creator-uniqueness-4.md``.
"""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest

from actingweb.db.exceptions import DbError
from tests._adoption_helpers import make_config


def _raise(*_a: Any, **_k: Any) -> Any:
    raise DbError("simulated backend fault")


@pytest.fixture
def fresh_permission_singletons(monkeypatch: Any) -> None:
    """Start with nothing initialised; the originals come back afterwards."""
    from actingweb import permission_evaluator, trust_permissions, trust_type_registry

    for module, names in (
        (trust_type_registry, ("_registry", "_registry_config")),
        (trust_permissions, ("_permission_store", "_permission_store_config")),
        (
            permission_evaluator,
            ("_permission_evaluator", "_permission_evaluator_config"),
        ),
    ):
        for name in names:
            monkeypatch.setattr(module, name, None)


@pytest.mark.usefixtures("fresh_permission_singletons")
class TestA4StartupFault:
    def test_a_registry_fault_still_builds_the_store(self) -> None:
        from actingweb import trust_permissions, trust_type_registry
        from actingweb.permission_initialization import initialize_permission_system

        config = make_config()
        with (
            mock.patch.object(trust_type_registry, "_register_default_types", _raise),
            pytest.raises(DbError),
        ):
            initialize_permission_system(config)

        assert trust_permissions._permission_store is not None

    def test_a_deny_still_denies_after_a_startup_fault(self) -> None:
        """At 8e8b4df+entry 16 the store was never built, the evaluator raised
        RuntimeError, and the handler answered from the legacy grant."""
        from actingweb import trust_type_registry
        from actingweb.aw_web_request import AWWebObj
        from actingweb.handlers.properties import PropertiesHandler
        from actingweb.permission_evaluator import PermissionEvaluator, PermissionResult
        from actingweb.permission_initialization import initialize_permission_system

        config = make_config()
        with (
            mock.patch.object(trust_type_registry, "_register_default_types", _raise),
            pytest.raises(DbError),
        ):
            initialize_permission_system(config)

        auth = mock.Mock()
        auth.acl = {"peerid": "peer-1", "relationship": "friend"}
        auth.check_authorisation.return_value = True  # the legacy grant allows
        handler = PropertiesHandler(AWWebObj(), config)
        with mock.patch.object(
            PermissionEvaluator,
            "evaluate_property_access",
            return_value=PermissionResult.DENIED,
        ):
            allowed = handler._check_property_permission(
                "a1", auth, "secret/x", "write"
            )

        assert allowed is False
        auth.check_authorisation.assert_not_called()


_LISTS = [
    ("trust", "Trust", "Trusts"),
    ("subscription", "Subscription", "Subscriptions"),
    ("property", "Property", "Properties"),
]


class TestB4ListWrappersFold:
    @pytest.mark.parametrize("module,model,wrapper", _LISTS)
    def test_strict_false_folds_and_strict_raises(
        self, module: str, model: str, wrapper: str
    ) -> None:
        import importlib

        from tests._adoption_helpers import (
            aid,
            create_core_actor,
            seam_fault,
            uuid_email,
        )

        config = make_config()
        actor = create_core_actor(config, uuid_email())
        cls = getattr(importlib.import_module(f"actingweb.{module}"), wrapper)
        with seam_fault(config, module, model, "query"):
            listing = cls(actor_id=aid(actor), config=config)  # no raise
            assert not listing.fetch(strict=False)
            with pytest.raises(DbError):
                listing.fetch()

    def test_register_diffs_does_not_fail_a_committed_write(self) -> None:
        from actingweb.db import get_subscription
        from tests._adoption_helpers import (
            aid,
            create_core_actor,
            seam_fault,
            uuid_email,
        )

        config = make_config()
        actor = create_core_actor(config, uuid_email())
        assert get_subscription(config).create(
            actor_id=aid(actor), peerid="p1", subid="s1", target="properties"
        )
        with seam_fault(config, "subscription", "Subscription", "query"):
            actor.register_diffs(target="properties", blob='{"x": 1}')

    def test_delete_after_a_folded_construction_still_deletes(self) -> None:
        from actingweb.db import get_subscription
        from actingweb.property import Properties
        from actingweb.subscription import Subscriptions
        from tests._adoption_helpers import (
            aid,
            create_core_actor,
            seam_fault,
            uuid_email,
        )

        config = make_config()
        actor = create_core_actor(config, uuid_email())
        actor_id = aid(actor)
        assert actor.property is not None
        actor.property["colour"] = "blue"
        assert get_subscription(config).create(
            actor_id=actor_id, peerid="p1", subid="s1", target="properties"
        )
        with seam_fault(config, "property", "Property", "query"):
            props = Properties(actor_id=actor_id, config=config)
        with seam_fault(config, "subscription", "Subscription", "query"):
            subs = Subscriptions(actor_id=actor_id, config=config)

        assert props.delete() and subs.delete()
        assert not Properties(actor_id=actor_id, config=config).fetch()
        assert not Subscriptions(actor_id=actor_id, config=config).fetch()


def _subscribed_actor(peers: tuple[str, ...] = ("p1",)) -> tuple[Any, Any]:
    from actingweb.db import get_subscription
    from tests._adoption_helpers import aid, create_core_actor, uuid_email

    config = make_config()
    actor = create_core_actor(config, uuid_email())
    for peer in peers:
        assert get_subscription(config).create(
            actor_id=aid(actor),
            peerid=peer,
            subid=f"s-{peer}",
            target="properties",
            granularity="high",
            callback=False,
        )
    return config, actor


def _stored(config: Any, actor: Any, peer: str) -> tuple[int, list[int]]:
    from actingweb.db import get_subscription, get_subscription_diff_list
    from tests._adoption_helpers import aid

    row = get_subscription(config).get(
        actor_id=aid(actor), peerid=peer, subid=f"s-{peer}"
    )
    diffs = get_subscription_diff_list(config).fetch(
        actor_id=aid(actor), subid=f"s-{peer}"
    )
    assert row is not None
    return row["sequence"], sorted(d["sequence"] for d in diffs or [])


class TestG4AtomicSequence:
    def test_concurrent_diffs_get_distinct_numbers(self) -> None:
        """At 8e8b4df both writers read N and wrote N+1; on PostgreSQL the
        second diff collided, on DynamoDB it overwrote the first."""
        import threading

        from actingweb.subscription import Subscription
        from tests._adoption_helpers import aid

        config, actor = _subscribed_actor()
        subs = [
            Subscription(actor_id=aid(actor), peerid="p1", subid="s-p1", config=config)
            for _ in range(2)
        ]
        barrier = threading.Barrier(2)
        results: list[Any] = []

        def write(sub: Any, n: int) -> None:
            barrier.wait()
            results.append(sub.add_diff(blob=f'{{"n": {n}}}'))

        threads = [
            threading.Thread(target=write, args=(s, n)) for n, s in enumerate(subs)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(results)
        assert _stored(config, actor, "p1") == (2, [1, 2])

    def test_an_unstored_diff_leaves_a_gap_not_a_reused_number(self) -> None:
        from actingweb.db import get_subscription_diff
        from actingweb.subscription import Subscription
        from tests._adoption_helpers import aid

        config, actor = _subscribed_actor()
        sub = Subscription(
            actor_id=aid(actor), peerid="p1", subid="s-p1", config=config
        )
        with mock.patch.object(
            type(get_subscription_diff(config)), "create", return_value=False
        ):
            assert sub.add_diff(blob='{"x": 1}') is False

        again = Subscription(
            actor_id=aid(actor), peerid="p1", subid="s-p1", config=config
        )
        diff = again.add_diff(blob='{"x": 2}')
        assert diff and diff["sequence"] == 2
        assert _stored(config, actor, "p1") == (2, [2])

    def test_a_taken_number_on_postgresql_is_false_not_a_fault(self) -> None:
        pg = pytest.importorskip("psycopg")
        from actingweb.db.postgresql import subscription_diff

        class _Cursor:
            def __enter__(self) -> Any:
                return self

            def __exit__(self, *a: Any) -> None:
                return None

            def execute(self, *a: Any, **k: Any) -> None:
                raise pg.errors.UniqueViolation("duplicate key")

        class _Conn:
            def __enter__(self) -> Any:
                return self

            def __exit__(self, *a: Any) -> None:
                return None

            def cursor(self) -> Any:
                return _Cursor()

        with mock.patch.object(subscription_diff, "get_connection", lambda: _Conn()):
            assert (
                subscription_diff.DbSubscriptionDiff().create(
                    actor_id="a", subid="s", diff="{}", seqnr=3
                )
                is False
            )


class TestD4DeliberateGap:
    def test_an_increment_fault_propagates_from_add_diff(self) -> None:
        from actingweb.subscription import Subscription
        from tests._adoption_helpers import aid

        config, actor = _subscribed_actor()
        sub = Subscription(
            actor_id=aid(actor), peerid="p1", subid="s-p1", config=config
        )
        with (
            mock.patch.object(sub.handle, "increment_seq", _raise),
            pytest.raises(DbError),
        ):
            sub.add_diff(blob='{"x": 1}')

    def test_a_subscriber_skipped_on_a_fault_gets_a_gap(self) -> None:
        """The skipped subscriber's sequence moves without a diff, so its next
        diff shows a gap; the other subscriber gets its diff as usual."""
        config, actor = _subscribed_actor(("p1", "p2"))
        real = actor.get_subscription_obj

        def flaky(peerid: str | None = None, **kw: Any) -> Any:
            if peerid == "p1":
                raise DbError("simulated")
            return real(peerid=peerid, **kw)

        with (
            mock.patch.object(actor, "get_subscription_obj", flaky),
            mock.patch.object(actor, "callback_subscription"),
        ):
            actor.register_diffs(target="properties", blob='{"x": 1}')

        assert _stored(config, actor, "p1") == (1, [])
        assert _stored(config, actor, "p2") == (1, [1])

    def test_no_gap_after_a_registered_diff(self) -> None:
        """A fault after the diff was stored (the callback) leaves no extra
        gap: the diff is there to poll."""
        config, actor = _subscribed_actor()

        with mock.patch.object(actor, "callback_subscription", _raise):
            actor.register_diffs(target="properties", blob='{"x": 1}')

        assert _stored(config, actor, "p1") == (1, [1])


class TestI4FactoryFaultCors:
    """The factory handler maps a fault inside its route; the answer must
    still carry the CORS headers the factory's JSON normally sends."""

    ORIGIN = "https://spa.example.com"

    def _aw(self) -> Any:
        from actingweb.interface import ActingWebApp

        return (
            ActingWebApp(
                aw_type="urn:actingweb:test:factory-cors",
                database="dynamodb",
                fqdn="test.example.com",
                proto="https://",
            )
            .with_web_ui(enable=False)
            .with_open_factory()
        )

    def _fault(self, aw: Any) -> Any:
        from actingweb.actor import Actor

        return mock.patch.object(Actor, "create", _raise)

    def test_flask(self) -> None:
        from flask import Flask

        aw = self._aw()
        app = Flask(__name__)
        aw.integrate_flask(app)
        with self._fault(aw):
            response = app.test_client().post(
                "/",
                json={"creator": "someone@example.com", "passphrase": "pw"},
                headers={"Origin": self.ORIGIN, "Accept": "application/json"},
            )
        assert response.status_code == 503
        assert response.headers.get("Access-Control-Allow-Origin") == self.ORIGIN
        assert "Retry-After" in response.headers.get(
            "Access-Control-Expose-Headers", ""
        )

    def test_fastapi(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        aw = self._aw()
        app = FastAPI()
        aw.integrate_fastapi(app)
        with self._fault(aw):
            response = TestClient(app, raise_server_exceptions=False).post(
                "/",
                json={"creator": "someone@example.com", "passphrase": "pw"},
                headers={"Origin": self.ORIGIN, "Accept": "application/json"},
            )
        assert response.status_code == 503
        assert response.headers.get("access-control-allow-origin") == self.ORIGIN


class TestJ4PostCommitFolds:
    def test_a_faulting_trust_approved_hook_does_not_fail_the_approval(
        self,
    ) -> None:
        from actingweb.interface.trust_manager import TrustManager

        core = mock.Mock()
        core.get_trust_relationship.return_value = {
            "peerid": "peer-1",
            "relationship": "friend",
            "approved": True,
            "peer_approved": True,
        }
        core.modify_trust_and_notify.return_value = True
        hooks = mock.Mock()
        hooks.execute_lifecycle_hooks.side_effect = _raise

        assert TrustManager(core, hooks=hooks).approve_relationship("peer-1") is True
        hooks.execute_lifecycle_hooks.assert_called_once()

    def test_the_trust_deleted_hook_still_raises_before_anything_is_removed(
        self,
    ) -> None:
        from actingweb.interface.trust_manager import TrustManager

        core = mock.Mock()
        core.get_trust_relationship.return_value = {
            "peerid": "peer-1",
            "relationship": "friend",
        }
        hooks = mock.Mock()
        hooks.execute_lifecycle_hooks.side_effect = _raise

        with pytest.raises(DbError):
            TrustManager(core, hooks=hooks).delete_relationship("peer-1")
        core.delete_reciprocal_trust.assert_not_called()

    def test_mcp_peer_approval_bookkeeping_does_not_fail_the_request(self) -> None:
        from actingweb import actor as actor_module
        from tests.mcp_helpers import make_mcp_handler

        handler = make_mcp_handler()
        trust = mock.Mock(
            peerid="peer-1",
            established_via="oauth2_client",
            peer_approved=False,
            relationship="mcp_client",
        )
        core = mock.Mock(actor={"id": "a1"})
        core.modify_trust_and_notify.side_effect = _raise
        with mock.patch.object(actor_module, "Actor", return_value=core):
            handler._mark_client_peer_approved(mock.Mock(id="a1"), "client-1", trust)
        core.modify_trust_and_notify.assert_called_once()

    def test_mcp_client_info_write_does_not_fail_the_request(self) -> None:
        from actingweb import actor as actor_module
        from actingweb.handlers import mcp as mcp_module
        from tests.mcp_helpers import make_mcp_handler

        handler = make_mcp_handler()
        context = mock.Mock(peer_id="peer-1", trust_relationship=None)
        core = mock.Mock(actor={"id": "a1"})
        core.modify_trust_and_notify.side_effect = _raise
        with (
            mock.patch.object(mcp_module, "RuntimeContext") as runtime,
            mock.patch.object(actor_module, "Actor", return_value=core),
        ):
            runtime.return_value.get_mcp_context.return_value = context
            handler._update_trust_with_client_info(
                mock.Mock(id="a1"), {"name": "Claude", "version": "1"}
            )
        core.modify_trust_and_notify.assert_called_once()
