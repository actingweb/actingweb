"""Third iteration on the fault contract (Issues A2, B2, C2, D2, E2, F2, G2
and H2 of
``thoughts/verifications/2026-10-29-db-fault-semantics-and-creator-uniqueness-2.md``).
"""

from __future__ import annotations

import json
from typing import Any
from unittest import mock

import pytest

from actingweb.db import get_subscription
from actingweb.db.exceptions import DbError
from tests._adoption_helpers import aid, create_core_actor, make_config, uuid_email


def _raise(*_a: Any, **_k: Any) -> Any:
    raise DbError("simulated backend fault", "actor-secret-id")


class TestA2HookRunners:
    def test_a_faulting_lifecycle_hook_raises_instead_of_answering_none(self) -> None:
        from actingweb.interface.hooks import HookRegistry

        registry = HookRegistry()
        registry.register_lifecycle_hook("oauth_success", _raise)
        with pytest.raises(DbError):
            registry.execute_lifecycle_hooks("oauth_success", mock.Mock(), email="x")

    def test_a_faulting_property_hook_raises_instead_of_returning_the_value(
        self,
    ) -> None:
        from actingweb.interface.hooks import HookRegistry

        registry = HookRegistry()
        registry.register_property_hook("secret", _raise)
        with pytest.raises(DbError):
            registry.execute_property_hooks("secret", "get", mock.Mock(), "raw")

    def test_post_commit_notifications_do_not_fail_the_sign_in(self) -> None:
        from actingweb import oauth2 as oauth2_module

        hooks = mock.Mock()
        hooks.execute_lifecycle_hooks.side_effect = _raise
        config = make_config()
        oauth2_module._fire_lifecycle(hooks, "actor_adopted", None, config)
        oauth2_module._fire_lifecycle(hooks, "actor_deleted_complete", None, config)
        with pytest.raises(DbError):
            oauth2_module._fire_lifecycle(hooks, "actor_deleted", None, config)


class TestB2McpDispatch:
    def test_a_fault_in_a_method_answers_503_without_the_fault_text(self) -> None:
        from tests.mcp_helpers import make_mcp_handler

        handler = make_mcp_handler()
        with mock.patch.object(handler, "_handle_tools_list", _raise, create=True):
            body = {"jsonrpc": "2.0", "id": 7, "method": "tools/list"}
            with mock.patch.object(
                handler, "authenticate_and_get_actor_cached", return_value=mock.Mock()
            ):
                result = handler.post(body)

        assert handler.response.status_code == 503
        assert handler.response.headers.get("Retry-After") == "5"
        assert "actor-secret-id" not in json.dumps(result)


class TestC2RegisterDiffs:
    def test_one_subscribers_fault_does_not_stop_the_others(self) -> None:
        config = make_config()
        actor = create_core_actor(config, uuid_email())
        for peer in ("p1", "p2"):
            assert get_subscription(config).create(
                actor_id=aid(actor),
                peerid=peer,
                subid=f"s-{peer}",
                target="properties",
                granularity="high",
                callback=False,
            )
        real = actor.get_subscription_obj
        calls: list[str] = []

        def flaky(peerid: str | None = None, **kw: Any) -> Any:
            calls.append(str(peerid))
            if peerid == "p1":
                raise DbError("simulated")
            return real(peerid=peerid, **kw)

        with (
            mock.patch.object(actor, "get_subscription_obj", flaky),
            mock.patch.object(actor, "callback_subscription"),
        ):
            actor.register_diffs(target="properties", blob='{"x": 1}')

        assert sorted(calls) == ["p1", "p2"]


class TestD2CallbackDrain:
    """Entry 22 (D3): once the handlers ran, a sequence-write fault answers
    PROCESSED and the drained callbacks leave pending, so the publisher does
    not redeliver and the handlers do not run twice."""

    def _setup(self) -> Any:
        from actingweb.callback_processor import CallbackProcessor
        from actingweb.interface.actor_interface import ActorInterface

        config = make_config()
        actor = create_core_actor(config, uuid_email())
        assert get_subscription(config).create(
            actor_id=aid(actor),
            peerid="p1",
            subid="s1",
            target="properties",
            callback=True,
        )
        return CallbackProcessor(ActorInterface(actor))

    def test_a_faulted_sequence_write_after_the_handlers_is_processed(self) -> None:
        from actingweb.callback_processor import ProcessResult

        processor = self._setup()
        processor._set_pending("p1", "s1", [{"sequence": 2, "data": {"y": 2}}])
        seen: list[int] = []

        with mock.patch.object(processor, "_update_last_seq", _raise):
            result = processor.process_callback_sync(
                peer_id="p1",
                subscription_id="s1",
                sequence=1,
                data={"x": 1},
                handler=lambda cb: seen.append(cb.sequence),
            )

        assert result == ProcessResult.PROCESSED
        assert seen == [1, 2]
        assert processor._get_pending("p1", "s1") == []

    def test_a_storage_fault_in_the_handler_raises_before_the_sequence_moves(
        self,
    ) -> None:
        """A3: the handler's DbError (the library's auto-storage write) is not
        folded as an at-most-once consumer error."""
        processor = self._setup()

        with pytest.raises(DbError):
            processor.process_callback_sync(
                peer_id="p1",
                subscription_id="s1",
                sequence=1,
                data={"x": 1},
                handler=_raise,
            )

        assert processor._get_last_seq("p1", "s1") == 0

    def test_processed_leftovers_do_not_count_toward_back_pressure(self) -> None:
        """E3: an entry at or below last_seq is a processed leftover; it must
        not fill the pending queue and get a real gap callback rejected."""
        from actingweb.callback_processor import CallbackProcessor, ProcessResult

        processor = self._setup()
        small = CallbackProcessor(processor._actor, max_pending=1)
        small._set_pending("p1", "s1", [{"sequence": 1, "data": {"old": 1}}])
        assert small._update_last_seq("p1", "s1", 1)

        result = small.process_callback_sync(
            peer_id="p1", subscription_id="s1", sequence=3, data={"x": 3}
        )

        assert result == ProcessResult.PENDING
        assert [c["sequence"] for c in small._get_pending("p1", "s1")] == [3]


class TestE2SequenceCache:
    def test_a_faulted_increment_leaves_the_cached_sequence_alone(self) -> None:
        from actingweb.subscription import Subscription

        config = make_config()
        actor = create_core_actor(config, uuid_email())
        assert get_subscription(config).create(
            actor_id=aid(actor), peerid="p1", subid="s1", target="properties"
        )
        sub = Subscription(actor_id=aid(actor), peerid="p1", subid="s1", config=config)
        assert sub.subscription is not None
        before = sub.subscription["sequence"]

        with (
            mock.patch.object(sub.handle, "increment_seq", _raise),
            pytest.raises(DbError),
        ):
            sub.increase_seq()

        assert sub.subscription is not None
        assert sub.subscription["sequence"] == before


class TestF2PostgresDuplicateCreate:
    def test_a_duplicate_subscription_or_peertrustee_create_is_false(self) -> None:
        pg = pytest.importorskip("psycopg")
        from actingweb.db.postgresql import peertrustee, subscription

        class _Cursor:
            rowcount = 0

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

            def commit(self) -> None:
                return None

        for module, cls, kwargs in (
            (
                subscription,
                "DbSubscription",
                {"actor_id": "a", "peerid": "p", "subid": "s"},
            ),
            (
                peertrustee,
                "DbPeerTrustee",
                {"actor_id": "a", "peerid": "p", "peer_type": "t"},
            ),
        ):
            obj = getattr(module, cls)()
            with (
                mock.patch.object(module, "get_connection", lambda: _Conn()),
                mock.patch.object(obj, "get", return_value=None),
            ):
                assert obj.create(**kwargs) is False


class TestG2PermanentErrors:
    def test_a_validation_error_answers_500_without_retry_after(self) -> None:
        from actingweb.interface.integrations._errors import db_error_answer

        cause = Exception("Item size has exceeded the maximum allowed size")
        cause.cause_response_code = "ValidationException"  # type: ignore[attr-defined]
        try:
            raise DbError("attribute set") from cause
        except DbError as fault:
            status, headers, body = db_error_answer(fault)
        assert status == 500
        assert "Retry-After" not in headers
        assert body["error"] == "internal_error"

    def test_a_throttle_still_answers_503(self) -> None:
        from actingweb.interface.integrations._errors import db_error_answer

        cause = Exception("throttled")
        cause.cause_response_code = "ProvisionedThroughputExceededException"  # type: ignore[attr-defined]
        try:
            raise DbError("attribute get") from cause
        except DbError as fault:
            status, headers, _ = db_error_answer(fault)
        assert status == 503 and headers["Retry-After"] == "5"


class TestH2SpaCors:
    def test_a_503_on_an_spa_route_carries_cors_headers(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from flask import Flask

        from actingweb.interface import ActingWebApp

        aw = ActingWebApp(
            aw_type="urn:actingweb:test:spa-cors",
            database="dynamodb",
            fqdn="test.example.com",
            proto="https://",
        )
        origin = "https://spa.example.com"

        fapp = FastAPI()

        @fapp.get("/oauth/spa/probe")
        async def probe() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
            raise DbError("simulated")

        aw.integrate_fastapi(fapp)
        response = TestClient(fapp, raise_server_exceptions=False).get(
            "/oauth/spa/probe", headers={"Origin": origin}
        )
        assert response.status_code == 503
        assert response.headers.get("access-control-allow-origin") == origin

        flask_app = Flask(__name__)

        @flask_app.route("/oauth/spa/probe")
        def flask_probe() -> str:  # pyright: ignore[reportUnusedFunction]
            raise DbError("simulated")

        aw.integrate_flask(flask_app)
        flask_response = flask_app.test_client().get(
            "/oauth/spa/probe", headers={"Origin": origin}
        )
        assert flask_response.status_code == 503
        assert flask_response.headers.get("Access-Control-Allow-Origin") == origin
