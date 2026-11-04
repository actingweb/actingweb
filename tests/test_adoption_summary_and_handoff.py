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


def _nothing_pending(config: Any, creator: str) -> bool:
    """No unannounced pending adoption for ``creator``: the record is gone or
    claimed (re-verification 5, X3: a claimed row stays until its TTL)."""
    from actingweb.constants import ACTINGWEB_SYSTEM_ACTOR, PENDING_ADOPTION_BUCKET
    from actingweb.db import get_attribute

    row = get_attribute(config).get_attr_strict(
        actor_id=ACTINGWEB_SYSTEM_ACTOR, bucket=PENDING_ADOPTION_BUCKET, name=creator
    )
    return row is None or bool(row["data"].get("announced"))


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

    def test_an_unvouched_create_does_not_announce_it(self, env: Any) -> None:
        """Re-verification N11: the email form's unverified create proves
        nothing about the creator, so it must not be announced as the one
        that adopted the squatter's account."""
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
            unvouched = auth.lookup_or_create_actor_by_identifier(
                creator, create_only=True, auth_method="email_unverified"
            )
        assert unvouched is not None
        assert adopted == []
        from actingweb.constants import ACTINGWEB_SYSTEM_ACTOR, PENDING_ADOPTION_BUCKET
        from actingweb.db import get_attribute

        # The record stays for a sign-in that proves the address.
        row = get_attribute(config).get_attr_strict(
            actor_id=ACTINGWEB_SYSTEM_ACTOR,
            bucket=PENDING_ADOPTION_BUCKET,
            name=creator,
        )
        assert row is not None and row["data"]["actor_id"] == aid(squat)
        assert not row["data"].get("announced")

    def test_the_sign_in_that_adopts_the_unvouched_actor_announces_it(
        self, env: Any
    ) -> None:
        """Re-verification 3, V2: the record N11 left waiting is announced by
        the vouched sign-in that later adopts the email form's actor, once,
        and does not linger."""
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
            unvouched = auth.lookup_or_create_actor_by_identifier(
                creator, create_only=True, auth_method="email_unverified"
            )
        assert unvouched is not None and adopted == []
        signed_in = auth.lookup_or_create_actor_by_identifier(creator)
        assert signed_in is not None
        previous = [kw["previous_actor_id"] for kw in adopted]
        assert aid(squat) in previous
        assert previous.count(aid(squat)) == 1

        assert _nothing_pending(config, creator)
        # A later sign-in does not announce it again.
        auth.lookup_or_create_actor_by_identifier(creator)
        assert [kw["previous_actor_id"] for kw in adopted].count(aid(squat)) == 1

    def test_an_earlier_replacement_survives_a_failure_after_the_rewrite(
        self, env: Any
    ) -> None:
        """Re-verification 4, W2: the earlier replacement is kept inside the
        rewritten record, so this sign-in failing after the write loses
        nothing, and the next one announces both, once each."""
        from actingweb.constants import ACTINGWEB_SYSTEM_ACTOR, PENDING_ADOPTION_BUCKET
        from actingweb.db import get_attribute

        config, auth, adopted = env
        creator = uuid_email()
        squat = create_core_actor(config, creator, auth_method="factory")
        # An earlier replacement that was never announced.
        oauth2_module._record_pending_adoption(config, creator, "x-old", squat)
        with patch.object(oauth2_module, "_remove_for_replacement", return_value=None):
            try:
                auth.lookup_or_create_actor_by_identifier(creator)
            except DbError:
                pass
        row = get_attribute(config).get_attr_strict(
            actor_id=ACTINGWEB_SYSTEM_ACTOR,
            bucket=PENDING_ADOPTION_BUCKET,
            name=creator,
        )
        assert row is not None
        assert row["data"]["actor_id"] == aid(squat)
        assert [e["actor_id"] for e in row["data"]["earlier"]] == ["x-old"]
        assert adopted == []

        signed_in = auth.lookup_or_create_actor_by_identifier(creator)
        assert signed_in is not None
        previous = [kw["previous_actor_id"] for kw in adopted]
        assert previous.count("x-old") == 1
        assert previous.count(aid(squat)) == 1
        assert _nothing_pending(config, creator)

    def test_a_fault_reading_the_record_fails_the_sign_in_with_nothing_removed(
        self, env: Any
    ) -> None:
        """W2: the record is written strictly before anything is removed."""
        from actingweb.constants import PENDING_ADOPTION_BUCKET
        from actingweb.db import get_attribute

        config, auth, _adopted = env
        creator = uuid_email()
        squat = create_core_actor(config, creator, auth_method="factory")
        db_type = type(get_attribute(config))
        real = db_type.get_attr_strict

        def faulty(self: Any, *a: Any, **k: Any) -> Any:
            if k.get("bucket") == PENDING_ADOPTION_BUCKET:
                raise DbError("read")
            return real(self, *a, **k)

        with patch.object(db_type, "get_attr_strict", faulty):
            with pytest.raises(DbError):
                auth.lookup_or_create_actor_by_identifier(creator)
        assert Actor(actor_id=aid(squat), config=config).id == aid(squat)

    def test_a_vouched_sign_in_announces_what_a_failed_replacement_left(
        self, env: Any
    ) -> None:
        """Re-verification 5, X4: a replacement that failed after its
        successor's create committed leaves the successor vouched, and every
        later sign-in took the vouched branch, which read no record."""
        config, auth, adopted = env
        creator = uuid_email()
        successor = create_core_actor(config, creator, auth_method="email_verified")
        oauth2_module._record_pending_adoption(config, creator, "x-old", successor)
        assert auth.lookup_or_create_actor_by_identifier(creator) is not None
        assert [kw["previous_actor_id"] for kw in adopted] == ["x-old"]
        assert adopted[0]["mode"] == "replaced"
        assert _nothing_pending(config, creator)
        auth.lookup_or_create_actor_by_identifier(creator)
        assert [kw["previous_actor_id"] for kw in adopted] == ["x-old"]

    def test_without_hooks_the_record_is_left_for_a_sign_in_that_has_them(
        self, env: Any
    ) -> None:
        """Re-verification 6, Y1: claiming with no hooks lost the event."""
        config, _auth, adopted = env
        creator = uuid_email()
        successor = create_core_actor(config, creator, auth_method="email_verified")
        oauth2_module._record_pending_adoption(config, creator, "x-old", successor)
        oauth2_module._announce_pending(config, None, successor, None, skip=set())
        assert not _nothing_pending(config, creator)  # still waiting
        hooks = HookRegistry()
        hooks.register_lifecycle_hook(
            "actor_adopted", lambda actor, **kw: adopted.append(kw)
        )
        oauth2_module._announce_pending(config, hooks, successor, None, skip=set())
        assert [kw["previous_actor_id"] for kw in adopted] == ["x-old"]

    def test_an_actor_is_never_announced_as_having_replaced_itself(
        self, env: Any
    ) -> None:
        """Y2: a replacement that recorded V and failed before removing it
        leaves a record naming V; V is later vouched."""
        config, auth, adopted = env
        creator = uuid_email()
        actor = create_core_actor(config, creator, auth_method="email_verified")
        oauth2_module._record_pending_adoption(config, creator, aid(actor), actor)
        assert auth.lookup_or_create_actor_by_identifier(creator) is not None
        assert aid(actor) not in [kw["previous_actor_id"] for kw in adopted]

    def test_a_first_write_that_loses_to_another_fails_closed(self, env: Any) -> None:
        """X2: with no row read, the write is a create-if-absent, so a
        concurrent replacement's record is never overwritten."""
        from actingweb.constants import PENDING_ADOPTION_BUCKET
        from actingweb.db import get_attribute

        config, _auth, _adopted = env
        creator = uuid_email()
        first = create_core_actor(config, creator, auth_method="factory")
        oauth2_module._record_pending_adoption(config, creator, aid(first), first)
        db_type = type(get_attribute(config))
        real = db_type.get_attr_strict

        def unseen(self: Any, *a: Any, **k: Any) -> Any:
            if k.get("bucket") == PENDING_ADOPTION_BUCKET:
                return None  # read before the other replacement wrote
            return real(self, *a, **k)

        with patch.object(db_type, "get_attr_strict", unseen):
            with pytest.raises(DbError):
                oauth2_module._record_pending_adoption(config, creator, "other", first)

    def test_a_completed_adoption_leaves_no_pending_record(self, env: Any) -> None:
        config, auth, adopted = env
        creator = uuid_email()
        squat = create_core_actor(config, creator, auth_method="factory")
        first = auth.lookup_or_create_actor_by_identifier(creator)
        assert first is not None and len(adopted) == 1
        assert adopted[0]["previous_actor_id"] == aid(squat)

        assert _nothing_pending(config, creator)

    def test_a_hand_off_that_ends_cleaned_leaves_no_pending_record(
        self, env: Any
    ) -> None:
        """Verification 2026-11-03, issue 12: the record was cleared only
        for mode "replaced", so a replacement that handed off to the owner's
        own unvouched actor left it for a later create to announce again."""
        config, auth, adopted = env
        creator = uuid_email()
        squat = create_core_actor(config, creator, auth_method="factory")
        real_sweep = oauth2_module._sweep_factory_actors

        def sweep_then_owner_appears(*a: Any, **k: Any) -> Any:
            # The owner's own unvouched actor shows up after the listing (the
            # race the successor re-listing exists for): the replacement
            # hands off to it and ends "cleaned".
            out = real_sweep(*a, **k)
            create_core_actor(config, creator, auth_method=None)
            return out

        with patch.object(
            oauth2_module, "_sweep_factory_actors", sweep_then_owner_appears
        ):
            result = auth.lookup_or_create_actor_by_identifier(creator)
        assert result is not None and result.id != aid(squat)
        assert len(adopted) == 1

        assert _nothing_pending(config, creator)


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
