"""Auth and sign-in wrappers no longer fold a fault into 401 or a failed
login (3.16 iteration, Issues C-G of
``thoughts/verifications/2026-10-29-db-fault-semantics-and-creator-uniqueness.md``).
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest import mock

import pytest

from actingweb.db.exceptions import DbError
from actingweb.oauth2_server.token_manager import TokenStoreUnavailable
from tests._adoption_helpers import make_config, uuid_email


def _raise(*_a: Any, **_k: Any) -> Any:
    raise DbError("simulated backend fault")


class TestCSpaToken:
    def test_spa_store_fault_raises_instead_of_answering_false(self) -> None:
        from actingweb.auth import Auth

        auth = Auth(None, config=make_config())
        with (
            mock.patch.object(Auth, "_check_spa_token", _raise),
            pytest.raises(DbError),
        ):
            auth._check_oauth2_token("spa-token")


class TestDMcpBearer:
    def test_actor_read_fault_is_a_store_fault_not_a_401(self) -> None:
        from tests.mcp_helpers import make_mcp_config, make_mcp_handler

        config = make_mcp_config()
        handler = make_mcp_handler(
            {"Authorization": f"Bearer tok-{uuid.uuid4().hex}"}, cfg=config
        )
        server = mock.Mock()
        server.validate_mcp_token.return_value = ("a1", "client-1", {"email": "x"})

        with (
            mock.patch(
                "actingweb.oauth2_server.oauth2_server.get_actingweb_oauth2_server",
                return_value=server,
            ),
            mock.patch.object(handler, "_get_or_create_actor_cached", _raise),
            pytest.raises(TokenStoreUnavailable),
        ):
            handler.authenticate_and_get_actor_cached()

    def test_trust_lookup_fault_propagates(self) -> None:
        from tests.mcp_helpers import make_mcp_handler

        handler = make_mcp_handler()
        actor = mock.Mock()
        type(actor).trust = mock.PropertyMock(side_effect=DbError("simulated"))
        with pytest.raises(DbError):
            handler._lookup_mcp_trust_relationship(actor, "client-1", {})


class TestEGClaimedSessionAndCallback:
    def test_claimed_session_completion_raises_on_a_fault(self) -> None:
        from actingweb.oauth_session import OAuth2SessionManager

        manager = OAuth2SessionManager(make_config())
        session = {"token_data": {"access_token": "at"}, "provider": "google"}
        with (
            mock.patch(
                "actingweb.oauth2.OAuth2Authenticator.lookup_or_create_actor_by_identifier",
                _raise,
            ),
            mock.patch(
                "actingweb.oauth2.OAuth2Authenticator.lookup_or_create_actor_by_email",
                _raise,
                create=True,
            ),
            pytest.raises(DbError),
        ):
            manager.complete_claimed_session(session, uuid_email())
