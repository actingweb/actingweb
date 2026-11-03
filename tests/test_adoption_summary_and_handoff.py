"""Adoption follow-ups: BK, BN, BP, the summary reads, the pending adoption,
the K4 bookkeeping folds and the load-time rewrite.

Plan: thoughts/plans/2026-11-02-3-16-adoption-fault-followups.md, Phase 2.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from actingweb import oauth2 as oauth2_module
from actingweb.actor import Actor
from actingweb.db.exceptions import DbError
from actingweb.interface.hooks import HookRegistry
from actingweb.oauth2 import OAuth2Authenticator, OAuth2Provider
from tests._adoption_helpers import (
    aid,
    create_core_actor,
    istore,
    make_config,
    uuid_email,
)


@pytest.fixture
def provider() -> OAuth2Provider:
    return OAuth2Provider(
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


@pytest.fixture
def env(provider: OAuth2Provider) -> Any:
    hooks = HookRegistry()
    adopted: list[dict[str, Any]] = []
    hooks.register_lifecycle_hook(
        "actor_adopted", lambda actor, **kw: adopted.append(kw)
    )
    config = make_config(hooks)
    return config, OAuth2Authenticator(config, provider), adopted


class TestBK:
    def test_a_row_renamed_away_is_not_the_creators(self) -> None:
        assert oauth2_module.row_holds_creator({"creator": "A@x.com"}, "a@x.com")
        assert not oauth2_module.row_holds_creator({"creator": "b@x.com"}, "a@x.com")
        assert not oauth2_module.row_holds_creator(None, "a@x.com")

    def test_get_from_creator_drops_a_stale_listing(self, env: Any) -> None:
        config, _auth, _adopted = env
        creator = uuid_email()
        renamed = create_core_actor(config, creator, auth_method="google_oauth2")
        stale = [{"id": aid(renamed)}]
        renamed.modify(creator=uuid_email())
        from actingweb.db import get_actor

        with patch.object(
            type(get_actor(config)), "get_by_creator", return_value=stale
        ):
            found = Actor(config=config)
            assert found.get_from_creator(creator) is False


class TestBN:
    def test_a_nested_hand_off_keeps_both_levels(self) -> None:
        outer = {
            "replaced_ids": ["a"],
            "removed_trusts": [{"peerid": "p1"}],
            "subscription_peers": ["s1"],
            "tokens_revoked": 2,
            "client_ids": ["c1"],
        }
        inner = {
            "replaced_ids": ["b"],
            "removed_trusts": [{"peerid": "p2"}],
            "subscription_peers": ["s2"],
            "tokens_revoked": 3,
            "client_ids": ["c2"],
        }
        merged = oauth2_module._merge_carried(outer, inner)
        assert merged["replaced_ids"] == ["a", "b"]
        assert [t["peerid"] for t in merged["removed_trusts"]] == ["p1", "p2"]
        assert merged["tokens_revoked"] == 5 and merged["client_ids"] == ["c1", "c2"]

    def test_an_unknown_count_stays_unknown(self) -> None:
        merged = oauth2_module._merge_carried(
            {"removed_trusts": None, "subscription_peers": ["s"]},
            {"removed_trusts": [{"peerid": "p"}], "subscription_peers": None},
        )
        assert merged["removed_trusts"] is None
        assert merged["subscription_peers"] is None


class TestSummary:
    def test_a_fault_reports_unknown_not_zero(self, env: Any) -> None:
        config, _auth, _adopted = env
        victim = create_core_actor(config, uuid_email())
        from actingweb import trust as trust_module

        with patch.object(trust_module.Trusts, "fetch", side_effect=DbError("x")):
            assert oauth2_module._summary_or_unknown(config, aid(victim)) == (
                None,
                None,
            )


class TestBP:
    def test_a_replacement_scans_the_spa_buckets_once(self, env: Any) -> None:
        config, auth, _adopted = env
        creator = uuid_email()
        create_core_actor(config, creator, auth_method="factory")
        create_core_actor(config, creator, auth_method="factory")
        calls: list[list[str]] = []
        real = oauth2_module._revoke_spa_tokens

        def spy(cfg: Any, ids: list[str]) -> int:
            calls.append(list(ids))
            return real(cfg, ids)

        with patch.object(oauth2_module, "_revoke_spa_tokens", spy):
            adopted = auth.lookup_or_create_actor_by_identifier(creator)
        assert adopted is not None
        assert len(calls) == 1 and len(calls[0]) == 2


class TestPendingAdoption:
    def test_a_create_that_raised_is_announced_by_the_next_sign_in(
        self, env: Any
    ) -> None:
        config, auth, adopted = env
        creator = uuid_email()
        squat = create_core_actor(config, creator, auth_method="factory")
        real_create = oauth2_module._create_actor_for_identifier
        calls = {"n": 0}

        def flaky(*a: Any, **k: Any) -> Any:
            calls["n"] += 1
            if calls["n"] == 1:
                raise DbError("create")
            return real_create(*a, **k)

        with patch.object(oauth2_module, "_create_actor_for_identifier", flaky):
            with pytest.raises(DbError):
                auth.lookup_or_create_actor_by_identifier(creator)
            assert adopted == []
            created = auth.lookup_or_create_actor_by_identifier(creator)
        assert created is not None and created.id != aid(squat)
        assert len(adopted) == 1
        assert adopted[0]["previous_actor_id"] == aid(squat)
        assert adopted[0]["removed_trusts"] is None  # unknown, not zero

    def test_a_completed_adoption_leaves_no_pending_record(self, env: Any) -> None:
        config, auth, adopted = env
        creator = uuid_email()
        squat = create_core_actor(config, creator, auth_method="factory")
        first = auth.lookup_or_create_actor_by_identifier(creator)
        assert first is not None and len(adopted) == 1
        assert adopted[0]["previous_actor_id"] == aid(squat)
        from actingweb.constants import ACTINGWEB_SYSTEM_ACTOR, PENDING_ADOPTION_BUCKET
        from actingweb.db import get_attribute

        assert (
            get_attribute(config).get_attr_strict(
                actor_id=ACTINGWEB_SYSTEM_ACTOR,
                bucket=PENDING_ADOPTION_BUCKET,
                name=creator,
            )
            is None
        )


class TestK4Folds:
    def test_the_vouched_successor_provider_write_does_not_fail_the_sign_in(
        self, env: Any
    ) -> None:
        from actingweb.attribute import InternalStore

        config, auth, _adopted = env
        creator = uuid_email()
        create_core_actor(config, creator, auth_method="factory")
        owner = create_core_actor(config, creator, auth_method="google_oauth2")
        real = InternalStore.__setattr__

        def faulting(self: Any, name: str, value: Any) -> None:
            if name == "oauth_provider":
                raise DbError("provider write")
            real(self, name, value)

        with patch.object(InternalStore, "__setattr__", faulting):
            signed_in = auth.lookup_or_create_actor_by_identifier(creator)
        assert signed_in is not None and signed_in.id == aid(owner)


class TestLoadRewrite:
    def test_an_unvouched_actors_email_does_not_rename_it(self) -> None:
        config = make_config()
        config.force_email_prop_as_creator = True
        creator = uuid_email()
        actor = create_core_actor(config, creator, auth_method="factory")
        istore(actor).email = "previous@example.com"
        loaded = Actor(actor_id=aid(actor), config=config)
        assert loaded.creator == creator

    def test_a_vouched_actors_email_still_does(self) -> None:
        config = make_config()
        config.force_email_prop_as_creator = True
        actor = create_core_actor(config, uuid_email(), auth_method="google_oauth2")
        new_email = uuid_email()
        istore(actor).email = new_email
        loaded = Actor(actor_id=aid(actor), config=config)
        assert loaded.creator == new_email


class TestNativeValidateBeforeWrite:
    def test_a_rejected_native_sign_in_writes_no_provider_token(self, env: Any) -> None:
        """O2c on the SPA native grants: oauth_success decides first."""
        from actingweb.handlers.oauth2_spa import OAuth2SPAHandler

        config, auth, _adopted = env
        hooks = HookRegistry()
        hooks.register_lifecycle_hook("oauth_success", lambda actor, **kw: False)
        creator = uuid_email()
        owner = create_core_actor(config, creator, auth_method="google_oauth2")
        handler = OAuth2SPAHandler.__new__(OAuth2SPAHandler)
        handler.config = config
        handler.hooks = hooks
        handler.response = None  # type: ignore[assignment]

        result = handler._finalize_native_session(
            "google",
            auth,
            creator,
            {"email": creator, "email_verified": True},
            {},
            "json",
            provider_access_token="refused-token",
        )

        assert result.get("status_code") == 403
        assert istore(Actor(actor_id=aid(owner), config=config)).oauth_token is None
