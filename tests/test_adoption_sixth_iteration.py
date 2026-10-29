"""Adoption after the sixth verification (3.16).

Strict creator listings (index lag, a missing victim, a successor that cannot
be read), the record a recursive clean reports, factory actors beside a
vouched one, the create rollback and the MCP bridge's winner, the email of a
provider-id creator, peer-trustee rows of unlisted types, and the one marker
classifier. Faults are injected at the backend class, so every test runs on
either backend unless it says otherwise.
"""

import os
import uuid
from typing import Any, cast
from unittest.mock import patch

import pytest

from actingweb import oauth2 as oauth2_module
from actingweb.actor import Actor
from actingweb.db import get_actor, get_peer_trustee, get_peer_trustee_list
from actingweb.oauth2 import OAuth2Authenticator, OAuth2Provider, classify_marker
from actingweb.oauth_session import OAuth2SessionManager
from tests._adoption_helpers import (
    aid,
    create_core_actor,
    istore,
    make_config,
    uuid_email,
)
from tests.mcp_helpers import make_mcp_config, make_mcp_handler
from tests.test_adoption_write_faults import marker_write_fault


@pytest.fixture
def auth() -> OAuth2Authenticator:
    provider = OAuth2Provider(
        "google",
        {
            "client_id": "cid",
            "client_secret": "csec",
            "auth_uri": "https://provider.test/auth",
            "token_uri": "https://provider.test/token",
            "userinfo_uri": "https://provider.test/userinfo",
            "scope": "openid email",
            "redirect_uri": "https://test.example.com/oauth/callback",
        },
    )
    return OAuth2Authenticator(make_config(), provider)


def _ids(config: Any, creator: str) -> list[str]:
    rows: Any = get_actor(config).get_by_creator(creator=creator) or []
    if isinstance(rows, dict):
        rows = [rows]
    return sorted(str(r["id"]) for r in rows if r)


def _with_id(config: Any, creator: str, prefix: str, auth_method: str | None) -> Actor:
    actor = Actor(config=config)
    assert actor.create(
        url="https://test.example.com/",
        creator=creator,
        passphrase="pass",
        actor_id=f"{prefix}{uuid.uuid4().hex}",
        auth_method=auth_method or "app",
    )
    if auth_method is None:
        istore(actor).auth_method = None
    return actor


class _Hooks:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute_lifecycle_hooks(self, name: str, *_a: Any, **kw: Any) -> bool:
        self.calls.append((name, kw))
        return True

    def kwargs(self, name: str) -> dict[str, Any]:
        return next(kw for n, kw in self.calls if n == name)


class TestStrictCreatorListing:
    @pytest.mark.skipif(
        os.environ.get("DATABASE_BACKEND", "dynamodb") != "dynamodb",
        reason="the creator index's lag is DynamoDB's",
    )
    def test_index_entry_for_a_deleted_actor_does_not_fail_the_sign_in(
        self, auth
    ) -> None:
        # Issue AX: the squatter deletes one of their factory actors just
        # before the owner signs in; the index still lists it.
        from actingweb.db.dynamodb.actor import Actor as ActorModel

        config = auth.config
        creator = uuid_email()
        squat = _with_id(config, creator, "00", "factory")
        real_query = ActorModel.creator_index.query
        ghost = type("Row", (), {"id": f"ff{uuid.uuid4().hex}"})()

        def lagging(*a: Any, **k: Any) -> Any:
            return [*real_query(*a, **k), ghost]

        with patch.object(ActorModel.creator_index, "query", lagging):
            signed_in = auth.lookup_or_create_actor_by_identifier(creator)

        assert signed_in is not None and signed_in.id != squat.id
        assert not Actor(actor_id=aid(squat), config=config).id

    def test_victim_missing_from_the_listing_fails_closed(self, auth) -> None:
        # Issue AY: a partial listing would sweep only what it saw.
        config = auth.config
        creator = uuid_email()
        squat = _with_id(config, creator, "00", "factory")
        sibling = _with_id(config, creator, "ff", "factory")

        with patch.object(
            oauth2_module,
            "_creator_rows",
            lambda c, cr: [{"id": sibling.id}],
        ):
            result = oauth2_module.adopt_actor(
                squat, provider=auth.provider, config=config, hooks=None
            )

        assert result is None
        assert Actor(actor_id=aid(squat), config=config).id == squat.id
        assert Actor(actor_id=aid(sibling), config=config).id == sibling.id

    def test_unreadable_remaining_actor_creates_no_successor(self, auth) -> None:
        # Issue AZ: a new vouched actor would outrank the owner's for good.
        config = auth.config
        creator = uuid_email()
        squat = _with_id(config, creator, "00", "factory")
        owner = _with_id(config, creator, "ff", None)

        with patch.object(Actor, "get_from_creator", lambda self, creator=None: False):
            result = oauth2_module.adopt_actor(
                squat, provider=auth.provider, config=config, hooks=None
            )

        assert result is None
        assert _ids(config, creator) == [aid(owner)]


class TestRecursiveCleanReportsTheReplacement:
    """Issue BA."""

    def test_actor_adopted_names_the_factory_actor_it_replaced(self, auth) -> None:
        config = auth.config
        creator = uuid_email()
        squat = _with_id(config, creator, "00", "factory")
        owner = _with_id(config, creator, "ff", None)
        hooks = _Hooks()

        result = oauth2_module.adopt_actor(
            squat, provider=auth.provider, config=config, hooks=cast(Any, hooks)
        )

        assert result is not None and result.id == owner.id
        adopted = [n for n, _ in hooks.calls].count("actor_adopted")
        assert adopted == 1
        kw = hooks.kwargs("actor_adopted")
        assert kw["mode"] == "cleaned"
        assert kw["removed_sibling_ids"] == [squat.id]


class TestFactoryActorsBesideAVouchedOne:
    """Issue BB."""

    def test_vouched_sign_in_removes_the_factory_actors_beside_it(self, auth) -> None:
        config = auth.config
        creator = uuid_email()
        squats = [_with_id(config, creator, p, "factory") for p in ("00", "01", "02")]
        owner = _with_id(config, creator, "ff", "google_oauth2")
        real = OAuth2SessionManager.revoke_all_tokens_for_actors
        passes: list[list[str]] = []

        def counted(self: Any, actor_ids: list[str], **kw: Any) -> int:
            passes.append(list(actor_ids))
            return real(self, actor_ids, **kw)

        with patch.object(
            OAuth2SessionManager, "revoke_all_tokens_for_actors", counted
        ):
            signed_in = auth.lookup_or_create_actor_by_identifier(creator)

        assert signed_in is not None and signed_in.id == owner.id
        assert _ids(config, creator) == [aid(owner)]
        # One pass over the global token buckets for all three.
        assert passes == [sorted(aid(s) for s in squats)]

    def test_a_failed_sweep_still_signs_the_owner_in(self, auth) -> None:
        config = auth.config
        creator = uuid_email()
        squat = _with_id(config, creator, "00", "factory")
        owner = _with_id(config, creator, "ff", "google_oauth2")

        with patch.object(oauth2_module, "_sweep_factory_actors", lambda *a: None):
            signed_in = auth.lookup_or_create_actor_by_identifier(creator)

        assert signed_in is not None and signed_in.id == owner.id
        assert Actor(actor_id=aid(squat), config=config).id == squat.id


class TestCreateRollbackAndTheBridgeWinner:
    """Issue BC."""

    def test_failed_marker_and_rollback_leave_the_object_unbound(self) -> None:
        config = make_config()
        actor_id = f"fixed-{uuid.uuid4().hex}"
        actor = Actor(config=config)
        try:
            with (
                marker_write_fault(config, actor_id),
                patch.object(type(get_actor(config)), "delete", lambda self: False),
            ):
                assert (
                    actor.create(
                        url="https://test.example.com/",
                        creator=uuid_email(),
                        passphrase="p",
                        actor_id=actor_id,
                    )
                    is False
                )

            assert actor.id is None and actor.handle is None and actor.store is None
        finally:
            left = Actor(actor_id=actor_id, config=config)
            if left.id:
                left.delete()

    def test_bridge_refuses_an_unmarked_winner(self) -> None:
        config = make_mcp_config()
        handler = make_mcp_handler(cfg=config)
        actor_id = f"mcp{uuid.uuid4().hex}"
        real_create = Actor.create

        def unmarked_row_wins(self: Actor, *a: Any, **kw: Any) -> bool:
            other = Actor(config=config)
            assert real_create(other, *a, **kw)
            istore(other).auth_method = None  # its marker never landed
            return real_create(self, *a, **kw)

        try:
            with patch.object(Actor, "create", unmarked_row_wins):
                result = handler._get_or_create_actor_cached(
                    actor_id, {"email": uuid_email()}, 0.0
                )

            assert result is None
        finally:
            left = Actor(actor_id=actor_id, config=config)
            if left.id:
                left.delete()


class TestProviderIdCreatorEmail:
    """Issue BD."""

    def test_clean_sets_the_providers_email_for_a_provider_id_creator(
        self, auth
    ) -> None:
        config = auth.config
        creator = f"apple:{uuid.uuid4().hex}"
        proven = uuid_email()
        legacy = create_core_actor(config, creator, auth_method=None)
        istore(legacy).email = "squatter@example.com"

        assert oauth2_module.adopt_actor(
            legacy,
            provider=auth.provider,
            config=config,
            hooks=None,
            user_info={"email": proven.upper()},
        )

        assert istore(Actor(actor_id=aid(legacy), config=config)).email == proven

    def test_clean_drops_the_email_when_the_provider_gave_none(self, auth) -> None:
        config = auth.config
        legacy = create_core_actor(
            config, f"apple:{uuid.uuid4().hex}", auth_method=None
        )
        istore(legacy).email = "squatter@example.com"

        assert oauth2_module.adopt_actor(
            legacy, provider=auth.provider, config=config, hooks=None
        )

        assert istore(Actor(actor_id=aid(legacy), config=config)).email is None


class TestPeerTrusteeRowsOfUnlistedTypes:
    """Issue BE."""

    def test_purge_removes_a_peer_trustee_of_a_type_not_in_config(self) -> None:
        config = make_config()
        actor = create_core_actor(config, uuid_email(), auth_method=None)
        assert get_peer_trustee(config).create(
            actor_id=aid(actor),
            peerid=f"peer-{uuid.uuid4().hex}",
            peer_type="urn:actingweb:test:unlisted",
            baseuri="http://127.0.0.1:9/never-called",
            passphrase="squatter",
        )

        purged = actor.purge_relationships(notify_peers=False)

        assert purged["confirmed"] is True
        assert not get_peer_trustee_list(config).fetch(actor_id=aid(actor))


class TestClassifyMarker:
    """Issue BF: one classifier, one meaning for an unreadable bucket."""

    def test_classes_and_unreadable(self) -> None:
        config = make_config()
        vouched = create_core_actor(config, uuid_email(), auth_method="google_oauth2")
        squat = create_core_actor(config, uuid_email(), auth_method="factory")
        legacy = create_core_actor(config, uuid_email(), auth_method=None)

        assert classify_marker(config, aid(vouched)) == "vouched"
        assert classify_marker(config, aid(squat)) == "replace"
        assert classify_marker(config, aid(legacy)) == "unvouched"
        with patch("actingweb.attribute.InternalStore.loaded", False):
            assert classify_marker(config, aid(vouched)) is None


class TestSweepAfterTheSeventhVerification:
    """Issues BH, BI, BJ."""

    def test_sibling_vouched_during_the_sweep_is_kept(self, auth) -> None:
        # BH: the marker is read again just before each delete.
        config = auth.config
        creator = uuid_email()
        first = _with_id(config, creator, "00", "factory")
        second = _with_id(config, creator, "01", "factory")
        owner = _with_id(config, creator, "ff", "google_oauth2")
        real_remove = oauth2_module._remove_for_replacement

        def vouch_second_after_first(victim: Actor, **kw: Any) -> Any:
            removed = real_remove(victim, **kw)
            if victim.id == first.id:
                assert istore(Actor(actor_id=aid(second), config=config)).set_confirmed(
                    "auth_method", "operator"
                )
            return removed

        with patch.object(
            oauth2_module, "_remove_for_replacement", vouch_second_after_first
        ):
            signed_in = auth.lookup_or_create_actor_by_identifier(creator)

        assert signed_in is not None and signed_in.id == owner.id
        assert not Actor(actor_id=aid(first), config=config).id
        assert Actor(actor_id=aid(second), config=config).id == second.id

    def test_one_sign_in_removes_at_most_the_limit(self, auth) -> None:
        # BI: each removal is a full wipe inside the request.
        config = auth.config
        creator = uuid_email()
        squats = [_with_id(config, creator, p, "factory") for p in ("00", "01", "02")]
        owner = _with_id(config, creator, "ff", "google_oauth2")

        with patch.object(oauth2_module, "SWEEP_LIMIT", 2):
            assert auth.lookup_or_create_actor_by_identifier(creator) is not None
            assert _ids(config, creator) == sorted([aid(squats[2]), aid(owner)])
            assert auth.lookup_or_create_actor_by_identifier(creator) is not None

        assert _ids(config, creator) == [aid(owner)]

    @pytest.mark.skipif(
        os.environ.get("DATABASE_BACKEND", "dynamodb") != "dynamodb",
        reason="DynamoDB's eventually consistent query",
    )
    def test_peer_trustee_reads_are_consistent(self) -> None:
        # BJ: the purge re-reads right after its deletes.
        from actingweb.db.dynamodb.peertrustee import PeerTrustee

        config = make_config()
        actor = create_core_actor(config, uuid_email(), auth_method=None)
        calls: list[dict[str, Any]] = []
        real_query = PeerTrustee.query

        def spy(*a: Any, **k: Any) -> Any:
            calls.append(k)
            return real_query(*a, **k)

        with patch.object(PeerTrustee, "query", spy):
            lister = get_peer_trustee_list(config)
            lister.fetch(actor_id=aid(actor))
            lister.delete()

        assert calls and all(c.get("consistent_read") is True for c in calls)
