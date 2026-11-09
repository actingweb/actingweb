"""Peer paths bound to their peer, and the method rule (Phase 2).

``thoughts/plans/2026-11-06-peer-authorisation-fixes.md``, Phase 2:
``/subscriptions``, ``/permissions`` and ``/trust/<type>/<id>`` admit a peer
only on its own path, a PUT or DELETE on a subscription is authorised as
itself (a GET-only row refuses it, logged once at WARNING), the subscription
root's ``?peerid=`` lists a peer's own rows, and a peer or client view lists
only its own trust's subscriptions. Real storage; both backends through
``DATABASE_BACKEND``.
"""

from __future__ import annotations

import base64
import json
import logging
import uuid
from typing import Any
from unittest import mock

import pytest

from actingweb.aw_web_request import AWWebObj
from actingweb.handlers.permissions import PermissionsHandler
from actingweb.handlers.subscription import (
    SubscriptionDiffHandler,
    SubscriptionHandler,
    SubscriptionRelationshipHandler,
    SubscriptionRootHandler,
)
from actingweb.handlers.trust import TrustPeerHandler, TrustPermissionHandler
from actingweb.interface.actor_interface import ActorInterface
from actingweb.interface.authenticated_views import AuthContext
from actingweb.subscription import Subscription
from actingweb.trust import Trust
from actingweb.trust_permissions import initialize_trust_permission_store
from tests._adoption_helpers import aid, create_core_actor, make_config, uuid_email

PASSPHRASE = "peer-paths-test-passphrase"
GET_ONLY_TYPE = "getonly"


class Publisher:
    """A with trusts to B and C (friend), D (admin), E (pending) and G (an
    application type whose rows grant only GET on its subscription); B and
    G each hold a subscription at A with one queued diff."""

    def __init__(self) -> None:
        self.config = make_config()
        # The application type's rows, as a consumer adds them.
        self.config.access.insert(
            0, (GET_ONLY_TYPE, "subscriptions/<id>/<subid>", "GET", "a")
        )
        self.config.access.insert(1, (GET_ONLY_TYPE, "trust/<type>/<id>", "GET", "a"))
        initialize_trust_permission_store(self.config)
        self.a = create_core_actor(self.config, uuid_email(), passphrase=PASSPHRASE)
        tag = uuid.uuid4().hex[:8]
        self.peers: dict[str, str] = {}
        self.secrets: dict[str, str] = {}
        for name, relationship, approved in (
            ("b", "friend", True),
            ("c", "friend", True),
            ("d", "admin", True),
            ("e", "friend", False),
            ("g", GET_ONLY_TYPE, True),
        ):
            peer = f"peer-{name}-{tag}"
            self.peers[name] = peer
            secret = uuid.uuid4().hex
            self.secrets[name] = secret
            assert Trust(actor_id=aid(self.a), peerid=peer, config=self.config).create(
                baseuri=f"https://{peer}.example.test/{peer}",
                peer_type="urn:test",
                relationship=relationship,
                secret=secret,
                approved=approved,
                verified=True,
                peer_approved=True,
            )
        for name in ("b", "g"):
            sub = Subscription(
                actor_id=aid(self.a),
                peerid=self.peers[name],
                subid=f"sub-{name}",
                callback=False,
                config=self.config,
            )
            assert sub.create(target="properties", granularity="high")
            assert sub.add_diff(blob=json.dumps({"x": {"v": 1}}))

    def call(
        self,
        handler_class: Any,
        method: str,
        *args: str,
        as_peer: str | None = None,
        creator: bool = False,
        body: Any = None,
        params: dict[str, str] | None = None,
    ) -> AWWebObj:
        headers: dict[str, str] = {}
        if as_peer:
            headers["Authorization"] = f"Bearer {self.secrets[as_peer]}"
        if creator:
            token = base64.b64encode(f"{self.a.creator}:{PASSPHRASE}".encode()).decode()
            headers["Authorization"] = f"Basic {token}"
        webobj = AWWebObj(
            url=f"https://test.example.com/{aid(self.a)}/x",
            params=params or {},
            body=json.dumps(body) if body is not None else None,
            headers=headers,
        )
        handler = handler_class(webobj, self.config)
        getattr(handler, method.lower())(aid(self.a), *args)
        return webobj

    def diffs(self, name: str) -> list[int]:
        sub = Subscription(
            actor_id=aid(self.a),
            peerid=self.peers[name],
            subid=f"sub-{name}",
            callback=False,
            config=self.config,
        )
        return [d["sequence"] for d in sub.get_diffs() or []]

    def has_subscription(self, name: str) -> bool:
        return bool(
            Subscription(
                actor_id=aid(self.a),
                peerid=self.peers[name],
                subid=f"sub-{name}",
                callback=False,
                config=self.config,
            ).get()
        )


@pytest.fixture
def world() -> Publisher:
    return Publisher()


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------


class TestAnotherPeersSubscription:
    def test_every_handler_refuses_and_changes_nothing(self, world: Publisher) -> None:
        b = world.peers["b"]
        for handler, method, args, body in (
            (SubscriptionRelationshipHandler, "GET", (b,), None),
            (SubscriptionRelationshipHandler, "POST", (b,), {"target": "properties"}),
            (SubscriptionHandler, "GET", (b, "sub-b"), None),
            (SubscriptionHandler, "PUT", (b, "sub-b"), {"sequence": 1}),
            (SubscriptionHandler, "DELETE", (b, "sub-b"), None),
            (SubscriptionDiffHandler, "GET", (b, "sub-b", "1"), None),
        ):
            out = world.call(handler, method, *args, as_peer="c", body=body)
            assert out.response.status_code == 403, (handler.__name__, method)
        assert world.diffs("b") == [1]
        assert world.has_subscription("b")

    def test_its_own_path_works_as_before(self, world: Publisher) -> None:
        b = world.peers["b"]
        out = world.call(SubscriptionHandler, "GET", b, "sub-b", as_peer="b")
        assert out.response.status_code == 200
        out = world.call(
            SubscriptionHandler, "PUT", b, "sub-b", as_peer="b", body={"sequence": 1}
        )
        assert out.response.status_code == 204
        assert world.diffs("b") == []
        out = world.call(SubscriptionHandler, "DELETE", b, "sub-b", as_peer="b")
        assert out.response.status_code == 204
        assert not world.has_subscription("b")

    def test_an_admin_peer_is_exempt_where_a_row_admits_it(
        self, world: Publisher
    ) -> None:
        """No built-in row admits ``admin`` on subscriptions (the exemption
        applies only after a row admits); its trust row does."""
        b = world.peers["b"]
        out = world.call(SubscriptionHandler, "GET", b, "sub-b", as_peer="d")
        assert out.response.status_code == 403
        out = world.call(TrustPeerHandler, "GET", "friend", b, as_peer="d")
        assert out.response.status_code == 200

    def test_the_creator_as_before(self, world: Publisher) -> None:
        b = world.peers["b"]
        out = world.call(SubscriptionHandler, "GET", b, "sub-b", creator=True)
        assert out.response.status_code == 200
        out = world.call(
            SubscriptionHandler, "PUT", b, "sub-b", creator=True, body={"sequence": 1}
        )
        assert out.response.status_code == 204


class TestTheMethodRule:
    def test_a_get_only_row_admits_get_and_the_diff_get(self, world: Publisher) -> None:
        g = world.peers["g"]
        out = world.call(SubscriptionHandler, "GET", g, "sub-g", as_peer="g")
        assert out.response.status_code == 200
        out = world.call(SubscriptionDiffHandler, "GET", g, "sub-g", "1", as_peer="g")
        assert out.response.status_code == 200

    @pytest.mark.parametrize(
        ("method", "params"),
        [
            ("PUT", None),
            ("DELETE", None),
            ("GET", {"_method": "PUT", "sequence": "1"}),
            ("GET", {"_method": "DELETE"}),
        ],
    )
    def test_the_owner_row_admits_a_peers_own_put_and_delete(
        self, world: Publisher, method: str, params: dict[str, str] | None
    ) -> None:
        """Reverify-4, Issue 2 (owner): a subscriber type with only a GET row
        clears and ends its own subscription through the ``owner`` row; no
        adoption rows are needed."""
        g = world.peers["g"]
        out = world.call(
            SubscriptionHandler,
            method,
            g,
            "sub-g",
            as_peer="g",
            body={"sequence": 1} if method == "PUT" else None,
            params=params,
        )
        # Admitted (a method override without a body answers 400, not 403).
        assert out.response.status_code != 403
        if params is None:
            assert out.response.status_code in (200, 204)

    def test_the_owner_row_admits_no_other_peers_subscription(
        self, world: Publisher
    ) -> None:
        g = world.peers["g"]
        for method in ("PUT", "DELETE"):
            out = world.call(
                SubscriptionHandler,
                method,
                g,
                "sub-g",
                as_peer="b",
                body={"sequence": 1} if method == "PUT" else None,
            )
            assert out.response.status_code == 403
        assert world.diffs("g") == [1]
        assert world.has_subscription("g")

    def test_a_plain_refusal_is_not_logged(
        self, world: Publisher, caplog: pytest.LogCaptureFixture
    ) -> None:
        b = world.peers["b"]
        with caplog.at_level(logging.WARNING, logger="actingweb.handlers.subscription"):
            out = world.call(
                SubscriptionHandler,
                "PUT",
                b,
                "sub-b",
                as_peer="c",
                body={"sequence": 1},
            )
        assert out.response.status_code == 403
        assert not caplog.records


class TestTheSubscriptionRoot:
    def test_a_peer_lists_only_its_own_whatever_the_query(
        self, world: Publisher
    ) -> None:
        # An application row admitting peers on the root listing.
        world.config.access.insert(0, ("friend", "subscriptions", "GET", "a"))
        out = world.call(
            SubscriptionRootHandler,
            "GET",
            as_peer="c",
            params={"peerid": world.peers["b"]},
        )
        assert out.response.status_code == 200
        assert json.loads(out.response.body)["data"] == []
        out = world.call(SubscriptionRootHandler, "GET", as_peer="b")
        rows = json.loads(out.response.body)["data"]
        assert {r["peerid"] for r in rows} == {world.peers["b"]}

    def test_the_creator_keeps_the_query(self, world: Publisher) -> None:
        out = world.call(
            SubscriptionRootHandler,
            "GET",
            creator=True,
            params={"peerid": world.peers["b"]},
        )
        rows = json.loads(out.response.body)["data"]
        assert {r["peerid"] for r in rows} == {world.peers["b"]}


# ---------------------------------------------------------------------------
# The permission query
# ---------------------------------------------------------------------------


class TestThePermissionQuery:
    @pytest.mark.parametrize("name", ["b", "c", "d", "g"])
    def test_a_peer_reads_its_own_for_every_type(
        self, world: Publisher, name: str
    ) -> None:
        if name == "g":
            world.config.access.insert(
                0, (GET_ONLY_TYPE, "permissions/<id>", "GET", "a")
            )
        with mock.patch("actingweb.handlers.permissions.get_registry") as registry:
            registry.return_value.get_type.return_value = mock.Mock(
                base_permissions={"properties": {"patterns": ["*"]}}
            )
            out = world.call(PermissionsHandler, "GET", world.peers[name], as_peer=name)
        assert out.response.status_code == 200

    def test_another_peers_and_an_unknown_id_answer_the_same_403(
        self, world: Publisher
    ) -> None:
        out = world.call(PermissionsHandler, "GET", world.peers["b"], as_peer="c")
        assert out.response.status_code == 403
        out = world.call(PermissionsHandler, "GET", "peer-unknown", as_peer="c")
        assert out.response.status_code == 403

    @pytest.mark.parametrize("who", ["creator", "d"])
    def test_the_creator_and_an_admin_read_any(
        self, world: Publisher, who: str
    ) -> None:
        kwargs: dict[str, Any] = (
            {"creator": True} if who == "creator" else {"as_peer": "d"}
        )
        with mock.patch("actingweb.handlers.permissions.get_registry") as registry:
            registry.return_value.get_type.return_value = mock.Mock(base_permissions={})
            out = world.call(PermissionsHandler, "GET", world.peers["b"], **kwargs)
        assert out.response.status_code == 200

    def test_a_pending_peer_is_refused(self, world: Publisher) -> None:
        out = world.call(PermissionsHandler, "GET", world.peers["e"], as_peer="e")
        assert out.response.status_code == 403


# ---------------------------------------------------------------------------
# /trust/<type>/<id>, one test per site
# ---------------------------------------------------------------------------


class TestTrustSites:
    @pytest.mark.parametrize(
        ("handler", "method", "body"),
        [
            (TrustPeerHandler, "GET", None),
            (TrustPeerHandler, "POST", {"approved": True}),
            (TrustPeerHandler, "POST", {"desc": "x"}),
            (TrustPeerHandler, "PUT", {"desc": "x"}),
            (TrustPeerHandler, "DELETE", None),
            (TrustPermissionHandler, "GET", None),
            (TrustPermissionHandler, "PUT", {"properties": {"patterns": ["x"]}}),
            (TrustPermissionHandler, "DELETE", None),
        ],
    )
    def test_another_peer_is_refused(
        self, world: Publisher, handler: Any, method: str, body: Any
    ) -> None:
        # A row that admits friends on any trust row, every method, ahead of
        # the defaults: only the binding refuses C on B's row.
        world.config.access.insert(0, ("friend", "trust/<type>/<id>", "", "a"))
        b = world.peers["b"]
        out = world.call(handler, method, "friend", b, as_peer="c", body=body)
        assert out.response.status_code == 403
        assert Trust(actor_id=aid(world.a), peerid=b, config=world.config).get()

    def test_the_peer_reads_its_own(self, world: Publisher) -> None:
        b = world.peers["b"]
        out = world.call(TrustPeerHandler, "GET", "friend", b, as_peer="b")
        assert out.response.status_code == 200
        # The ``owner`` row admits a peer to its own trust's permissions
        # (reverify-4, Issue 2: the handler passes the path's peer); reading
        # them only, writing stays the owner's (TrustPermissionHandler).
        out = world.call(TrustPermissionHandler, "GET", "friend", b, as_peer="b")
        assert out.response.status_code != 403
        g = world.peers["g"]
        out = world.call(TrustPermissionHandler, "GET", GET_ONLY_TYPE, g, as_peer="g")
        # Admitted (the test type is not registered, so no defaults: 404).
        assert out.response.status_code != 403
        out = world.call(TrustPermissionHandler, "GET", "friend", b, as_peer="g")
        assert out.response.status_code == 403

    def test_an_application_get_row_admits_its_own_row_only(
        self, world: Publisher
    ) -> None:
        g = world.peers["g"]
        out = world.call(TrustPeerHandler, "GET", GET_ONLY_TYPE, g, as_peer="g")
        assert out.response.status_code == 200
        out = world.call(
            TrustPeerHandler, "GET", "friend", world.peers["b"], as_peer="g"
        )
        assert out.response.status_code == 403


# ---------------------------------------------------------------------------
# The authenticated view
# ---------------------------------------------------------------------------


class TestTheViewFilter:
    def _views(self, world: Publisher) -> ActorInterface:
        return ActorInterface(world.a)

    def test_a_peer_view_sees_its_own(self, world: Publisher) -> None:
        actor = self._views(world)
        b = world.peers["b"]
        view = actor.as_peer(b, {"peerid": b, "relationship": "friend"})
        assert {s.peer_id for s in view.subscriptions.all_subscriptions} == {b}
        assert {s.peer_id for s in view.subscriptions.inbound_subscriptions} == {b}
        assert view.subscriptions.outbound_subscriptions == []

    def test_a_client_view_sees_its_trusts_own(self, world: Publisher) -> None:
        actor = self._views(world)
        g = world.peers["g"]
        view = actor.as_client("client-1", {"peerid": g})
        assert {s.peer_id for s in view.subscriptions.all_subscriptions} == {g}

    def test_a_client_view_with_no_trust_sees_nothing(self, world: Publisher) -> None:
        actor = self._views(world)
        view = actor.as_client("client-2", None)
        assert view.subscriptions.all_subscriptions == []

    def test_owner_mode_sees_every_row(self, world: Publisher) -> None:
        from actingweb.interface.authenticated_views import (
            AuthenticatedSubscriptionManager,
        )

        actor = self._views(world)
        manager = AuthenticatedSubscriptionManager(
            actor.subscriptions, AuthContext(), aid(world.a), world.config
        )
        peers = {s.peer_id for s in manager.all_subscriptions}
        assert peers == {world.peers["b"], world.peers["g"]}


# ---------------------------------------------------------------------------
# A refusal is seen as one
# ---------------------------------------------------------------------------


class TestARefusalIsSeen:
    def _proxy(self) -> Any:
        from actingweb.aw_proxy import AwProxy

        proxy = AwProxy(config=make_config())
        proxy.trust = {
            "baseuri": "https://a.example.test/a",
            "secret": "s",
            "peerid": "a",
        }
        proxy._maybe_retry_with_basic = mock.Mock(return_value=None)  # type: ignore[method-assign]
        return proxy

    def test_a_403_with_no_body_is_an_error(self) -> None:
        refused = mock.Mock(status_code=403, content=b"")
        refused.json.side_effect = ValueError("no body")
        proxy = self._proxy()
        with mock.patch("actingweb.aw_proxy.requests.put", return_value=refused):
            result = proxy.change_resource(
                path="subscriptions/b/s", params={"sequence": 1}
            )
        assert result["error"]["code"] == 403
        assert proxy.last_response_code == 403

    def test_a_204_is_not(self) -> None:
        done = mock.Mock(status_code=204, content=b"")
        done.json.side_effect = ValueError("no body")
        proxy = self._proxy()
        with mock.patch("actingweb.aw_proxy.requests.put", return_value=done):
            result = proxy.change_resource(
                path="subscriptions/b/s", params={"sequence": 1}
            )
        assert "error" not in result

    def test_a_refused_remote_unsubscribe_is_logged_with_its_status(
        self, world: Publisher, caplog: pytest.LogCaptureFixture
    ) -> None:
        refused = mock.Mock(status_code=403, content=b"")
        with (
            mock.patch("actingweb.actor.requests.delete", return_value=refused),
            caplog.at_level(logging.WARNING, logger="actingweb.actor"),
        ):
            assert not world.a.delete_remote_subscription(
                peerid=world.peers["b"], subid="sub-b"
            )
        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert errors and "403" in errors[0].getMessage()


class TestTheOwnersPartOfATrustRow:
    """The Phase 2 review: a peer bound to its own row still never approves
    it or writes its own permissions."""

    @pytest.fixture
    def admitted(self, world: Publisher) -> Publisher:
        world.config.access.insert(0, ("friend", "trust/<type>/<id>", "", "a"))
        return world

    def test_a_peer_cannot_approve_its_own_row(self, admitted: Publisher) -> None:
        c = admitted.peers["c"]
        out = admitted.call(
            TrustPeerHandler, "PUT", "friend", c, as_peer="c", body={"approved": True}
        )
        assert out.response.status_code == 403

    def test_a_peer_cannot_write_its_own_permissions(self, admitted: Publisher) -> None:
        c = admitted.peers["c"]
        for method, body in (
            ("PUT", {"properties": {"patterns": ["*"]}}),
            ("DELETE", None),
        ):
            out = admitted.call(
                TrustPermissionHandler, method, "friend", c, as_peer="c", body=body
            )
            assert out.response.status_code == 403, method

    def test_a_peer_may_still_describe_its_own_row(self, admitted: Publisher) -> None:
        c = admitted.peers["c"]
        out = admitted.call(
            TrustPeerHandler, "PUT", "friend", c, as_peer="c", body={"desc": "mine"}
        )
        assert out.response.status_code != 403

    def test_an_admin_peer_may_write_anothers_permissions(
        self, world: Publisher
    ) -> None:
        b = world.peers["b"]
        out = world.call(
            TrustPermissionHandler,
            "PUT",
            "friend",
            b,
            as_peer="d",
            body={"properties": {"patterns": ["x"], "operations": ["read"]}},
        )
        assert out.response.status_code != 403


class TestTheSubscriptionRootPost:
    def test_a_peer_cannot_subscribe_the_actor_to_another_peer(
        self, world: Publisher
    ) -> None:
        world.config.access.insert(0, ("friend", "subscriptions", "POST", "a"))
        with mock.patch(
            "actingweb.interface.subscription_manager.SubscriptionManager.subscribe_to_peer"
        ) as subscribe:
            out = world.call(
                SubscriptionRootHandler,
                "POST",
                as_peer="c",
                body={"peerid": world.peers["b"], "target": "properties"},
            )
        assert out.response.status_code == 403
        subscribe.assert_not_called()


class TestAClientViewListsWhatItCreates:
    def test_rows_it_creates_are_listed(self, world: Publisher) -> None:
        actor = ActorInterface(world.a)
        view = actor.as_client("client-new", {"peer_id": "unused"})
        with mock.patch(
            "actingweb.interface.authenticated_views.AuthenticatedSubscriptionManager._check_subscription_permission"
        ):
            assert view.subscriptions.create_local_subscription("properties")
        assert {s.peer_id for s in view.subscriptions.all_subscriptions} == {
            "client-new"
        }


class TestTheProxyOnOddBodies:
    def test_a_403_with_a_null_body_is_an_error(self) -> None:
        from actingweb.aw_proxy import AwProxy

        refused = mock.Mock(status_code=403, content=b"null")
        refused.json.return_value = None
        proxy = AwProxy(config=make_config())
        proxy.trust = {"baseuri": "https://a.example.test/a", "secret": "s"}
        proxy._maybe_retry_with_basic = mock.Mock(return_value=None)  # type: ignore[method-assign]
        with mock.patch("actingweb.aw_proxy.requests.put", return_value=refused):
            result = proxy.change_resource(path="x", params={"a": 1})
        assert result is not None and result["error"]["code"] == 403

    def test_the_async_twin_sees_a_403_with_no_body(self) -> None:
        import asyncio

        from actingweb.aw_proxy import AwProxy

        refused = mock.Mock(status_code=403, content=b"")
        refused.json.side_effect = ValueError("no body")
        client = mock.MagicMock()
        client.__aenter__.return_value.put = mock.AsyncMock(return_value=refused)
        proxy = AwProxy(config=make_config())
        proxy.trust = {"baseuri": "https://a.example.test/a", "secret": "s"}
        with mock.patch("actingweb.aw_proxy.httpx.AsyncClient", return_value=client):
            result = asyncio.run(proxy.change_resource_async(path="x", params={"a": 1}))
        assert result is not None and result["error"]["code"] == 403


class TestNoPeerReadsAnothersSecret:
    """Verification of 2026-11-08, Issue 1: an ``admin`` peer reads another
    peer's trust row without its secret, and cannot move its base URI."""

    def test_an_admin_peer_gets_no_secret(self, world: Publisher) -> None:
        b = world.peers["b"]
        out = world.call(TrustPeerHandler, "GET", "friend", b, as_peer="d")
        assert out.response.status_code == 200
        row = json.loads(out.response.body)
        assert row["peerid"] == b
        assert "secret" not in row and "verification_token" not in row

    @pytest.mark.parametrize("who", ["b", "creator"])
    def test_the_peer_itself_and_the_creator_do(
        self, world: Publisher, who: str
    ) -> None:
        b = world.peers["b"]
        kwargs: dict[str, Any] = (
            {"creator": True} if who == "creator" else {"as_peer": "b"}
        )
        out = world.call(TrustPeerHandler, "GET", "friend", b, **kwargs)
        row = json.loads(out.response.body)
        assert row["secret"] == world.secrets["b"]
        assert row.get("verification_token")

    def test_an_admin_peer_cannot_move_anothers_base_uri(
        self, world: Publisher
    ) -> None:
        b = world.peers["b"]
        out = world.call(
            TrustPeerHandler,
            "PUT",
            "friend",
            b,
            as_peer="d",
            body={"baseuri": "https://evil.example.test/x"},
        )
        assert out.response.status_code == 403
        row = Trust(actor_id=aid(world.a), peerid=b, config=world.config).get()
        assert row and row["baseuri"] == f"https://{b}.example.test/{b}"


class TestAPeersOwnSubscriptionAfterReverify5:
    """reverify-5 Issue 2: the ``owner`` row admits a peer to its own
    subscription (read, clear, end), never to creating one; and what a peer
    pulls of a ``properties`` subscription is filtered by its permissions,
    as a pushed callback is."""

    def test_the_owner_row_admits_no_subscription_creation(
        self, world: Publisher
    ) -> None:
        g = world.peers["g"]
        out = world.call(
            SubscriptionRelationshipHandler,
            "POST",
            g,
            as_peer="g",
            body={"target": "properties", "granularity": "high"},
        )
        assert out.response.status_code == 403

    def test_a_relationship_row_still_admits_creation(self, world: Publisher) -> None:
        b = world.peers["b"]
        out = world.call(
            SubscriptionRelationshipHandler,
            "POST",
            b,
            as_peer="b",
            body={"target": "properties", "granularity": "high"},
        )
        assert out.response.status_code == 201

    @staticmethod
    def _narrow(world: Publisher, name: str) -> None:
        from actingweb.trust_permissions import (
            create_permission_override,
            get_trust_permission_store,
        )

        assert get_trust_permission_store(world.config).store_permissions(
            create_permission_override(
                actor_id=aid(world.a),
                peer_id=world.peers[name],
                trust_type="friend",
                permission_updates={
                    # Overrides add to the type's grant: an exclusion
                    # narrows it.
                    "properties": {"excluded_patterns": ["x", "x/*"]}
                },
            )
        )

    def test_a_pulled_diff_carries_only_what_the_peer_may_read(
        self, world: Publisher
    ) -> None:
        b = world.peers["b"]
        self._narrow(world, "b")
        out = world.call(SubscriptionHandler, "GET", b, "sub-b", as_peer="b")
        assert out.response.status_code == 200
        pairs = json.loads(out.response.body)["data"]
        assert [p["sequence"] for p in pairs] == [1]
        assert pairs[0]["data"] == {}
        out = world.call(SubscriptionDiffHandler, "GET", b, "sub-b", "1", as_peer="b")
        assert out.response.status_code == 200
        assert json.loads(out.response.body)["data"] == {}

    @pytest.mark.parametrize("narrowed", [False, True])
    def test_a_subtargets_value_is_pulled_only_when_readable(
        self, world: Publisher, narrowed: bool
    ) -> None:
        """A subtarget subscription's diff is the property's value itself."""
        b = world.peers["b"]
        sub = Subscription(
            actor_id=aid(world.a),
            peerid=b,
            subid="sub-bx",
            callback=False,
            config=world.config,
        )
        assert sub.create(target="properties", subtarget="x", granularity="high")
        assert sub.add_diff(blob="change2")
        if narrowed:
            self._narrow(world, "b")
        out = world.call(SubscriptionHandler, "GET", b, "sub-bx", as_peer="b")
        assert out.response.status_code == 200
        data = json.loads(out.response.body)["data"][0]["data"]
        assert data == ({} if narrowed else "change2")

    def test_a_permitted_diff_is_pulled_whole(self, world: Publisher) -> None:
        b = world.peers["b"]
        out = world.call(SubscriptionHandler, "GET", b, "sub-b", as_peer="b")
        assert json.loads(out.response.body)["data"][0]["data"] == {"x": {"v": 1}}


class TestAPeersOwnTrustRowAfterReverify5:
    """reverify-5 Issues 3, 7 and 13: the built-in ``owner`` row alone (no
    application row) admits a peer to its own trust row; a base URI it moves
    to must name it on ``/meta``, as a creation's must."""

    @staticmethod
    def _meta(peer_id: str) -> Any:
        # The /meta check reads through the bounded verification GET (3.16).
        return mock.patch(
            "actingweb.actor._bounded_get_json",
            return_value=(200, {"id": peer_id}),
        )

    def test_a_move_to_a_base_uri_that_names_another_id_is_refused(
        self, world: Publisher
    ) -> None:
        c = world.peers["c"]
        before = Trust(actor_id=aid(world.a), peerid=c, config=world.config).get()
        with self._meta("someone-else"):
            out = world.call(
                TrustPeerHandler,
                "PUT",
                "friend",
                c,
                as_peer="c",
                body={"baseuri": "http://169.254.169.254/latest"},
            )
        assert out.response.status_code == 400
        after = Trust(actor_id=aid(world.a), peerid=c, config=world.config).get()
        assert (after or {}).get("baseuri") == (before or {}).get("baseuri")

    def test_a_move_to_a_base_uri_that_names_the_peer_is_stored(
        self, world: Publisher
    ) -> None:
        c = world.peers["c"]
        moved = f"https://moved.example.test/{c}"
        with self._meta(c):
            out = world.call(
                TrustPeerHandler,
                "PUT",
                "friend",
                c,
                as_peer="c",
                body={"baseuri": moved},
            )
        assert out.response.status_code == 204
        row = Trust(actor_id=aid(world.a), peerid=c, config=world.config).get()
        assert (row or {}).get("baseuri") == moved

    def test_the_owner_row_admits_a_description(self, world: Publisher) -> None:
        c = world.peers["c"]
        out = world.call(
            TrustPeerHandler, "PUT", "friend", c, as_peer="c", body={"desc": "mine"}
        )
        assert out.response.status_code == 204

    def test_the_owner_row_admits_no_approval(self, world: Publisher) -> None:
        c = world.peers["c"]
        out = world.call(
            TrustPeerHandler, "PUT", "friend", c, as_peer="c", body={"approved": True}
        )
        assert out.response.status_code == 403

    def test_a_json_false_approval_is_not_a_500(self, world: Publisher) -> None:
        c = world.peers["c"]
        out = world.call(
            TrustPeerHandler, "PUT", "friend", c, as_peer="c", body={"approved": False}
        )
        assert out.response.status_code != 500


class TestAnUnapprovedRowGetsNothingAfterTheAudit:
    """Audit A1: anyone can file a trust request with a relationship of its
    choice and its secret then authenticates; the permission evaluator
    granted such a row its type's permissions. Only an approved row is
    granted anything."""

    @staticmethod
    def _unapproved(world: Publisher, name: str, relationship: str) -> None:
        peer = f"peer-{name}-{uuid.uuid4().hex[:8]}"
        world.peers[name] = peer
        world.secrets[name] = uuid.uuid4().hex
        assert Trust(actor_id=aid(world.a), peerid=peer, config=world.config).create(
            baseuri=f"https://{peer}.example.test/{peer}",
            peer_type="urn:test",
            relationship=relationship,
            secret=world.secrets[name],
            approved=False,
            verified=False,
        )

    @pytest.mark.parametrize("relationship", ["friend", "admin"])
    def test_properties_methods_and_actions_refuse_it(
        self, world: Publisher, relationship: str
    ) -> None:
        from actingweb.handlers.actions import ActionsHandler
        from actingweb.handlers.methods import MethodsHandler
        from actingweb.handlers.properties import PropertiesHandler

        store = world.a.property
        assert store is not None
        store.note = "private to approved peers"
        self._unapproved(world, "s", relationship)
        for handler, method, args, body in (
            (PropertiesHandler, "GET", ("",), None),
            (PropertiesHandler, "GET", ("note",), None),
            (PropertiesHandler, "PUT", ("note",), "overwritten"),
            (PropertiesHandler, "DELETE", ("",), None),
            (MethodsHandler, "POST", ("anything",), {"x": 1}),
            (ActionsHandler, "POST", ("anything",), {"x": 1}),
        ):
            out = world.call(handler, method, *args, as_peer="s", body=body)
            assert out.response.status_code in (401, 403), (handler.__name__, method)
        assert store.note == "private to approved peers"

    def test_an_approved_peer_still_reads(self, world: Publisher) -> None:
        from actingweb.handlers.properties import PropertiesHandler

        store = world.a.property
        assert store is not None
        store.note = "shared"
        out = world.call(PropertiesHandler, "GET", "note", as_peer="b")
        assert out.response.status_code == 200

    def test_the_evaluator_denies_every_kind(self, world: Publisher) -> None:
        from actingweb.permission_evaluator import (
            PermissionResult,
            PermissionType,
            get_permission_evaluator,
        )

        self._unapproved(world, "s", "admin")
        ev = get_permission_evaluator(world.config)
        a, s = aid(world.a), world.peers["s"]
        assert ev.evaluate_property_access(a, s, "note", "read") == (
            PermissionResult.DENIED
        )
        assert ev.evaluate_method_access(a, s, "m") == PermissionResult.DENIED
        assert ev.evaluate_action_access(a, s, "x") == PermissionResult.DENIED
        assert ev.evaluate_tool_access(a, s, "t") == PermissionResult.DENIED
        assert set(
            ev.evaluate_bulk_property_access(a, s, ["note", "x"], "read").values()
        ) == {PermissionResult.DENIED}
        assert ev.get_allowed_items(a, s, PermissionType.TOOLS) == []


class TestOneFilterForPushAndPull:
    """Reverify-6 Issues 4 to 6 and audit A4: the pushed callback and the
    pulled diffs pass one filter, which checks the path a direct read of the
    same property checks: the subtarget, and the resource under it."""

    @staticmethod
    def _sub(
        world: Publisher, name: str, subid: str, subtarget: str, resource: str = ""
    ) -> Subscription:
        sub = Subscription(
            actor_id=aid(world.a),
            peerid=world.peers[name],
            subid=subid,
            callback=False,
            config=world.config,
        )
        assert sub.create(
            target="properties",
            subtarget=subtarget,
            resource=resource,
            granularity="high",
        )
        return sub

    @staticmethod
    def _grant(world: Publisher, name: str, trust_type: str, rules: Any) -> None:
        from actingweb.trust_permissions import (
            create_permission_override,
            get_trust_permission_store,
        )

        assert get_trust_permission_store(world.config).store_permissions(
            create_permission_override(
                actor_id=aid(world.a),
                peer_id=world.peers[name],
                trust_type=trust_type,
                permission_updates={"properties": rules},
            )
        )

    def _pull(self, world: Publisher, name: str, subid: str) -> Any:
        out = world.call(
            SubscriptionHandler, "GET", world.peers[name], subid, as_peer=name
        )
        assert out.response.status_code == 200
        return json.loads(out.response.body)["data"][0]["data"]

    @pytest.mark.parametrize(
        ("resource", "readable"), [("private", False), ("open", True)]
    )
    def test_a_resource_is_checked_on_both_paths(
        self, world: Publisher, resource: str, readable: bool
    ) -> None:
        """Issue 4: a friend excluded from ``settings/private`` subscribes to
        ``settings`` with that resource."""
        self._grant(world, "b", "friend", {"excluded_patterns": ["settings/private"]})
        sub = self._sub(world, "b", f"sub-r-{resource}", "settings", resource)
        assert sub.add_diff(blob=json.dumps({"v": 1}))
        assert self._pull(world, "b", f"sub-r-{resource}") == (
            {"v": 1} if readable else {}
        )
        with mock.patch("actingweb.actor.requests.post") as post:
            post.return_value = mock.Mock(status_code=204)
            world.a.callback_subscription(
                peerid=world.peers["b"],
                sub_obj=sub,
                sub=sub.get(),
                diff={"sequence": 2, "timestamp": "2026-11-09T00:00:00Z"},
                blob=json.dumps({"v": 1}),
            )
        assert post.called is readable

    def test_an_object_value_under_a_subtarget_follows_the_property(
        self, world: Publisher
    ) -> None:
        """Issue 5: a grant of exactly ``settings`` reads the whole object,
        as ``GET /properties/settings`` does; checking ``settings/<key>``
        pulled ``{}``."""
        # The associate type grants public/*; this override adds exactly
        # "settings".
        peer = f"peer-s-{uuid.uuid4().hex[:8]}"
        world.peers["s"] = peer
        world.secrets["s"] = uuid.uuid4().hex
        assert Trust(actor_id=aid(world.a), peerid=peer, config=world.config).create(
            baseuri=f"https://{peer}.example.test/{peer}",
            peer_type="urn:test",
            relationship="associate",
            secret=world.secrets["s"],
            approved=True,
            verified=True,
            peer_approved=True,
        )
        self._grant(
            world, "s", "associate", {"patterns": ["settings"], "operations": ["read"]}
        )
        sub = self._sub(world, "s", "sub-s", "settings")
        assert sub.add_diff(blob=json.dumps({"a": 1}))
        assert self._pull(world, "s", "sub-s") == {"a": 1}

    def test_a_single_value_is_not_pushed_past_an_exclusion(
        self, world: Publisher
    ) -> None:
        """Audit A4: a subtarget's value that is not an object went out
        unfiltered on the push."""
        self._grant(world, "b", "friend", {"excluded_patterns": ["secret"]})
        sub = self._sub(world, "b", "sub-v", "secret")
        with mock.patch("actingweb.actor.requests.post") as post:
            world.a.callback_subscription(
                peerid=world.peers["b"],
                sub_obj=sub,
                sub=sub.get(),
                diff={"sequence": 1, "timestamp": "2026-11-09T00:00:00Z"},
                blob=json.dumps("the secret value"),
            )
        post.assert_not_called()

    def test_a_subtarget_subscription_gets_no_excluded_resource(
        self, world: Publisher
    ) -> None:
        """Reverify-7 Issue 2: a subscription to ``settings`` without a
        resource receives a write to ``settings/private`` as
        ``{"private": ...}``; checking ``settings`` alone sent it past the
        exclusion on both paths."""
        self._grant(world, "b", "friend", {"excluded_patterns": ["settings/private"]})
        sub = self._sub(world, "b", "sub-n", "settings")
        world.a.register_diffs(
            target="properties",
            subtarget="settings",
            resource="private",
            blob=json.dumps("hidden"),
        )
        assert self._pull(world, "b", "sub-n") == {}
        with mock.patch("actingweb.actor.requests.post") as post:
            post.return_value = mock.Mock(status_code=204)
            world.a.callback_subscription(
                peerid=world.peers["b"],
                sub_obj=sub,
                sub=sub.get(),
                diff={"sequence": 2, "timestamp": "2026-11-09T00:00:00Z"},
                blob=json.dumps({"private": "hidden", "open": 1}),
            )
        sent = post.call_args.kwargs["data"].decode()
        assert "hidden" not in sent and '"open"' in sent

    def test_an_excluded_list_under_a_subtarget_is_dropped(
        self, world: Publisher
    ) -> None:
        """Reverify-8 Issue 9 and reverify-9 Issue 7: a ``list:`` key is a
        list, a top-level property, checked by its bare name as the
        whole-target filter and the list store check it."""
        self._grant(world, "b", "friend", {"excluded_patterns": ["notes"]})
        sub = self._sub(world, "b", "sub-l", "settings")
        with mock.patch("actingweb.actor.requests.post") as post:
            post.return_value = mock.Mock(status_code=204)
            world.a.callback_subscription(
                peerid=world.peers["b"],
                sub_obj=sub,
                sub=sub.get(),
                diff={"sequence": 1, "timestamp": "2026-11-09T00:00:00Z"},
                blob=json.dumps({"list:notes": {"op": "append"}, "open": 1}),
            )
        sent = post.call_args.kwargs["data"].decode()
        assert "list:notes" not in sent and '"open"' in sent

    def test_a_refused_diff_is_logged(
        self, world: Publisher, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Reverify-9 Issue 6: the subtarget path logs a denial as
        ``evaluate_permission`` does."""
        self._grant(world, "b", "friend", {"excluded_patterns": ["secret"]})
        sub = self._sub(world, "b", "sub-d", "secret")
        with (
            caplog.at_level("WARNING", logger="actingweb.permission_evaluator"),
            mock.patch("actingweb.actor.requests.post") as post,
        ):
            world.a.callback_subscription(
                peerid=world.peers["b"],
                sub_obj=sub,
                sub=sub.get(),
                diff={"sequence": 1, "timestamp": "2026-11-09T00:00:00Z"},
                blob=json.dumps("the secret value"),
            )
        post.assert_not_called()
        assert any(
            "Permission denied" in r.getMessage() and "'secret'" in r.getMessage()
            for r in caplog.records
        )


class TestAPeerListsItsOwnSubscriptions:
    """Reverify-6 Issue 3: the ``owner`` row admits a peer's listing of its
    own subscriptions, as on ``master``; never another peer's, never a
    creation."""

    def test_a_peer_with_no_listing_row_lists_its_own(self, world: Publisher) -> None:
        g = world.peers["g"]
        out = world.call(SubscriptionRelationshipHandler, "GET", g, as_peer="g")
        assert out.response.status_code == 200

    def test_it_lists_no_other_peers(self, world: Publisher) -> None:
        b = world.peers["b"]
        out = world.call(SubscriptionRelationshipHandler, "GET", b, as_peer="g")
        assert out.response.status_code == 403

    def test_it_still_creates_none(self, world: Publisher) -> None:
        g = world.peers["g"]
        out = world.call(
            SubscriptionRelationshipHandler,
            "POST",
            g,
            as_peer="g",
            body={"target": "properties"},
        )
        assert out.response.status_code == 403
