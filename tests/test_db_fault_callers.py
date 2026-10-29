"""Callers that used to act on a folded read (3.16, Phase 2 rows B1-B11 of
``thoughts/plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md``).

Each test injects a read fault (a ``DbError``, as both backends raise since
3.16) where the caller once read "absent" and then created, overwrote or
deleted something. The fault must propagate (the integrations answer 503)
and leave storage as it was.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest import mock

import pytest

from actingweb.actor import Actor
from actingweb.constants import PEER_PERMISSIONS_BUCKET, TRUST_PERMISSIONS_BUCKET
from actingweb.db import (
    get_actor,
    get_attribute,
    get_peer_trustee_list,
    get_subscription,
    get_trust_list,
)
from actingweb.db.exceptions import DbError
from tests._adoption_helpers import (
    aid,
    backend_fault,
    create_core_actor,
    make_config,
    raise_db_error,
    seam_fault,
    uuid_email,
)


@pytest.fixture
def config() -> Any:
    return make_config()


def _attr_row(config: Any, actor_id: str, bucket: str, name: str) -> Any:
    return get_attribute(config).get_attr(actor_id=actor_id, bucket=bucket, name=name)


class TestB1OAuthTrustUpsert:
    def test_trust_read_fault_writes_no_new_secret(self, config: Any) -> None:
        from actingweb.interface.trust_manager import TrustManager

        actor = create_core_actor(config, uuid_email())
        tm = TrustManager(actor)
        assert tm.create_or_update_oauth_trust(
            email="client@example.com",
            trust_type="mcp_client",
            established_via="oauth2",
        )
        before = get_trust_list(config).fetch(actor_id=aid(actor))
        assert before

        with seam_fault(config, "trust", "Trust", "get"), pytest.raises(DbError):
            tm.create_or_update_oauth_trust(
                email="client@example.com",
                trust_type="mcp_client",
                established_via="oauth2",
            )

        assert get_trust_list(config).fetch(actor_id=aid(actor)) == before


class TestB2PermissionOverridePut:
    def test_override_read_fault_writes_nothing(self, config: Any) -> None:
        from actingweb.aw_web_request import AWWebObj
        from actingweb.handlers.trust import TrustPermissionHandler
        from actingweb.trust_permissions import (
            TrustPermissionStore,
            create_permission_override,
        )

        actor = create_core_actor(config, uuid_email())
        store = TrustPermissionStore(config)
        assert store.store_permissions(
            create_permission_override(
                aid(actor), "peer1", "friend", {"properties": {"allowed": ["a/*"]}}
            )
        )
        store.clear_cache()
        before = _attr_row(
            config, aid(actor), TRUST_PERMISSIONS_BUCKET, f"{aid(actor)}:peer1"
        )
        assert before

        webobj = AWWebObj(
            url="https://test.example.com/x",
            body=json.dumps({"properties": {"allowed": ["b/*"]}}),
        )
        handler = TrustPermissionHandler(webobj, config)
        me = mock.Mock()
        me.get_trust_relationships.return_value = [{"peerid": "peer1"}]
        auth = mock.Mock(success=True, actor=me)
        auth.authorize.return_value = True
        handler.authenticate_actor = mock.Mock(return_value=auth)  # type: ignore[method-assign]

        with (
            mock.patch("actingweb.handlers.trust.PERMISSION_SYSTEM_AVAILABLE", True),
            mock.patch(
                "actingweb.handlers.trust.get_trust_permission_store",
                return_value=store,
            ),
            backend_fault(
                config,
                "get_attr",
                lambda a, b, _n: b == TRUST_PERMISSIONS_BUCKET,
                raise_db_error,
            ),
            pytest.raises(DbError),
        ):
            handler.put(aid(actor), "friend", "peer1")

        after = _attr_row(
            config, aid(actor), TRUST_PERMISSIONS_BUCKET, f"{aid(actor)}:peer1"
        )
        assert after == before


class TestB3PermissionCache:
    def test_a_fault_caches_nothing_and_the_next_read_finds_the_override(
        self, config: Any
    ) -> None:
        from actingweb.trust_permissions import (
            TrustPermissionStore,
            create_permission_override,
        )

        actor = create_core_actor(config, uuid_email())
        store = TrustPermissionStore(config)
        assert store.store_permissions(
            create_permission_override(
                aid(actor), "peer1", "friend", {"properties": {"allowed": ["a/*"]}}
            )
        )
        store.clear_cache()

        with (
            backend_fault(
                config,
                "get_attr",
                lambda a, b, _n: b == TRUST_PERMISSIONS_BUCKET,
                raise_db_error,
            ),
            pytest.raises(DbError),
        ):
            store.get_permissions(aid(actor), "peer1")

        assert f"{aid(actor)}:peer1" not in store._cache
        assert store.get_permissions(aid(actor), "peer1") is not None


class TestB4UniqueCreatorCreate:
    def test_listing_fault_refuses_the_create(self, config: Any) -> None:
        config.unique_creator = True
        creator = uuid_email()
        create_core_actor(config, creator)
        with (
            seam_fault(config, "actor", "Actor", "creator_index.query"),
            pytest.raises(DbError),
        ):
            Actor(config=config).create(
                url="https://test.example.com/", creator=creator, passphrase="p"
            )

        assert len(get_actor(config).get_by_creator(creator=creator) or []) == 1


class TestB5SignInLookup:
    def test_listing_fault_creates_no_actor(self, config: Any) -> None:
        from actingweb.oauth2 import OAuth2Authenticator, OAuth2Provider

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
        auth = OAuth2Authenticator(config, provider)
        creator = uuid_email()

        with (
            seam_fault(config, "actor", "Actor", "creator_index.query"),
            pytest.raises(DbError),
        ):
            auth.lookup_or_create_actor_by_identifier(creator)

        assert get_actor(config).get_by_creator(creator=creator) == []


class TestB6PeerTrustee:
    def test_lookup_fault_contacts_no_peer_factory(self, config: Any) -> None:
        actor = create_core_actor(config, uuid_email())

        with (
            seam_fault(config, "peertrustee", "PeerTrustee", "get"),
            mock.patch("actingweb.actor.requests") as http,
            pytest.raises(DbError),
        ):
            actor.get_peer_trustee(peerid="peer-1")

        assert not http.method_calls
        assert get_peer_trustee_list(config).fetch(actor_id=aid(actor)) == []


class TestB7CallbackProcessor:
    def test_state_read_fault_leaves_queue_and_state_untouched(
        self, config: Any
    ) -> None:
        from actingweb.callback_processor import CallbackProcessor
        from actingweb.interface.actor_interface import ActorInterface

        actor = create_core_actor(config, uuid_email())
        processor = CallbackProcessor(ActorInterface(actor))
        bucket = "_callback_state"
        pending_key = processor._get_pending_key("peer1", "sub1")
        state_key = processor._get_state_key("peer1", "sub1")
        db = get_attribute(config)
        db.set_attr(
            actor_id=aid(actor),
            bucket=bucket,
            name=pending_key,
            data={"callbacks": [{"sequence": 5}]},
        )
        db.set_attr(
            actor_id=aid(actor), bucket=bucket, name=state_key, data={"version": 3}
        )
        before = (
            _attr_row(config, aid(actor), bucket, pending_key),
            _attr_row(config, aid(actor), bucket, state_key),
        )

        with (
            seam_fault(config, "attribute", "Attribute", "get"),
            pytest.raises(DbError),
        ):
            processor.process_callback_sync(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=7,
                data={"x": 1},
                callback_type="diff",
            )

        after = (
            _attr_row(config, aid(actor), bucket, pending_key),
            _attr_row(config, aid(actor), bucket, state_key),
        )
        assert after == before


class TestB8ActorDelete:
    def test_trust_list_fault_deletes_nothing_and_writes_no_tombstone(
        self, config: Any
    ) -> None:
        from actingweb.deletion import DeletionStatus, get_deletion_status

        actor = create_core_actor(config, uuid_email())
        assert actor.property is not None
        actor.property["keep"] = "me"

        with seam_fault(config, "trust", "Trust", "query"), pytest.raises(DbError):
            actor.delete()

        assert Actor(actor_id=aid(actor), config=config).id == aid(actor)
        assert get_deletion_status(aid(actor), config) != DeletionStatus.DELETED
        kept = Actor(actor_id=aid(actor), config=config).property
        assert kept is not None and kept["keep"] == "me"


class TestB9DeleteSubscription:
    def test_listing_fault_deletes_neither_subscription_nor_peer_data(
        self, config: Any
    ) -> None:
        actor = create_core_actor(config, uuid_email())
        assert get_subscription(config).create(
            actor_id=aid(actor),
            peerid="peer1",
            subid="sub1",
            target="properties",
            callback=True,
        )
        bucket = "remote:peer1"
        get_attribute(config).set_attr(
            actor_id=aid(actor), bucket=bucket, name="x", data={"v": 1}
        )

        with (
            seam_fault(config, "subscription", "Subscription", "query"),
            pytest.raises(DbError),
        ):
            actor.delete_subscription(peerid="peer1", subid="sub1", callback=True)

        assert get_subscription(config).get(
            actor_id=aid(actor), peerid="peer1", subid="sub1"
        )
        assert get_attribute(config).get_bucket(actor_id=aid(actor), bucket=bucket)


class TestB10PermissionCallback:
    def test_permission_read_fault_runs_no_sync_and_stores_nothing(
        self, config: Any
    ) -> None:
        from actingweb.aw_web_request import AWWebObj
        from actingweb.handlers.callbacks import CallbacksHandler

        actor = create_core_actor(config, uuid_email())
        body = {"data": {"properties": {"allowed": ["notes/*"]}}}
        webobj = AWWebObj(url="https://test.example.com/x", body=json.dumps(body))
        handler = CallbacksHandler(webobj, config)
        check = mock.Mock()
        check.check_authorisation.return_value = True
        handler._authenticate_dual_context = mock.Mock(  # type: ignore[method-assign]
            return_value=mock.Mock(actor=actor, auth_obj=check)
        )

        with (
            backend_fault(
                config,
                "get_attr",
                lambda a, b, _n: b == PEER_PERMISSIONS_BUCKET,
                raise_db_error,
            ),
            mock.patch.object(
                CallbacksHandler, "_incremental_sync_granted_properties"
            ) as sync,
            pytest.raises(DbError),
        ):
            handler.post(aid(actor), "permissions/granting-peer")

        sync.assert_not_called()
        assert (
            _attr_row(
                config,
                aid(actor),
                PEER_PERMISSIONS_BUCKET,
                f"{aid(actor)}:granting-peer",
            )
            is None
        )


class TestB11CircuitBreaker:
    def test_unreadable_breaker_skips_delivery_and_keeps_stored_state(
        self, config: Any
    ) -> None:
        from actingweb.fanout import CircuitBreaker, FanOutManager
        from actingweb.interface.actor_interface import ActorInterface

        actor = create_core_actor(config, uuid_email())
        manager = FanOutManager(ActorInterface(actor))
        open_cb = CircuitBreaker(
            peer_id="peer1", failure_threshold=1, cooldown_seconds=600
        )
        open_cb.record_failure()
        bucket = FanOutManager._CB_STATE_BUCKET
        get_attribute(config).set_attr(
            actor_id=aid(actor), bucket=bucket, name="cb:peer1", data=open_cb.to_dict()
        )
        before = _attr_row(config, aid(actor), bucket, "cb:peer1")
        manager._circuit_breakers.clear()

        with (
            backend_fault(
                config, "get_attr", lambda a, b, _n: b == bucket, raise_db_error
            ),
            mock.patch.object(FanOutManager, "_deliver_single") as deliver,
        ):
            result = asyncio.run(
                manager.deliver_to_subscribers(
                    subscriptions=[
                        {
                            "peerid": "peer1",
                            "subid": "s1",
                            "callback_url": "https://p.test/cb",
                        }
                    ],
                    payload={"x": 1},
                    target="properties",
                    sequence=1,
                )
            )

        deliver.assert_not_called()
        assert result.results[0].error == "breaker_state_unreadable"
        assert _attr_row(config, aid(actor), bucket, "cb:peer1") == before
