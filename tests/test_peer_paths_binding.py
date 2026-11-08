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
from actingweb.handlers import subscription as subscription_handlers
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


@pytest.fixture(autouse=True)
def _fresh_refusal_log() -> Any:
    """The once-per-process WARNING keeps state; each test starts clean."""
    saved = set(subscription_handlers._GET_ROW_REFUSALS_LOGGED)
    subscription_handlers._GET_ROW_REFUSALS_LOGGED.clear()
    yield
    subscription_handlers._GET_ROW_REFUSALS_LOGGED.clear()
    subscription_handlers._GET_ROW_REFUSALS_LOGGED.update(saved)


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
    def test_a_get_only_row_refuses_put_and_delete(
        self, world: Publisher, method: str, params: dict[str, str] | None
    ) -> None:
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
        assert out.response.status_code == 403
        assert world.diffs("g") == [1]
        assert world.has_subscription("g")

    def test_the_refusal_is_logged_once_at_warning(
        self, world: Publisher, caplog: pytest.LogCaptureFixture
    ) -> None:
        g = world.peers["g"]
        with caplog.at_level(logging.WARNING, logger="actingweb.handlers.subscription"):
            for _ in range(3):
                world.call(
                    SubscriptionHandler,
                    "PUT",
                    g,
                    "sub-g",
                    as_peer="g",
                    body={"sequence": 1},
                )
            world.call(SubscriptionHandler, "DELETE", g, "sub-g", as_peer="g")
        warnings = [r.getMessage() for r in caplog.records]
        assert len(warnings) == 1
        assert GET_ONLY_TYPE in warnings[0]
        assert '("subscriptions/<id>/<subid>", "PUT", "a")' in warnings[0]
        assert '("subscriptions/<id>/<subid>", "DELETE", "a")' in warnings[0]

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
        # As before: no built-in row admits a friend on its trust's
        # permissions (the handler passes no peer id, so ``owner`` never
        # binds); an application row does, for its own row only.
        out = world.call(TrustPermissionHandler, "GET", "friend", b, as_peer="b")
        assert out.response.status_code == 403
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
