"""R3: credentials issued before the clean in place mint nothing after it.

Plan: thoughts/plans/2026-11-02-3-16-adoption-fault-followups.md, Phase 1.
"""

from __future__ import annotations

from collections import Counter
from typing import Any
from unittest.mock import patch

import pytest

from actingweb import session_generation
from actingweb.db import get_attribute
from actingweb.db.exceptions import DbError
from actingweb.oauth2_server.token_manager import (
    ActingWebTokenManager,
    TokenStoreUnavailable,
)
from tests._adoption_helpers import aid, create_core_actor, make_config, uuid_email


@pytest.fixture
def config() -> Any:
    return make_config()


def _code(manager: ActingWebTokenManager, actor_id: str) -> str:
    return manager.create_authorization_code(
        actor_id, "client-1", {"access_token": "provider-at"}
    )


def _exchange(manager: ActingWebTokenManager, code: str) -> dict[str, Any] | None:
    return manager.exchange_authorization_code(code=code, client_id="client-1")


class TestBump:
    def test_writes_a_new_value_each_time(self, config: Any) -> None:
        actor_id = aid(create_core_actor(config, uuid_email()))
        assert session_generation.current(actor_id, config) is None
        first = session_generation.bump(actor_id, config)
        second = session_generation.bump(actor_id, config)
        assert first and second and first != second
        assert session_generation.current(actor_id, config) == second

    def test_a_write_that_did_not_land_raises(self, config: Any) -> None:
        actor_id = aid(create_core_actor(config, uuid_email()))
        session_generation.bump(actor_id, config)
        with (
            patch.object(
                type(get_attribute(config)),
                "conditional_update_attr",
                return_value=False,
            ),
            pytest.raises(DbError),
        ):
            session_generation.bump(actor_id, config)

    def test_current_is_one_point_read(self, config: Any) -> None:
        actor_id = aid(create_core_actor(config, uuid_email()))
        calls: Counter[str] = Counter()
        cls = type(get_attribute(config))
        real_strict, real_bucket = cls.get_attr_strict, cls.get_bucket

        def _args(a: tuple[Any, ...]) -> tuple[Any, ...]:
            return a[1:] if a and isinstance(a[0], cls) else a

        def strict(*a: Any, **k: Any) -> Any:
            calls["get_attr_strict"] += 1
            return real_strict(*_args(a), **k)

        def bucket(*a: Any, **k: Any) -> Any:
            calls["get_bucket"] += 1
            return real_bucket(*_args(a), **k)

        with (
            patch.object(cls, "get_attr_strict", strict),
            patch.object(cls, "get_bucket", bucket),
        ):
            session_generation.current(actor_id, config)
        assert calls == Counter({"get_attr_strict": 1})


class TestMcpGrants:
    def test_a_code_issued_before_the_clean_mints_nothing(self, config: Any) -> None:
        actor_id = aid(create_core_actor(config, uuid_email()))
        manager = ActingWebTokenManager(config)
        code = _code(manager, actor_id)
        session_generation.bump(actor_id, config)

        assert _exchange(manager, code) is None
        assert not manager.revoke_actor_tokens(actor_id)  # nothing live was left

    def test_a_code_issued_after_the_clean_works(self, config: Any) -> None:
        actor_id = aid(create_core_actor(config, uuid_email()))
        session_generation.bump(actor_id, config)
        manager = ActingWebTokenManager(config)
        tokens = _exchange(manager, _code(manager, actor_id))
        assert tokens is not None and tokens["access_token"]

    def test_an_unstamped_code_works_only_on_an_actor_never_cleaned(
        self, config: Any
    ) -> None:
        actor_id = aid(create_core_actor(config, uuid_email()))
        manager = ActingWebTokenManager(config)
        assert _exchange(manager, _code(manager, actor_id)) is not None  # None == None

    def test_a_refresh_that_straddles_the_clean_mints_nothing(
        self, config: Any
    ) -> None:
        actor_id = aid(create_core_actor(config, uuid_email()))
        manager = ActingWebTokenManager(config)
        tokens = _exchange(manager, _code(manager, actor_id))
        assert tokens is not None
        # The clean's bump lands between the refresh's consume and its write;
        # its stamp is the one the chain began under, so it fails either way.
        session_generation.bump(actor_id, config)

        refreshed = manager.refresh_access_token(
            refresh_token=tokens["refresh_token"], client_id="client-1"
        )

        assert refreshed is None
        # Nothing it minted is live, and the access token the chain held went
        # with the consume.
        assert manager._snapshot_bucket(actor_id, manager.tokens_bucket) == {}

    def test_a_generation_read_fault_revokes_and_answers_unavailable(
        self, config: Any
    ) -> None:
        actor_id = aid(create_core_actor(config, uuid_email()))
        manager = ActingWebTokenManager(config)
        code = _code(manager, actor_id)
        with (
            patch.object(
                session_generation, "current", side_effect=DbError("generation")
            ),
            pytest.raises(TokenStoreUnavailable),
        ):
            _exchange(manager, code)
        assert manager.revoke_actor_tokens(actor_id) == 0

    def test_client_credentials_from_a_registration_before_the_clean(
        self, config: Any
    ) -> None:
        actor_id = aid(create_core_actor(config, uuid_email()))
        manager = ActingWebTokenManager(config)
        before = session_generation.current(actor_id, config)
        session_generation.bump(actor_id, config)
        assert (
            manager.create_access_token(actor_id, "client-1", client_generation=before)
            is None
        )
        now = session_generation.current(actor_id, config)
        assert manager.create_access_token(actor_id, "client-1", client_generation=now)


class TestClientManagerToken:
    """``ActorInterface.oauth_clients.generate_access_token`` passes the
    client's stamp: a client registered after the clean mints, one from
    before it does not (re-verification N1)."""

    def test_a_client_registered_after_the_clean_gets_a_token(
        self, config: Any
    ) -> None:
        from actingweb.interface.oauth_client_manager import OAuth2ClientManager

        actor_id = aid(create_core_actor(config, uuid_email()))
        manager = OAuth2ClientManager(actor_id, config)
        before = manager.create_client(client_name="Before", trust_type="mcp_client")
        session_generation.bump(actor_id, config)
        after = manager.create_client(client_name="After", trust_type="mcp_client")
        assert manager.generate_access_token(after["client_id"]) is not None
        assert manager.generate_access_token(before["client_id"]) is None


class TestSpaRefresh:
    def test_a_refresh_token_from_before_the_clean_mints_nothing(
        self, config: Any
    ) -> None:
        from actingweb.handlers.oauth2_spa import OAuth2SPAHandler
        from actingweb.oauth_session import get_oauth2_session_manager

        actor_id = aid(create_core_actor(config, uuid_email()))
        manager = get_oauth2_session_manager(config)
        refresh = manager.create_refresh_token(actor_id, "who@example.com")
        session_generation.bump(actor_id, config)
        handler = OAuth2SPAHandler.__new__(OAuth2SPAHandler)
        handler.config = config
        handler.response = None  # type: ignore[assignment]

        result = handler._handle_refresh_token({"refresh_token": refresh}, "json")

        assert result.get("error") is True and result.get("code") == "invalid_grant"

    def test_a_refresh_token_from_after_the_clean_works(self, config: Any) -> None:
        from actingweb.handlers.oauth2_spa import OAuth2SPAHandler
        from actingweb.oauth_session import get_oauth2_session_manager

        actor_id = aid(create_core_actor(config, uuid_email()))
        session_generation.bump(actor_id, config)
        refresh = get_oauth2_session_manager(config).create_refresh_token(
            actor_id, "who@example.com"
        )
        handler = OAuth2SPAHandler.__new__(OAuth2SPAHandler)
        handler.config = config
        handler.response = None  # type: ignore[assignment]

        result = handler._handle_refresh_token({"refresh_token": refresh}, "json")

        assert result.get("success") is True, result


class TestTheCleanBumps:
    def test_the_clean_writes_the_generation_before_the_passphrase(
        self, config: Any
    ) -> None:
        from actingweb.actor import Actor
        from actingweb.oauth2 import OAuth2Authenticator, OAuth2Provider

        creator = uuid_email()
        squat = create_core_actor(config, creator, auth_method=None)  # legacy
        order: list[str] = []
        real_bump = session_generation.bump
        real_modify = Actor.modify

        def bump(*a: Any, **k: Any) -> Any:
            order.append("bump")
            return real_bump(*a, **k)

        def modify(self: Any, *a: Any, **k: Any) -> Any:
            if "passphrase" in k:
                order.append("passphrase")
            return real_modify(self, *a, **k)

        provider = OAuth2Provider(
            "google",
            {
                "client_id": "c",
                "client_secret": "s",
                "auth_uri": "https://p/a",
                "token_uri": "https://p/t",
                "userinfo_uri": "https://p/u",
                "scope": "openid email",
                "redirect_uri": "https://test.example.com/oauth/callback",
            },
        )
        with (
            patch.object(session_generation, "bump", bump),
            patch.object(Actor, "modify", modify),
        ):
            adopted = OAuth2Authenticator(
                config, provider
            ).lookup_or_create_actor_by_identifier(creator)
        assert adopted is not None and adopted.id == aid(squat)
        assert order[:2] == ["bump", "passphrase"]

    def test_a_stamp_taken_during_the_clean_mints_nothing_after_it(
        self, config: Any
    ) -> None:
        """Verification 2026-11-03, issue 6: a code or client registration
        issued during the clean carried the clean's only generation and
        passed its check afterwards; the clean now bumps again before its
        second revoke."""
        from actingweb.oauth2 import OAuth2Authenticator, OAuth2Provider

        creator = uuid_email()
        squat = create_core_actor(config, creator, auth_method=None)
        during: list[str | None] = []
        real_purge = type(squat).purge_relationships

        def purge(self: Any, *a: Any, **k: Any) -> Any:
            during.append(session_generation.current(aid(squat), config))
            return real_purge(self, *a, **k)

        provider = OAuth2Provider(
            "google",
            {
                "client_id": "c",
                "client_secret": "s",
                "auth_uri": "https://p/a",
                "token_uri": "https://p/t",
                "userinfo_uri": "https://p/u",
                "scope": "openid email",
                "redirect_uri": "https://test.example.com/oauth/callback",
            },
        )
        with patch.object(type(squat), "purge_relationships", purge):
            adopted = OAuth2Authenticator(
                config, provider
            ).lookup_or_create_actor_by_identifier(creator)
        assert adopted is not None and adopted.id == aid(squat)
        assert during and during[0] is not None
        assert not session_generation.matches(during[0], aid(squat), config)


class TestRevokeEachRemoval:
    def test_a_failed_removal_does_not_skip_the_next(self, config: Any) -> None:
        """Verification 2026-11-03, issue 17: one revoke callback removed the
        access then the refresh token, so a failure on the first left the
        second."""
        actor = create_core_actor(config, uuid_email())
        session_generation.bump(aid(actor), config)
        done: list[str] = []

        def fail() -> None:
            raise DbError("remove access")

        assert (
            session_generation.guard(
                aid(actor), config, "stale", [fail, lambda: done.append("refresh")]
            )
            is False
        )
        assert done == ["refresh"]
