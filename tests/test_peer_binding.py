"""The peer binding and the authenticated ``/callbacks`` branches.

``thoughts/plans/2026-11-06-peer-authorisation-fixes.md``, Phase 1: a peer
caller reaches only the peer its path names (``Auth.check_authorisation``'s
``path_peer`` and ``peer_caller_only``), every callback request is
authenticated, the two peer branches admit only the peer they name, the
low-granularity fetch goes to the stored base URI, only ``diff`` and
``resync`` are accepted, the library's own hook names are reserved on the
generic branch and a permission timestamp is clamped. Real storage; both
backends through ``DATABASE_BACKEND``.
"""

from __future__ import annotations

import base64
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from unittest import mock

import pytest

from actingweb.attribute import Attributes
from actingweb.auth import Auth
from actingweb.aw_web_request import AWWebObj
from actingweb.callback_processor import CallbackProcessor
from actingweb.config import Config
from actingweb.constants import PEER_PERMISSIONS_BUCKET
from actingweb.handlers.callbacks import (
    CallbacksHandler,
    is_reserved_callback_name,
    low_granularity_fetch_url,
)
from actingweb.interface.hooks import HookRegistry
from actingweb.remote_storage import RemotePeerStore
from actingweb.subscription import Subscription
from actingweb.subscription_config import SubscriptionProcessingConfig
from actingweb.trust import Trust
from tests._adoption_helpers import aid, create_core_actor, make_config, uuid_email

PASSPHRASE = "binding-test-passphrase"

# ---------------------------------------------------------------------------
# check_authorisation
# ---------------------------------------------------------------------------


def _auth(
    config: Config, relationship: str, peerid: str = "", approved: bool = True
) -> Auth:
    """An ``Auth`` already authenticated as ``relationship`` (no request)."""
    auth = Auth.__new__(Auth)
    auth.config = config
    auth.acl = {
        "authenticated": True,
        "authorised": False,
        "rights": "",
        "relationship": relationship,
        "peerid": peerid,
        "approved": approved,
    }
    return auth


class TestCheckAuthorisation:
    def test_a_peer_on_its_own_path_passes(self) -> None:
        auth = _auth(make_config(), "friend", "peer-a")
        assert auth.check_authorisation(
            "subscriptions", "<id>", "GET", path_peer="peer-a"
        )

    @pytest.mark.parametrize(
        ("path", "subpath", "method"),
        [
            ("subscriptions", "<id>", "GET"),  # a built-in row with <id>
            ("properties", "", "GET"),  # a row without <id>
            ("callbacks", "", "POST"),  # the any row
        ],
    )
    def test_a_peer_on_another_peers_path_fails_whatever_row_matched(
        self, path: str, subpath: str, method: str
    ) -> None:
        auth = _auth(make_config(), "friend", "peer-c")
        assert auth.check_authorisation(path, subpath, method)
        assert not auth.check_authorisation(path, subpath, method, path_peer="peer-a")

    def test_an_application_row_at_index_0_does_not_bypass_it(self) -> None:
        config = make_config()
        config.access.insert(0, ("subscriber", "subscriptions/<id>", "", "a"))
        auth = _auth(config, "subscriber", "peer-s")
        assert auth.check_authorisation("subscriptions", "<id>", "GET")
        assert not auth.check_authorisation(
            "subscriptions", "<id>", "GET", path_peer="peer-a"
        )

    @pytest.mark.parametrize("relationship", ["creator", "trustee"])
    def test_creator_and_trustee_are_not_peer_callers(self, relationship: str) -> None:
        auth = _auth(make_config(), relationship)
        assert auth.check_authorisation(
            "subscriptions", "<id>", "GET", path_peer="peer-a"
        )
        assert not auth.check_authorisation(
            "callbacks",
            "subscriptions",
            "POST",
            path_peer="peer-a",
            peer_caller_only=True,
        )

    def test_an_admin_peer_is_exempt_except_on_a_peer_only_path(self) -> None:
        auth = _auth(make_config(), "admin", "peer-d")
        assert auth.check_authorisation("trust", "<type>/<id>", "GET", path_peer="x")
        assert not auth.check_authorisation(
            "callbacks", "permissions", "POST", path_peer="x", peer_caller_only=True
        )
        assert auth.check_authorisation(
            "callbacks",
            "permissions",
            "POST",
            path_peer="peer-d",
            peer_caller_only=True,
        )

    def test_without_the_keywords_nothing_changes(self) -> None:
        auth = _auth(make_config(), "associate", "peer-c")
        assert auth.check_authorisation("properties", "", "GET")
        assert not auth.check_authorisation("properties", "", "PUT")
        assert _auth(make_config(), "friend", "peer-c").check_authorisation(
            "subscriptions", "<id>", "PUT", "x"
        )

    def test_a_refused_row_stays_refused(self) -> None:
        auth = _auth(make_config(), "associate", "peer-a")
        assert not auth.check_authorisation(
            "subscriptions", "<id>", "GET", path_peer="peer-a"
        )


# ---------------------------------------------------------------------------
# The callback handler, with real storage
# ---------------------------------------------------------------------------


class World:
    """B with an approved friend trust to A, C and D (admin), and an
    unapproved one to E; B's subscription at A (callback true) and A's at B
    (B as publisher, callback false)."""

    def __init__(self, *, granularity: str = "high", hooks: Any = None) -> None:
        self.hooks = hooks
        self.config = make_config()
        self.config._subscription_config = SubscriptionProcessingConfig(  # type: ignore[attr-defined]
            enabled=True, auto_sequence=True, auto_storage=True
        )
        self.b = create_core_actor(self.config, uuid_email(), passphrase=PASSPHRASE)
        self.secrets: dict[str, str] = {}
        tag = uuid.uuid4().hex[:8]
        self.a, self.c, self.d, self.e = (
            f"peer-a-{tag}",
            f"peer-c-{tag}",
            f"peer-d-{tag}",
            f"peer-e-{tag}",
        )
        for peer, relationship, approved in (
            (self.a, "friend", True),
            (self.c, "friend", True),
            (self.d, "admin", True),
            (self.e, "friend", False),
        ):
            secret = uuid.uuid4().hex
            self.secrets[peer] = secret
            assert Trust(actor_id=aid(self.b), peerid=peer, config=self.config).create(
                baseuri=f"https://{peer}.example.test/{peer}/",
                peer_type="urn:test",
                relationship=relationship,
                secret=secret,
                approved=approved,
                verified=True,
                peer_approved=True,
            )
        assert Subscription(
            actor_id=aid(self.b),
            peerid=self.a,
            subid="sub-in",
            callback=True,
            config=self.config,
        ).create(target="properties", granularity=granularity)
        assert Subscription(
            actor_id=aid(self.b),
            peerid=self.a,
            subid="sub-out",
            callback=False,
            config=self.config,
        ).create(target="properties", granularity="high")

    def request(
        self,
        method: str,
        name: str,
        body: Any = None,
        *,
        as_peer: str | None = None,
        creator: bool = False,
        cookies: dict[str, str] | None = None,
    ) -> AWWebObj:
        headers: dict[str, str] = {}
        if as_peer:
            headers["Authorization"] = f"Bearer {self.secrets[as_peer]}"
        if creator:
            token = base64.b64encode(f"{self.b.creator}:{PASSPHRASE}".encode()).decode()
            headers["Authorization"] = f"Basic {token}"
        webobj = AWWebObj(
            url=f"https://test.example.com/{aid(self.b)}/callbacks/{name}",
            body=json.dumps(body) if body is not None else None,
            headers=headers,
            cookies=cookies,
        )
        handler = CallbacksHandler(webobj, self.config, hooks=self.hooks)
        getattr(handler, method.lower())(aid(self.b), name)
        return webobj

    def diff(self, subid: str = "sub-in", **extra: Any) -> dict[str, Any]:
        return {
            "id": self.a,
            "subscriptionid": subid,
            "sequence": 1,
            "target": "properties",
            "granularity": "high",
            "data": {"planted": {"v": 1}},
            **extra,
        }

    def replica(self, peer: str) -> list[str]:
        from actingweb.interface.actor_interface import ActorInterface

        store = RemotePeerStore(ActorInterface(self.b), peer, validate_peer_id=False)
        return sorted(store.list_all_scalars())

    def stored_permissions(self, peer: str) -> dict[str, Any] | None:
        row = Attributes(
            actor_id=aid(self.b), bucket=PEER_PERMISSIONS_BUCKET, config=self.config
        ).get_attr(name=f"{aid(self.b)}:{peer}")
        if not row:
            return None
        data = row.get("data")
        return json.loads(data) if isinstance(data, str) else data

    def subscription_exists(self, subid: str, callback: bool) -> bool:
        return bool(
            Subscription(
                actor_id=aid(self.b),
                peerid=self.a,
                subid=subid,
                callback=callback,
                config=self.config,
            ).get()
        )


def _permission_body(timestamp: str | None = None, excluded: str = "x") -> Any:
    body: dict[str, Any] = {
        "type": "permission",
        "data": {
            "properties": {
                "patterns": ["*"],
                "operations": ["read"],
                "excluded_patterns": [excluded],
            }
        },
    }
    if timestamp is not None:
        body["timestamp"] = timestamp
    return body


class TestUnauthenticated:
    def test_subscription_callback_401_nothing_applied(self) -> None:
        w = World()
        out = w.request("POST", f"subscriptions/{w.a}/sub-in", w.diff())
        assert out.response.status_code == 401
        assert "WWW-Authenticate" in out.response.headers
        assert w.replica(w.a) == []

    def test_permission_callback_401_nothing_stored(self) -> None:
        w = World()
        unknown = f"peer-x-{uuid.uuid4().hex[:8]}"
        for peer in (w.a, unknown):
            out = w.request("POST", f"permissions/{peer}", _permission_body())
            assert out.response.status_code == 401
            assert w.stored_permissions(peer) is None

    def test_subscription_delete_401_subscription_kept(self) -> None:
        w = World()
        out = w.request("DELETE", f"subscriptions/{w.a}/sub-in")
        assert out.response.status_code == 401
        assert w.subscription_exists("sub-in", callback=True)

    @pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE"])
    def test_generic_401_and_no_hook(self, method: str) -> None:
        hooks = HookRegistry()
        called = mock.Mock(return_value={"ok": True})
        hooks.register_callback_hook("ping", called)
        w = World(hooks=hooks)
        out = w.request(method, "ping", {"x": 1})
        assert out.response.status_code == 401
        called.assert_not_called()

    def test_a_web_session_cookie_answers_401_not_a_redirect(self) -> None:
        w = World()
        w.config.www_auth = "oauth"
        out = w.request(
            "POST",
            f"subscriptions/{w.a}/sub-in",
            w.diff(),
            cookies={"oauth_token": "stale"},
        )
        assert out.response.status_code == 401
        assert w.replica(w.a) == []


class TestThePeerBranches:
    @pytest.mark.parametrize("who", ["c", "d", "creator"])
    def test_another_caller_is_refused_before_the_lookup(self, who: str) -> None:
        w = World()
        kwargs: dict[str, Any] = (
            {"creator": True} if who == "creator" else {"as_peer": getattr(w, who)}
        )
        for subid in ("sub-in", "no-such-subscription"):
            out = w.request(
                "POST", f"subscriptions/{w.a}/{subid}", w.diff(subid), **kwargs
            )
            assert out.response.status_code == 403
        out = w.request("POST", f"permissions/{w.a}", _permission_body(), **kwargs)
        assert out.response.status_code == 403
        out = w.request("DELETE", f"subscriptions/{w.a}/sub-in", **kwargs)
        assert out.response.status_code == 403
        assert w.replica(w.a) == []
        assert w.subscription_exists("sub-in", callback=True)
        assert w.stored_permissions(w.a) is None

    def test_an_unapproved_peer_is_refused(self) -> None:
        w = World()
        out = w.request("POST", f"permissions/{w.e}", _permission_body(), as_peer=w.e)
        assert out.response.status_code == 403
        assert w.stored_permissions(w.e) is None

    @pytest.mark.parametrize(
        "name",
        [
            "subscriptions/",
            "subscriptions//sub-in",
            "subscriptions/peer",
            "permissions/",
        ],
    )
    def test_an_empty_or_short_peer_segment_is_400(self, name: str) -> None:
        w = World()
        out = w.request("POST", name, w.diff(), as_peer=w.a)
        assert out.response.status_code == 400

    def test_the_short_delete_path_is_400(self) -> None:
        w = World()
        out = w.request("DELETE", f"subscriptions/{w.a}", as_peer=w.a)
        assert out.response.status_code == 400

    def test_the_peer_itself_high_granularity(self) -> None:
        w = World()
        out = w.request("POST", f"subscriptions/{w.a}/sub-in", w.diff(), as_peer=w.a)
        assert out.response.status_code == 204
        assert w.replica(w.a) == ["planted"]

    def test_the_peer_itself_resync(self) -> None:
        w = World()
        from actingweb.interface.subscription_manager import SubscriptionManager

        with mock.patch.object(
            SubscriptionManager,
            "_fetch_and_transform_baseline",
            return_value={"baseline": {"v": 2}},
        ):
            out = w.request(
                "POST",
                f"subscriptions/{w.a}/sub-in",
                {
                    "id": w.a,
                    "sequence": 1,
                    "type": "resync",
                    "url": "https://elsewhere.example.test/p",
                },
                as_peer=w.a,
            )
        assert out.response.status_code == 204
        assert w.replica(w.a) == ["baseline"]

    def test_the_peer_itself_permission_callback(self) -> None:
        w = World()
        out = w.request("POST", f"permissions/{w.a}", _permission_body(), as_peer=w.a)
        assert out.response.status_code == 204
        stored = w.stored_permissions(w.a)
        assert stored and stored["properties"]["excluded_patterns"] == ["x"]

    def test_the_peer_deletes_its_subscription(self) -> None:
        w = World()
        out = w.request("DELETE", f"subscriptions/{w.a}/sub-in", as_peer=w.a)
        assert out.response.status_code == 204
        assert not w.subscription_exists("sub-in", callback=True)

    def test_a_subscriber_cannot_post_to_its_publisher(self) -> None:
        """B holds ``sub-out`` as publisher (callback false): A posting under
        it is refused and nothing is stored."""
        w = World()
        out = w.request(
            "POST", f"subscriptions/{w.a}/sub-out", w.diff("sub-out"), as_peer=w.a
        )
        assert out.response.status_code == 403
        assert w.replica(w.a) == []


class TestCallbackType:
    @pytest.mark.parametrize("kind", ["permission", "bogus", ""])
    def test_another_type_is_400_and_nothing_runs(self, kind: str) -> None:
        hooks = HookRegistry()
        legacy = mock.Mock(return_value=True)
        hooks.register_callback_hook("subscription", legacy)
        w = World(hooks=hooks)
        with mock.patch.object(CallbackProcessor, "process_callback_sync") as process:
            out = w.request(
                "POST",
                f"subscriptions/{w.a}/sub-in",
                w.diff(type=kind),
                as_peer=w.a,
            )
        assert out.response.status_code == 400
        process.assert_not_called()
        legacy.assert_not_called()

    @pytest.mark.parametrize("kind", [None, "diff"])
    def test_an_absent_type_or_diff_is_a_diff(self, kind: str | None) -> None:
        w = World()
        body = w.diff() if kind is None else w.diff(type=kind)
        out = w.request("POST", f"subscriptions/{w.a}/sub-in", body, as_peer=w.a)
        assert out.response.status_code == 204


class TestLowGranularityFetch:
    @pytest.mark.parametrize(
        ("baseuri", "expected"),
        [
            (
                "https://a.example.test/a",
                "https://a.example.test/a/subscriptions/b/s/3",
            ),
            (
                "https://a.example.test/a/",
                "https://a.example.test/a/subscriptions/b/s/3",
            ),
        ],
    )
    def test_the_url_joins_with_one_slash(self, baseuri: str, expected: str) -> None:
        assert low_granularity_fetch_url(baseuri, "b", "s", 3) == expected

    def test_the_fetch_goes_to_the_stored_base_uri_whatever_the_body_says(
        self,
    ) -> None:
        w = World(granularity="low")
        expected = f"https://{w.a}.example.test/{w.a}/subscriptions/{aid(w.b)}/sub-in/1"
        fetched: list[str] = []

        def get(url: str, **_kw: Any) -> Any:
            # Any other host fails the test.
            assert url == expected, url
            fetched.append(url)
            return mock.Mock(status_code=200, json=lambda: {"data": {"low": 1}})

        client = mock.MagicMock()
        client.__enter__.return_value.get.side_effect = get
        with (
            mock.patch("httpx.Client", return_value=client),
            mock.patch("actingweb.aw_proxy.AwProxy.change_resource", return_value={}),
        ):
            out = w.request(
                "POST",
                f"subscriptions/{w.a}/sub-in",
                {
                    "id": w.a,
                    "sequence": 1,
                    "granularity": "low",
                    "url": "https://attacker.example.test/collect",
                },
                as_peer=w.a,
            )
        assert out.response.status_code == 204
        assert fetched == [expected]
        assert w.replica(w.a) == ["low"]


class TestPermissionTimestamp:
    def test_unparsable_is_400_and_nothing_stored(self) -> None:
        w = World()
        out = w.request(
            "POST", f"permissions/{w.a}", _permission_body("not a time"), as_peer=w.a
        )
        assert out.response.status_code == 400
        assert w.stored_permissions(w.a) is None

    def test_a_timestamp_a_day_ahead_is_400_with_a_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        w = World()
        ahead = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        with caplog.at_level(logging.WARNING, logger="actingweb.handlers.callbacks"):
            out = w.request(
                "POST", f"permissions/{w.a}", _permission_body(ahead), as_peer=w.a
            )
        assert out.response.status_code == 400
        assert w.stored_permissions(w.a) is None
        assert any("ahead of this" in r.getMessage() for r in caplog.records)
        # A current update applies.
        out = w.request(
            "POST",
            f"permissions/{w.a}",
            _permission_body(datetime.now(UTC).isoformat(), excluded="later"),
            as_peer=w.a,
        )
        assert out.response.status_code == 204
        stored = w.stored_permissions(w.a)
        assert stored and stored["properties"]["excluded_patterns"] == ["later"]

    def test_within_the_skew_the_senders_order_holds(self) -> None:
        """A sender two minutes fast: its revoke arrives before its earlier
        grant; the grant is older and changes nothing."""
        w = World()
        fast = datetime.now(UTC) + timedelta(minutes=2)
        revoke = _permission_body((fast + timedelta(seconds=1)).isoformat(), "revoked")
        grant = _permission_body(fast.isoformat(), "granted")
        out = w.request("POST", f"permissions/{w.a}", revoke, as_peer=w.a)
        assert out.response.status_code == 204
        out = w.request("POST", f"permissions/{w.a}", grant, as_peer=w.a)
        assert out.response.status_code == 204
        stored = w.stored_permissions(w.a)
        assert stored and stored["properties"]["excluded_patterns"] == ["revoked"]

    def test_an_older_update_is_ignored_and_runs_no_hook(self) -> None:
        hooks = HookRegistry()
        hook = mock.Mock(return_value=True)
        hooks.register_callback_hook("permissions", hook)
        w = World(hooks=hooks)
        now = datetime.now(UTC)
        out = w.request(
            "POST", f"permissions/{w.a}", _permission_body(now.isoformat()), as_peer=w.a
        )
        assert out.response.status_code == 204
        assert hook.call_count == 1
        older = (now - timedelta(hours=1)).isoformat()
        out = w.request(
            "POST",
            f"permissions/{w.a}",
            _permission_body(older, excluded="older"),
            as_peer=w.a,
        )
        assert out.response.status_code == 204
        assert hook.call_count == 1
        stored = w.stored_permissions(w.a)
        assert stored and stored["properties"]["excluded_patterns"] == ["x"]


class TestReservedNames:
    @pytest.mark.parametrize(
        "name",
        ["permissions", "subscription", "subscriptions", "www", "resource_x", "WWW"],
    )
    @pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
    def test_reserved_names_are_403_and_run_no_hook(
        self, name: str, method: str
    ) -> None:
        hooks = HookRegistry()
        named = mock.Mock(return_value={"ran": True})
        wildcard = mock.Mock(return_value={"ran": True})
        hooks.register_callback_hook(name, named)
        hooks.register_callback_hook("*", wildcard)
        w = World(hooks=hooks)
        out = w.request(method, name, {"x": 1}, as_peer=w.a)
        # A bare "subscriptions" POST or DELETE is the subscription branch
        # with its ids missing.
        expected = 400 if name == "subscriptions" and method != "GET" else 403
        assert out.response.status_code == expected
        named.assert_not_called()
        wildcard.assert_not_called()

    @pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
    def test_an_ordinary_name_runs_its_hook(self, method: str) -> None:
        hooks = HookRegistry()
        hook = mock.Mock(return_value={"pong": True})
        hooks.register_callback_hook("ping", hook)
        w = World(hooks=hooks)
        out = w.request(method, "ping", {"x": 1}, as_peer=w.c)
        assert out.response.status_code == 200
        assert hook.call_count == 1

    @pytest.mark.parametrize(
        ("name", "reserved"),
        [
            ("permissions", True),
            ("permissions/x", True),
            ("resource_files", True),
            ("Subscriptions", True),
            ("ping", False),
            ("resources", False),
            ("", False),
        ],
    )
    def test_is_reserved_callback_name(self, name: str, reserved: bool) -> None:
        assert is_reserved_callback_name(name) is reserved


class TestPhase1ReviewFixes:
    """The outside voice on the Phase 1 commit (verification document)."""

    def test_a_put_is_authorised_as_put(self) -> None:
        hooks = HookRegistry()
        hook = mock.Mock(return_value={"pong": True})
        hooks.register_callback_hook("ping", hook)
        w = World(hooks=hooks)
        # The callbacks row narrowed to POST: a PUT is not admitted by it.
        index = w.config.access.index(("any", "callbacks", "", "a"))
        w.config.access[index] = ("any", "callbacks", "POST", "a")
        out = w.request("PUT", "ping", {"x": 1}, as_peer=w.a)
        assert out.response.status_code == 403
        hook.assert_not_called()
        out = w.request("POST", "ping", {"x": 1}, as_peer=w.a)
        assert out.response.status_code == 200
        assert hook.call_args.args[2]["method"] == "POST"

    def test_a_put_reaches_the_hook_as_put(self) -> None:
        hooks = HookRegistry()
        hook = mock.Mock(return_value={"pong": True})
        hooks.register_callback_hook("ping", hook)
        w = World(hooks=hooks)
        out = w.request("PUT", "ping", {"x": 1}, as_peer=w.a)
        assert out.response.status_code == 200
        assert hook.call_args.args[2]["method"] == "PUT"

    def test_a_timestamp_that_overflows_in_utc_is_400(self) -> None:
        w = World()
        out = w.request(
            "POST",
            f"permissions/{w.a}",
            _permission_body("0001-01-01T00:00:00+05:00"),
            as_peer=w.a,
        )
        assert out.response.status_code == 400
        assert w.stored_permissions(w.a) is None

    def test_a_stale_update_deletes_and_syncs_nothing(self) -> None:
        w = World()
        w.config.auto_delete_on_revocation = True  # type: ignore[attr-defined]
        now = datetime.now(UTC)
        out = w.request(
            "POST", f"permissions/{w.a}", _permission_body(now.isoformat()), as_peer=w.a
        )
        assert out.response.status_code == 204
        older = (now - timedelta(hours=1)).isoformat()
        from actingweb.peer_permissions import PeerPermissions

        # The stale update revokes: the peer is asked (reverify-4, Issue 5);
        # here it does not answer, so nothing changes.
        unanswered = PeerPermissions(actor_id="x", peer_id=w.a, fetch_error="down")
        with (
            mock.patch(
                "actingweb.peer_permissions.fetch_peer_permissions",
                return_value=unanswered,
            ),
            mock.patch.object(CallbacksHandler, "_delete_revoked_peer_data") as delete,
            mock.patch.object(
                CallbacksHandler, "_incremental_sync_granted_properties"
            ) as sync,
        ):
            out = w.request(
                "POST",
                f"permissions/{w.a}",
                {
                    "type": "permission",
                    "timestamp": older,
                    "data": {"properties": {"patterns": [], "operations": ["read"]}},
                },
                as_peer=w.a,
            )
        assert out.response.status_code == 204
        delete.assert_not_called()
        sync.assert_not_called()
        stored = w.stored_permissions(w.a)
        assert stored and stored["properties"]["excluded_patterns"] == ["x"]


class TestThePermissionOrderUsesOneClock:
    """Verification of 2026-11-08, Issue 7: callbacks are ordered by the
    sender's clock among themselves only; every stored copy carries the
    receiver's clock, compared as times."""

    def _store(self, w: World, fetched_at: str, extra: dict[str, Any]) -> None:
        from actingweb.peer_permissions import (
            PeerPermissions,
            get_peer_permission_store,
        )

        store = get_peer_permission_store(w.config)
        store._cache.clear()  # noqa: SLF001 - start from the stored row
        assert store.store_permissions(
            PeerPermissions(
                actor_id=aid(w.b),
                peer_id=w.a,
                properties={"patterns": ["*"], "operations": ["read"]},
                fetched_at=fetched_at,
                extra_attributes=extra,
            )
        )

    def test_a_slow_senders_revocation_after_a_fetched_copy_applies(self) -> None:
        w = World()
        # A copy the receiver fetched by query, stamped with its own clock.
        self._store(w, datetime.now(UTC).isoformat(), {})
        slow = (datetime.now(UTC) - timedelta(seconds=30)).isoformat()
        out = w.request(
            "POST",
            f"permissions/{w.a}",
            _permission_body(slow, excluded="revoked"),
            as_peer=w.a,
        )
        assert out.response.status_code == 204
        stored = w.stored_permissions(w.a)
        assert stored and stored["properties"]["excluded_patterns"] == ["revoked"]
        assert stored["extra_attributes"]["sender_timestamp"]

    def test_a_row_stamped_in_another_offset_does_not_block_a_newer_one(
        self,
    ) -> None:
        w = World()
        # Stored before 3.16, an hour ago, in the sender's +02:00 format: as a
        # string it sorts after the current UTC time.
        an_hour_ago = (datetime.now(UTC) - timedelta(hours=1)).astimezone(
            timezone(timedelta(hours=2))
        )
        self._store(w, an_hour_ago.isoformat(), {})
        out = w.request(
            "POST",
            f"permissions/{w.a}",
            _permission_body(datetime.now(UTC).isoformat(), excluded="newer"),
            as_peer=w.a,
        )
        assert out.response.status_code == 204
        stored = w.stored_permissions(w.a)
        assert stored and stored["properties"]["excluded_patterns"] == ["newer"]


class TestThePermissionBranchEdges:
    """Verification of 2026-11-08, Issue 9."""

    def test_a_put_reaches_the_permissions_hook_as_put(self) -> None:
        hooks = HookRegistry()
        hook = mock.Mock(return_value=True)
        hooks.register_callback_hook("permissions", hook)
        w = World(hooks=hooks)
        out = w.request("PUT", f"permissions/{w.a}", _permission_body(), as_peer=w.a)
        assert out.response.status_code == 204
        assert hook.call_args.args[2]["method"] == "PUT"

    @pytest.mark.parametrize("body", [[1, 2], 3, {"data": [1]}, {"data": "x"}])
    def test_a_body_that_is_not_an_object_is_400(self, body: Any) -> None:
        w = World()
        out = w.request("POST", f"permissions/{w.a}", body, as_peer=w.a)
        assert out.response.status_code == 400
        assert w.stored_permissions(w.a) is None


class TestConcurrentPermissionCallbacks:
    """Verification of 2026-11-08 (reverify-1), Issue 4: a callback stores
    only over the row it read; one that loses the race decides again against
    the winner's row."""

    def test_an_older_callback_that_loses_the_race_is_ignored(self) -> None:
        from actingweb.peer_permissions import PeerPermissionStore

        w = World()
        now = datetime.now(UTC)
        first = w.request(
            "POST",
            f"permissions/{w.a}",
            _permission_body((now - timedelta(seconds=30)).isoformat(), "first"),
            as_peer=w.a,
        )
        assert first.response.status_code == 204
        real = PeerPermissionStore.replace_permissions
        raced: list[int] = []

        def racing(store: Any, perms: Any, expected: Any) -> bool:
            if not raced:
                raced.append(1)
                # Another worker stores the peer's newer callback meanwhile.
                newer = w.request(
                    "POST",
                    f"permissions/{w.a}",
                    _permission_body(
                        (now - timedelta(seconds=10)).isoformat(), "newer"
                    ),
                    as_peer=w.a,
                )
                assert newer.response.status_code == 204
            return real(store, perms, expected)

        with mock.patch.object(PeerPermissionStore, "replace_permissions", racing):
            out = w.request(
                "POST",
                f"permissions/{w.a}",
                _permission_body((now - timedelta(seconds=20)).isoformat(), "older"),
                as_peer=w.a,
            )
        assert out.response.status_code == 204
        stored = w.stored_permissions(w.a)
        assert stored and stored["properties"]["excluded_patterns"] == ["newer"]

    def test_a_newer_callback_that_loses_the_race_is_stored(self) -> None:
        from actingweb.peer_permissions import PeerPermissionStore

        w = World()
        now = datetime.now(UTC)
        real = PeerPermissionStore.replace_permissions
        raced: list[int] = []

        def racing(store: Any, perms: Any, expected: Any) -> bool:
            if not raced:
                raced.append(1)
                older = w.request(
                    "POST",
                    f"permissions/{w.a}",
                    _permission_body(
                        (now - timedelta(seconds=20)).isoformat(), "older"
                    ),
                    as_peer=w.a,
                )
                assert older.response.status_code == 204
            return real(store, perms, expected)

        with mock.patch.object(PeerPermissionStore, "replace_permissions", racing):
            out = w.request(
                "POST",
                f"permissions/{w.a}",
                _permission_body((now - timedelta(seconds=10)).isoformat(), "newer"),
                as_peer=w.a,
            )
        assert out.response.status_code == 204
        stored = w.stored_permissions(w.a)
        assert stored and stored["properties"]["excluded_patterns"] == ["newer"]


def _grant_body(timestamp: str, patterns: list[str]) -> Any:
    return {
        "type": "permission",
        "timestamp": timestamp,
        "data": {"properties": {"patterns": patterns, "operations": ["read"]}},
    }


class TestEveryWriterOfTheCopyIsConditional:
    """Verification reverify-2, Issues 2 to 4: data a losing callback
    deleted comes back; a query result older than the stored copy is not
    stored, in any process; a fault is not taken for a lost race."""

    def test_a_revocation_that_loses_to_a_regrant_restores_what_it_deleted(
        self,
    ) -> None:
        from actingweb.peer_permissions import PeerPermissionStore

        w = World()
        w.config.auto_delete_on_revocation = True  # type: ignore[attr-defined]
        now = datetime.now(UTC)

        def at(seconds: int) -> str:
            return (now - timedelta(seconds=seconds)).isoformat()

        first = w.request(
            "POST", f"permissions/{w.a}", _grant_body(at(30), ["p/*"]), as_peer=w.a
        )
        assert first.response.status_code == 204
        real = PeerPermissionStore.replace_permissions
        raced: list[int] = []

        def racing(store: Any, perms: Any, expected: Any) -> bool:
            if not raced:
                raced.append(1)
                # The peer's newer re-grant is stored meanwhile; read against
                # the same row, it changes nothing and syncs nothing.
                regrant = w.request(
                    "POST",
                    f"permissions/{w.a}",
                    _grant_body(at(10), ["p/*"]),
                    as_peer=w.a,
                )
                assert regrant.response.status_code == 204
            return real(store, perms, expected)

        with (
            mock.patch.object(PeerPermissionStore, "replace_permissions", racing),
            mock.patch.object(CallbacksHandler, "_delete_revoked_peer_data") as delete,
            mock.patch.object(
                CallbacksHandler, "_incremental_sync_granted_properties"
            ) as sync,
        ):
            out = w.request(
                "POST", f"permissions/{w.a}", _grant_body(at(20), []), as_peer=w.a
            )
        assert out.response.status_code == 204
        assert delete.call_args.args[2] == ["p/*"]
        # The revocation lost and was then older: what it deleted, the stored
        # re-grant still grants, so it is fetched again.
        assert sync.call_args.kwargs["granted_patterns"] == ["p/*"]
        stored = w.stored_permissions(w.a)
        assert stored and stored["properties"]["patterns"] == ["p/*"]

    def test_a_revocation_that_loses_to_another_revocation_restores_nothing(
        self,
    ) -> None:
        """Reverify-3, Issue 1: what is restored is what the stored copy
        grants, not what the last diff happens not to revoke."""
        from actingweb.peer_permissions import PeerPermissionStore

        w = World()
        w.config.auto_delete_on_revocation = True  # type: ignore[attr-defined]
        now = datetime.now(UTC)

        def at(seconds: int) -> str:
            return (now - timedelta(seconds=seconds)).isoformat()

        first = w.request(
            "POST", f"permissions/{w.a}", _grant_body(at(30), ["p/*"]), as_peer=w.a
        )
        assert first.response.status_code == 204
        real = PeerPermissionStore.replace_permissions
        raced: list[int] = []

        def racing(store: Any, perms: Any, expected: Any) -> bool:
            if not raced:
                raced.append(1)
                # Another worker stores the peer's earlier revocation of P.
                other = w.request(
                    "POST", f"permissions/{w.a}", _grant_body(at(20), []), as_peer=w.a
                )
                assert other.response.status_code == 204
            return real(store, perms, expected)

        with (
            mock.patch.object(PeerPermissionStore, "replace_permissions", racing),
            mock.patch.object(CallbacksHandler, "_delete_revoked_peer_data"),
            mock.patch.object(
                CallbacksHandler, "_incremental_sync_granted_properties"
            ) as sync,
        ):
            out = w.request(
                "POST", f"permissions/{w.a}", _grant_body(at(10), []), as_peer=w.a
            )
        assert out.response.status_code == 204
        sync.assert_not_called()
        stored = w.stored_permissions(w.a)
        assert stored and stored["properties"]["patterns"] == []

    def test_the_503_exit_restores_what_the_stored_copy_grants(self) -> None:
        """Reverify-3, Issue 6: a revocation that never wins leaves the copy
        granting P; what it deleted of P is fetched again."""
        from actingweb.peer_permissions import PeerPermissionStore

        w = World()
        w.config.auto_delete_on_revocation = True  # type: ignore[attr-defined]
        now = datetime.now(UTC)
        first = w.request(
            "POST",
            f"permissions/{w.a}",
            _grant_body((now - timedelta(seconds=30)).isoformat(), ["p/*"]),
            as_peer=w.a,
        )
        assert first.response.status_code == 204
        with (
            mock.patch.object(
                PeerPermissionStore, "replace_permissions", return_value=False
            ),
            mock.patch.object(CallbacksHandler, "_delete_revoked_peer_data"),
            mock.patch.object(
                CallbacksHandler, "_incremental_sync_granted_properties"
            ) as sync,
        ):
            out = w.request(
                "POST",
                f"permissions/{w.a}",
                _grant_body((now - timedelta(seconds=10)).isoformat(), []),
                as_peer=w.a,
            )
        assert out.response.status_code == 503
        assert sync.call_args.kwargs["granted_patterns"] == ["p/*"]

    def test_a_query_copy_keeps_the_last_callbacks_timestamp(self) -> None:
        """Reverify-3, Issue 4: after a query write, an older callback (a
        resend after a 503) is still recognised as older."""
        from actingweb.peer_permissions import PeerPermissions, PeerPermissionStore

        w = World()
        now = datetime.now(UTC)
        newer = w.request(
            "POST",
            f"permissions/{w.a}",
            _grant_body((now - timedelta(seconds=10)).isoformat(), ["new/*"]),
            as_peer=w.a,
        )
        assert newer.response.status_code == 204
        queried = PeerPermissions(
            actor_id=aid(w.b),
            peer_id=w.a,
            properties={"patterns": ["new/*"], "operations": ["read"]},
            fetched_at=datetime.now(UTC).isoformat(),
        )
        assert PeerPermissionStore(w.config).store_permissions(queried) is True
        resent = w.request(
            "POST",
            f"permissions/{w.a}",
            _grant_body((now - timedelta(seconds=20)).isoformat(), ["old/*"]),
            as_peer=w.a,
        )
        assert resent.response.status_code == 204
        stored = w.stored_permissions(w.a)
        assert stored and stored["properties"]["patterns"] == ["new/*"]

    def test_an_ignored_revocation_asks_the_peer(self) -> None:
        """Reverify-4, Issue 5: a revocation that looks older (sender
        instances with skewed clocks) is checked against the peer's current
        permissions, which decide."""
        from actingweb.peer_permissions import PeerPermissions

        w = World()
        w.config.auto_delete_on_revocation = True  # type: ignore[attr-defined]
        now = datetime.now(UTC)
        grant = w.request(
            "POST",
            f"permissions/{w.a}",
            _grant_body((now - timedelta(seconds=10)).isoformat(), ["p/*"]),
            as_peer=w.a,
        )
        assert grant.response.status_code == 204
        current = PeerPermissions(
            actor_id=aid(w.b),
            peer_id=w.a,
            properties={"patterns": [], "operations": ["read"]},
            fetched_at=datetime.now(UTC).isoformat(),
        )
        with (
            mock.patch(
                "actingweb.peer_permissions.fetch_peer_permissions",
                return_value=current,
            ) as fetch,
            mock.patch.object(CallbacksHandler, "_delete_revoked_peer_data") as delete,
        ):
            out = w.request(
                "POST",
                f"permissions/{w.a}",
                _grant_body((now - timedelta(seconds=20)).isoformat(), []),
                as_peer=w.a,
            )
        assert out.response.status_code == 204
        fetch.assert_called_once()
        assert delete.call_args.args[2] == ["p/*"]
        stored = w.stored_permissions(w.a)
        assert stored and stored["properties"]["patterns"] == []

    def test_a_callback_without_a_timestamp_keeps_the_last_one(self) -> None:
        """Reverify-4, Issue 6: a later resend of an older callback stays
        older after a callback that carried no timestamp."""
        w = World()
        now = datetime.now(UTC)
        newer = w.request(
            "POST",
            f"permissions/{w.a}",
            _grant_body((now - timedelta(seconds=10)).isoformat(), ["new/*"]),
            as_peer=w.a,
        )
        assert newer.response.status_code == 204
        untimed = w.request(
            "POST",
            f"permissions/{w.a}",
            {
                "type": "permission",
                "data": {"properties": {"patterns": ["new/*"], "operations": ["read"]}},
            },
            as_peer=w.a,
        )
        assert untimed.response.status_code == 204
        resent = w.request(
            "POST",
            f"permissions/{w.a}",
            _grant_body((now - timedelta(seconds=20)).isoformat(), ["old/*"]),
            as_peer=w.a,
        )
        assert resent.response.status_code == 204
        stored = w.stored_permissions(w.a)
        assert stored and stored["properties"]["patterns"] == ["new/*"]

    def test_a_query_older_than_the_stored_copy_is_not_stored(self) -> None:
        from actingweb.peer_permissions import PeerPermissions, PeerPermissionStore

        w = World()
        began = datetime.now(UTC).isoformat()  # the query's fetch begins
        out = w.request(
            "POST",
            f"permissions/{w.a}",
            _grant_body(datetime.now(UTC).isoformat(), []),
            as_peer=w.a,
        )
        assert out.response.status_code == 204
        # Another process: nothing cached, only the stored row to go by.
        other = PeerPermissionStore(w.config)
        stale = PeerPermissions(
            actor_id=aid(w.b),
            peer_id=w.a,
            properties={"patterns": ["p/*"], "operations": ["read"]},
            fetched_at=began,
        )
        assert other.store_permissions(stale) is False
        stored = w.stored_permissions(w.a)
        assert stored and stored["properties"]["patterns"] == []

    def test_a_fault_on_the_conditional_write_raises(self) -> None:
        from actingweb.db.exceptions import DbError
        from actingweb.peer_permissions import PeerPermissions, PeerPermissionStore

        w = World()
        out = w.request(
            "POST",
            f"permissions/{w.a}",
            _grant_body(datetime.now(UTC).isoformat(), ["p/*"]),
            as_peer=w.a,
        )
        assert out.response.status_code == 204
        store = PeerPermissionStore(w.config)
        expected, _ = store.read_stored_permissions(aid(w.b), w.a)
        newer = PeerPermissions(
            actor_id=aid(w.b), peer_id=w.a, fetched_at=datetime.now(UTC).isoformat()
        )
        # Both backends answer a fault on a conditional update with False.
        with (
            mock.patch.object(
                Attributes, "conditional_update_attr", return_value=False
            ),
            pytest.raises(DbError),
        ):
            store.replace_permissions(newer, expected)
