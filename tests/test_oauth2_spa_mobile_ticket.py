"""Tests for the generic ``mobile_ticket`` grant on /oauth/spa/token.

The ticket flow was originally Apple-only (``apple_mobile_ticket``). Phase 8
generalizes it to any native-mobile provider whose authorization code is
exchanged server-side — notably GitHub mobile, which has no OIDC id_token and
derives identity from the userinfo endpoint. The ``apple_mobile_ticket`` name is
kept as an alias; the Apple path is covered by ``test_oauth2_spa_apple_ticket``.
"""

import json
import threading
from unittest.mock import MagicMock, patch

from actingweb.aw_web_request import AWWebObj
from actingweb.config import Config
from actingweb.handlers.oauth2_spa import OAuth2SPAHandler
from actingweb.oauth_state_store import MobileTicketStore

CLIENT_ID = "github-client-id"
DEEP_LINK = "io.example.app://callback"
CALLBACK = "https://test.example.com/oauth/callback"


def _make_config() -> Config:
    config = MagicMock(spec=Config)
    config.proto = "https://"
    config.fqdn = "test.example.com"
    config.oauth2_provider = "github-mobile"
    config.force_email_prop_as_creator = False
    config.service_registry = None
    config.devtest = False
    config.new_token = MagicMock(return_value="aw-access-token")
    config.oauth_providers = {
        "github-mobile": {
            "client_id": CLIENT_ID,
            "client_secret": "github-secret",
            "redirect_uri": CALLBACK,
            "mobile_deep_link": DEEP_LINK,
        },
    }
    config.oauth = {}

    storage: dict = {}
    # Guards delete_attr_conditional so the mock faithfully models the real
    # backends' atomic single-winner delete under concurrent redemption.
    consume_lock = threading.Lock()

    class MockDbAttribute:
        def __init__(self):  # type: ignore
            self.storage = storage

        def get_bucket(self, actor_id, bucket):  # type: ignore
            return self.storage.get(f"{actor_id}:{bucket}", {})

        def get_attr(self, actor_id, bucket, name):  # type: ignore
            return self.storage.get(f"{actor_id}:{bucket}", {}).get(name)

        def set_attr(
            self, actor_id, bucket, name, data, timestamp=None, ttl_seconds=None
        ):  # type: ignore
            self.storage.setdefault(f"{actor_id}:{bucket}", {})[name] = {"data": data}
            return True

        def delete_attr(self, actor_id, bucket, name):  # type: ignore
            key = f"{actor_id}:{bucket}"
            if key in self.storage and name in self.storage[key]:
                del self.storage[key][name]
                return True
            return False

        def delete_attr_conditional(self, actor_id, bucket, name):  # type: ignore
            key = f"{actor_id}:{bucket}"
            with consume_lock:
                if key in self.storage and name in self.storage[key]:
                    del self.storage[key][name]
                    return True
                return False

        def delete_bucket(self, actor_id, bucket):  # type: ignore
            return self.storage.pop(f"{actor_id}:{bucket}", None) is not None

    db_mod = MagicMock()
    db_mod.DbAttribute = MockDbAttribute
    config.DbAttribute = db_mod
    return config


def _handler(config, body: dict) -> OAuth2SPAHandler:
    webobj = AWWebObj(
        url="https://test.example.com/oauth/spa/token",
        params={},
        body=json.dumps(body),
        headers={"Accept": "application/json"},
        cookies={},
    )
    return OAuth2SPAHandler(webobj, config, hooks=None)


def _run(config, body):
    # GitHub token exchange: access_token only, NO id_token (identity comes from
    # the userinfo endpoint, exercising the generalized fallback path).
    token_resp = MagicMock()
    token_resp.status_code = 200
    token_body = {
        "access_token": "github-access",
        "token_type": "bearer",
        "scope": "read:user,user:email",
    }
    token_resp.json.return_value = token_body
    token_resp.text = json.dumps(token_body)

    userinfo_resp = MagicMock()
    userinfo_resp.status_code = 200
    userinfo_resp.json.return_value = {
        "id": 99887766,
        "login": "octocat",
        "name": "The Octocat",
        "email": "octocat@example.com",
    }

    mock_actor = MagicMock()
    mock_actor.id = "actor-gh"
    mock_actor.store = MagicMock()
    mock_actor.get_from_creator.return_value = True

    session_mgr = MagicMock()
    session_mgr.create_refresh_token.return_value = "aw-refresh"

    with (
        patch("actingweb.oauth2.requests.post", return_value=token_resp),
        patch("actingweb.oauth2.requests.get", return_value=userinfo_resp),
        patch("actingweb.actor.Actor", return_value=mock_actor),
        patch(
            "actingweb.oauth_session.get_oauth2_session_manager",
            return_value=session_mgr,
        ),
    ):
        return _handler(config, body)._handle_token()


def _ticket(config) -> str:
    return MobileTicketStore(config).create(
        code="github-auth-code",
        redirect_uri=CALLBACK,
        provider="github-mobile",
    )


class TestMobileTicketGrant:
    def test_github_ticket_creates_session(self) -> None:
        config = _make_config()
        ticket = _ticket(config)
        result = _run(config, {"grant_type": "mobile_ticket", "ticket": ticket})
        assert result.get("success") is True
        assert result.get("access_token") == "aw-access-token"

    def test_apple_alias_routes_to_same_handler(self) -> None:
        # The legacy grant name must still redeem a generic ticket.
        config = _make_config()
        ticket = _ticket(config)
        result = _run(config, {"grant_type": "apple_mobile_ticket", "ticket": ticket})
        assert result.get("success") is True

    def test_replayed_ticket_rejected(self) -> None:
        config = _make_config()
        ticket = _ticket(config)
        first = _run(config, {"grant_type": "mobile_ticket", "ticket": ticket})
        second = _run(config, {"grant_type": "mobile_ticket", "ticket": ticket})
        assert first.get("success") is True
        assert second.get("status_code") == 400

    def test_concurrent_consume_single_winner(self) -> None:
        # A single ticket consumed by many simultaneous redemptions must be
        # handed to exactly one caller (atomic single-use consume). A naive
        # read-then-delete would let several callers all observe the ticket
        # before any delete lands and each mint a session from one sign-in.
        config = _make_config()
        ticket = _ticket(config)
        store = MobileTicketStore(config)
        results: list = []
        barrier = threading.Barrier(8)

        def worker() -> None:
            barrier.wait()  # release all redemptions at once
            results.append(store.consume(ticket))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        winners = [r for r in results if r is not None]
        assert len(winners) == 1
        assert winners[0]["code"] == "github-auth-code"
        assert results.count(None) == 7

    def test_expired_ticket_rejected(self) -> None:
        # A ticket past its redemption window must be refused even though the
        # stored row still exists (the DB TTL purges it only later, with a
        # clock-skew buffer). A negative TTL stamps it already-expired.
        config = _make_config()
        expired = MobileTicketStore(config).create(
            code="github-auth-code",
            redirect_uri=CALLBACK,
            provider="github-mobile",
            ttl=-1,
        )
        result = _run(config, {"grant_type": "mobile_ticket", "ticket": expired})
        assert result.get("status_code") == 400

    def test_unknown_ticket_rejected(self) -> None:
        config = _make_config()
        result = _run(config, {"grant_type": "mobile_ticket", "ticket": "nope"})
        assert result.get("status_code") == 400

    def test_missing_ticket_rejected(self) -> None:
        config = _make_config()
        result = _handler(
            config, {"grant_type": "mobile_ticket", "ticket": ""}
        )._handle_token()
        assert result.get("status_code") == 400


class TestNativePkceFailClosed:
    """A native authorization_code exchange without PKCE must be rejected."""

    def test_mobile_provider_without_verifier_rejected(self) -> None:
        config = _make_config()
        result = _handler(config, {})._handle_authorization_code(
            {
                "code": "abc",
                "provider": "github-mobile",
                "redirect_uri": CALLBACK,
            },
            "json",
        )
        assert result.get("status_code") == 400
        assert "pkce" in result.get("message", "").lower()

    def test_custom_scheme_redirect_without_verifier_rejected(self) -> None:
        config = _make_config()
        result = _handler(config, {})._handle_authorization_code(
            {
                "code": "abc",
                "provider": "github",  # not a -mobile/-native name...
                "redirect_uri": "io.example.app://callback",  # ...but custom scheme
            },
            "json",
        )
        assert result.get("status_code") == 400
        assert "pkce" in result.get("message", "").lower()
