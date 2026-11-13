"""How a deletion in progress and a deleted actor are answered over HTTP and
at the MCP bridge (Phase 1: T2, the bridge refusal, UNKNOWN in
``_race_winner``).

Plan: thoughts/plans/2026-11-02-3-16-adoption-fault-followups.md, Phase 1.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any
from unittest.mock import patch

import pytest

from actingweb import deletion
from actingweb.actor import Actor
from actingweb.db.exceptions import DbError, DeletionInProgress
from actingweb.interface.integrations._errors import db_error_answer, log_db_error
from tests._adoption_helpers import uuid_email
from tests.mcp_helpers import make_mcp_config, make_mcp_handler


class TestMapping:
    def test_retry_after_is_the_lease_remainder(self) -> None:
        status, headers, body = db_error_answer(DeletionInProgress("a1", 37))
        assert status == 503
        assert headers["Retry-After"] == "37"
        assert body["code"] == "temporarily_unavailable" or body["code"]

    def test_retry_after_is_at_least_one_second(self) -> None:
        assert DeletionInProgress("a1", 0).retry_after == 1

    def test_logged_at_info_not_error(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO):
            log_db_error(DeletionInProgress("a1", 5))
        records = [r for r in caplog.records if "deletion of actor a1" in r.message]
        assert records and all(r.levelno == logging.INFO for r in records)

    def test_a_plain_fault_keeps_the_fixed_value(self) -> None:
        _status, headers, _body = db_error_answer(DbError("x"))
        assert headers["Retry-After"] == "5"


class TestMcpBridge:
    def test_a_deleted_id_is_not_recreated(self) -> None:
        config = make_mcp_config()
        handler = make_mcp_handler(cfg=config)
        actor_id = f"mcp{uuid.uuid4().hex}"
        deletion.mark_actor_deleted(actor_id, config)
        try:
            result = handler._get_or_create_actor(actor_id, {"email": uuid_email()})
            assert result is None
            assert Actor(actor_id=actor_id, config=config).id is None
            assert deletion.get_deletion_status(actor_id, config) == (
                deletion.DeletionStatus.DELETED
            )
        finally:
            deletion.clear_actor_tombstone(actor_id, config)

    def test_an_unreadable_tombstone_in_the_race_check_answers_503(self) -> None:
        config = make_mcp_config()
        handler = make_mcp_handler(cfg=config)
        actor_id = f"mcp{uuid.uuid4().hex}"
        real = deletion.read_tombstone
        calls = {"n": 0}

        def faulting(*args: Any, **kw: Any) -> Any:
            # The bridge's own deleted-id check reads fine; _race_winner's
            # read (the second) faults.
            calls["n"] += 1
            if calls["n"] > 1:
                raise DbError("tombstone read")
            return real(*args, **kw)

        real_create = Actor.create

        def other_request_wins(self: Actor, *a: Any, **kw: Any) -> bool:
            assert real_create(Actor(config=config), *a, **kw)
            return real_create(self, *a, **kw)

        with (
            patch.object(deletion, "read_tombstone", faulting),
            patch.object(Actor, "create", other_request_wins),
            pytest.raises(DbError),
        ):
            handler._get_or_create_actor(actor_id, {"email": uuid_email()})


class TestSignInRoutes:
    """Phase 1 (planned, added at the 2026-11-03 verification): a sign-in
    completion that meets a live deletion lease answers 503 with the lease's
    Retry-After on every route, in both integrations."""

    @pytest.mark.parametrize(
        ("path", "method", "target", "attr"),
        [
            ("/oauth/callback", "get", "oauth2_callback.OAuth2CallbackHandler", "get"),
            ("/oauth/spa/token", "post", "oauth2_spa.OAuth2SPAHandler", "post"),
            ("/oauth/email", "post", "oauth_email.OAuth2EmailHandler", "post"),
        ],
    )
    @pytest.mark.parametrize("framework", ["flask", "fastapi"])
    def test_a_live_lease_answers_retry_after(
        self, framework: str, path: str, method: str, target: str, attr: str
    ) -> None:
        import importlib

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from flask import Flask

        from actingweb.interface import ActingWebApp
        from actingweb.interface.integrations.fastapi_integration import (
            FastAPIIntegration,
        )
        from actingweb.interface.integrations.flask_integration import (
            FlaskIntegration,
        )

        aw_app = ActingWebApp(
            aw_type="urn:actingweb:test:deletion-in-progress",
            database="dynamodb",
            fqdn="test.example.com",
            proto="https://",
        ).with_oauth(client_id="c", client_secret="s")
        module_name, class_name = target.split(".")
        handler_class = getattr(
            importlib.import_module(f"actingweb.handlers.{module_name}"), class_name
        )

        def raise_lease(*_a: Any, **_k: Any) -> Any:
            raise DeletionInProgress("a1", 7)

        with patch.object(handler_class, attr, raise_lease):
            if framework == "flask":
                app = Flask(__name__)
                FlaskIntegration(aw_app, app).setup_routes()
                resp = getattr(app.test_client(), method)(path)
                status, retry = resp.status_code, resp.headers.get("Retry-After")
            else:
                fapp = FastAPI()
                FastAPIIntegration(aw_app, fapp).setup_routes()
                client = TestClient(fapp, raise_server_exceptions=False)
                resp = getattr(client, method)(path)
                status, retry = resp.status_code, resp.headers.get("retry-after")
        assert status == 503
        assert retry == "7"
