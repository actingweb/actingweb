"""``/oauth/logout`` and ``/oauth/revoke`` end the whole refresh-token chain.

Before 3.15.1 both endpoints deleted one row: logout the access token, revoke
the presented token. The refresh chain outlived them, and revoking a *used*
refresh token removed the row that would have caught a thief. These tests run
the real handlers on ``tests.mcp_token_double`` (a real Config over an
in-memory store with fault hooks).
"""

import json
from collections.abc import Iterator
from typing import Any
from unittest import mock
from urllib.parse import urlencode

import pytest

from actingweb.aw_web_request import AWWebObj
from actingweb.constants import OAUTH2_SYSTEM_ACTOR
from actingweb.handlers.oauth2_endpoints import OAuth2EndpointsHandler
from actingweb.handlers.oauth2_spa import OAuth2SPAHandler
from actingweb.oauth_session import (
    _ACCESS_TOKEN_BUCKET,
    _REFRESH_TOKEN_BUCKET,
    OAuth2SessionManager,
)
from tests.mcp_oauth_server_helpers import make_server
from tests.mcp_token_double import make_config

ACTOR = "actor-logout-chain"
EXPECTED_CLEARED = {
    ("access_token", "/"),
    ("oauth_token", "/"),
    ("refresh_token", "/"),
    ("refresh_token", "/oauth/spa/token"),
    ("session_id", "/"),
}


class Env:
    def __init__(self) -> None:
        self.config, self.store = make_config()
        self.mgr = OAuth2SessionManager(self.config)
        self.provider_clears: list[str] = []

    # -- seeding ----------------------------------------------------------
    def login(self, actor: str = ACTOR) -> tuple[str, str, str]:
        """A tagged login pair: ``(access, refresh, chain)``."""
        chain = self.mgr.new_chain_id()
        access = f"acc-{chain}"
        self.mgr.store_access_token(access, actor, "u@example.com", chain_id=chain)
        refresh = self.mgr.create_refresh_token(actor, "u@example.com", chain_id=chain)
        return access, refresh, chain

    def has(self, bucket: str, name: str) -> bool:
        return self.store.data(OAUTH2_SYSTEM_ACTOR, bucket, name) is not None

    def alive(self, access: str, refresh: str) -> tuple[bool, bool]:
        return self.has(_ACCESS_TOKEN_BUCKET, access), self.has(
            _REFRESH_TOKEN_BUCKET, refresh
        )

    # -- requests ---------------------------------------------------------
    def logout(
        self,
        *,
        method: str = "POST",
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        body: str | None = None,
        params: dict[str, str] | None = None,
    ) -> tuple[OAuth2EndpointsHandler, dict[str, Any]]:
        webobj = AWWebObj(
            url="https://test.example.com/oauth/logout",
            params=params or {},
            body=body,
            headers=headers or {},
            cookies=cookies or {},
        )
        with mock.patch(
            "actingweb.oauth2_server.oauth2_server.get_actingweb_oauth2_server",
            return_value=make_server(self.config),
        ):
            handler = OAuth2EndpointsHandler(webobj, self.config, hooks=None)
        result = handler.post("logout") if method == "POST" else handler.get("logout")
        return handler, result

    def spa(
        self, body: dict[str, Any] | None = None, **kwargs: Any
    ) -> OAuth2SPAHandler:
        webobj = AWWebObj(
            url="https://test.example.com/oauth/spa/token",
            params={},
            body=json.dumps(body or {}),
            headers=kwargs.pop("headers", {"Accept": "application/json"}),
            cookies=kwargs.pop("cookies", {}),
        )
        return OAuth2SPAHandler(webobj, self.config, hooks=None)

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        return self.spa()._handle_refresh_token(
            {"refresh_token": refresh_token}, "json"
        )

    def revoke(
        self,
        body: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
    ) -> tuple[OAuth2SPAHandler, dict[str, Any]]:
        handler = self.spa(
            body,
            headers=headers or {"Accept": "application/json"},
            cookies=cookies or {},
        )
        return handler, handler._handle_revoke()


@pytest.fixture
def env() -> Iterator[Env]:
    e = Env()
    with (
        mock.patch(
            "actingweb.oauth_session.get_oauth2_session_manager",
            return_value=e.mgr,
        ),
        mock.patch.object(
            OAuth2EndpointsHandler,
            "_clear_provider_token_for_actor",
            lambda _self, actor_id: e.provider_clears.append(actor_id),
        ),
        mock.patch.object(
            OAuth2SPAHandler,
            "_clear_provider_token_for_actor",
            lambda _self, actor_id: e.provider_clears.append(actor_id),
        ),
    ):
        yield e


def _cleared(handler: Any) -> set[tuple[str, str]]:
    return {
        (c["name"], c["path"])
        for c in handler.response.cookies
        if c["max_age"] is not None and c["max_age"] < 0
    }


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Login tagging
# ---------------------------------------------------------------------------


def test_the_passphrase_login_tags_its_pair_with_one_chain(env: Env) -> None:
    env.config.devtest = True
    actor = mock.MagicMock()
    actor.id = ACTOR
    actor.passphrase = "s3cret"
    actor.creator = "u@example.com"
    with mock.patch("actingweb.actor.Actor", return_value=actor):
        result = env.spa()._handle_passphrase_exchange(
            {"actor_id": ACTOR, "passphrase": "s3cret"}, "json"
        )

    access_row = env.store.data(
        OAUTH2_SYSTEM_ACTOR, _ACCESS_TOKEN_BUCKET, result["access_token"]
    )
    refresh_row = env.store.data(
        OAUTH2_SYSTEM_ACTOR, _REFRESH_TOKEN_BUCKET, result["refresh_token"]
    )
    assert access_row["chain_id"] is not None
    assert access_row["chain_id"] == refresh_row["chain_id"]


def test_a_rotation_keeps_the_pair_on_the_same_chain(env: Env) -> None:
    _access, refresh, chain = env.login()
    result = env.refresh(refresh)

    new_access = env.store.data(
        OAUTH2_SYSTEM_ACTOR, _ACCESS_TOKEN_BUCKET, result["access_token"]
    )
    new_refresh = env.store.data(
        OAUTH2_SYSTEM_ACTOR, _REFRESH_TOKEN_BUCKET, result["refresh_token"]
    )
    assert new_access["chain_id"] == new_refresh["chain_id"] == chain


# ---------------------------------------------------------------------------
# /oauth/logout
# ---------------------------------------------------------------------------


def test_logout_with_the_login_access_token_ends_the_chain(env: Env) -> None:
    access, refresh, _chain = env.login()
    other_access, other_refresh, _ = env.login()

    _handler, result = env.logout(headers=_bearer(access))

    assert result["success"] is True
    assert env.alive(access, refresh) == (False, False)
    assert env.refresh(refresh).get("status_code") == 401
    # Another device of the same actor is a different chain and keeps working.
    assert env.alive(other_access, other_refresh) == (True, True)
    assert env.provider_clears == [ACTOR]


def test_logout_after_a_rotation_ends_the_rotated_chain(env: Env) -> None:
    _access, refresh, _chain = env.login()
    rotated = env.refresh(refresh)

    _handler, result = env.logout(headers=_bearer(rotated["access_token"]))

    assert result["success"] is True
    assert env.refresh(rotated["refresh_token"]).get("status_code") == 401
    # The consumed predecessor is gone too, so it cannot rotate in the grace
    # window either.
    assert env.refresh(refresh).get("status_code") == 401


def test_logout_with_a_legacy_chainless_access_token_removes_only_that_row(
    env: Env,
) -> None:
    other_access, other_refresh, _ = env.login()
    env.mgr.store_access_token("legacy-www", ACTOR, "u@example.com")

    _handler, result = env.logout(headers=_bearer("legacy-www"))

    assert result["success"] is True
    assert not env.has(_ACCESS_TOKEN_BUCKET, "legacy-www")
    assert env.alive(other_access, other_refresh) == (True, True)


def test_a_get_logout_with_the_cookie_ends_the_chain_too(env: Env) -> None:
    access, refresh, _chain = env.login()

    _handler, result = env.logout(method="GET", cookies={"oauth_token": access})

    assert result["success"] is True
    assert env.alive(access, refresh) == (False, False)


def test_logout_with_an_expired_access_row_and_the_refresh_token_in_the_body(
    env: Env,
) -> None:
    access, refresh, _chain = env.login()
    env.store.rows[f"{OAUTH2_SYSTEM_ACTOR}:{_ACCESS_TOKEN_BUCKET}"].pop(access)

    _handler, result = env.logout(
        headers={"Content-Type": "application/json"},
        body=json.dumps({"refresh_token": refresh}),
    )

    assert result["success"] is True
    assert not env.has(_REFRESH_TOKEN_BUCKET, refresh)
    assert env.provider_clears == [ACTOR]


def test_logout_with_an_expired_access_row_and_the_refresh_cookie(env: Env) -> None:
    access, refresh, _chain = env.login()
    env.store.rows[f"{OAUTH2_SYSTEM_ACTOR}:{_ACCESS_TOKEN_BUCKET}"].pop(access)

    _handler, result = env.logout(cookies={"refresh_token": refresh})

    assert result["success"] is True
    assert not env.has(_REFRESH_TOKEN_BUCKET, refresh)


def test_logout_accepts_the_refresh_token_as_a_form_field(env: Env) -> None:
    _access, refresh, _chain = env.login()
    _handler, result = env.logout(
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=urlencode({"refresh_token": refresh}),
    )
    assert result["success"] is True
    assert not env.has(_REFRESH_TOKEN_BUCKET, refresh)


def test_a_refresh_token_in_the_query_string_is_ignored(env: Env) -> None:
    """A credential in a URL lands in logs; only the body or cookie count."""
    _access, refresh, _chain = env.login()
    _handler, result = env.logout(params={"refresh_token": refresh})
    assert result["success"] is True
    assert env.has(_REFRESH_TOKEN_BUCKET, refresh)


@pytest.mark.parametrize(
    "headers,body",
    [
        ({}, None),
        ({"Content-Type": "application/json"}, ""),
        ({"Content-Type": "application/json"}, "not json {"),
        ({"Content-Type": "application/json"}, json.dumps(["x"])),
        ({"Content-Type": "application/x-www-form-urlencoded"}, "a=b"),
    ],
)
def test_a_malformed_or_absent_body_is_ignored_not_a_400(
    env: Env, headers: dict[str, str], body: str | None
) -> None:
    access, refresh, _chain = env.login()

    handler, result = env.logout(headers={**_bearer(access), **headers}, body=body)

    assert handler.response.status_code == 200
    assert result["success"] is True
    assert env.alive(access, refresh) == (False, False)


def test_both_tokens_of_one_chain_cost_one_chain_delete(env: Env) -> None:
    access, refresh, _chain = env.login()
    scans: list[int] = []
    real = env.config.DbAttribute.DbAttribute.delete_by_chain

    with mock.patch.object(
        env.config.DbAttribute.DbAttribute,
        "delete_by_chain",
        lambda self, **kw: scans.append(1) or real(self, **kw),
    ):
        _handler, result = env.logout(
            headers={**_bearer(access), "Content-Type": "application/json"},
            body=json.dumps({"refresh_token": refresh}),
        )

    assert result["success"] is True
    assert scans == [1]


def test_two_different_chains_are_both_revoked(env: Env) -> None:
    access, refresh, _ = env.login()
    other_access, other_refresh, _ = env.login()

    _handler, result = env.logout(
        headers={**_bearer(access), "Content-Type": "application/json"},
        body=json.dumps({"refresh_token": other_refresh}),
    )

    assert result["success"] is True
    assert env.alive(access, refresh) == (False, False)
    assert env.alive(other_access, other_refresh) == (False, False)


def test_a_chain_fault_on_logout_is_503_and_keeps_everything(env: Env) -> None:
    access, refresh, _chain = env.login()
    env.store.chain_delete_fault = "zero"

    handler, result = env.logout(headers=_bearer(access))

    assert handler.response.status_code == 503
    assert handler.response.headers["Retry-After"] == "5"
    assert result == {
        "success": False,
        "error": "temporarily_unavailable",
        "message": "Token store temporarily unavailable; retry the logout",
        "method": "POST",
    }
    assert handler.response.cookies == []
    assert env.alive(access, refresh) == (True, True)
    assert env.provider_clears == []

    # The presented token is the retry handle.
    env.store.chain_delete_fault = None
    retry, ok = env.logout(headers=_bearer(access))
    assert ok["success"] is True
    assert env.alive(access, refresh) == (False, False)
    assert _cleared(retry) == EXPECTED_CLEARED
    assert ok["cleared_cookies"] == [
        "access_token",
        "oauth_token",
        "refresh_token",
        "session_id",
    ]


def test_a_faulting_lookup_is_503_not_logged_out(env: Env) -> None:
    """A store fault used to read as "unknown token" and answer success."""
    access, refresh, _chain = env.login()
    env.store.faulty_buckets.add(_ACCESS_TOKEN_BUCKET)

    handler, result = env.logout(headers=_bearer(access))

    assert handler.response.status_code == 503
    assert handler.response.cookies == []
    assert result["error"] == "temporarily_unavailable"
    env.store.faulty_buckets.clear()
    assert env.alive(access, refresh) == (True, True)


def test_a_faulting_chainless_delete_is_503(env: Env) -> None:
    env.mgr.store_access_token("legacy-www", ACTOR, "u@example.com")
    env.store.delete_faults.add(
        (OAUTH2_SYSTEM_ACTOR, _ACCESS_TOKEN_BUCKET, "legacy-www")
    )

    handler, _result = env.logout(headers=_bearer("legacy-www"))

    assert handler.response.status_code == 503
    assert env.has(_ACCESS_TOKEN_BUCKET, "legacy-www")


def test_an_unexpected_error_is_500_and_keeps_the_cookies_and_tokens(
    env: Env,
) -> None:
    """A bug is not a logout: no false 200, no cookie cleared, token kept."""
    access, refresh, _chain = env.login()

    with mock.patch.object(
        OAuth2EndpointsHandler,
        "_handle_session_token_logout",
        side_effect=RuntimeError("boom"),
    ):
        handler, result = env.logout(headers=_bearer(access))

    assert handler.response.status_code == 500
    assert result["error"] == "server_error"
    assert handler.response.cookies == []
    assert env.alive(access, refresh) == (True, True)


def test_a_token_less_logout_still_succeeds_and_clears_the_cookies(env: Env) -> None:
    handler, result = env.logout()
    assert result["success"] is True
    assert _cleared(handler) == EXPECTED_CLEARED


# ---------------------------------------------------------------------------
# /oauth/revoke
# ---------------------------------------------------------------------------


def test_revoking_a_used_refresh_token_revokes_the_chains_newest_token(
    env: Env,
) -> None:
    """The theft tripwire: revoking a used token used to delete its row and
    leave the live successor."""
    _access, refresh, _chain = env.login()
    rotated = env.refresh(refresh)

    _handler, result = env.revoke(
        {"token": refresh, "token_type_hint": "refresh_token"}
    )

    assert result["success"] is True
    assert env.alive(rotated["access_token"], rotated["refresh_token"]) == (
        False,
        False,
    )
    assert env.refresh(rotated["refresh_token"]).get("status_code") == 401


def test_revoking_an_access_token_with_a_chain_revokes_the_chain(env: Env) -> None:
    access, refresh, _chain = env.login()
    _handler, result = env.revoke({"token": access})
    assert result["success"] is True
    assert env.alive(access, refresh) == (False, False)


def test_revoking_a_chainless_refresh_token_revokes_only_itself(env: Env) -> None:
    other_access, other_refresh, _ = env.login()
    env.store.bucket(OAUTH2_SYSTEM_ACTOR, _REFRESH_TOKEN_BUCKET)["legacy-rt"] = {
        "data": {"actor_id": ACTOR, "identifier": "u@example.com", "used": False}
    }

    _handler, result = env.revoke(
        {"token": "legacy-rt", "token_type_hint": "refresh_token"}
    )

    assert result["success"] is True
    assert not env.has(_REFRESH_TOKEN_BUCKET, "legacy-rt")
    assert env.alive(other_access, other_refresh) == (True, True)


def test_revoking_an_unknown_token_is_200_and_clears_the_cookies(env: Env) -> None:
    handler, result = env.revoke({"token": "no-such-token"})
    assert result["success"] is True
    assert handler.response.status_code == 200
    assert _cleared(handler) == EXPECTED_CLEARED


def test_a_refresh_token_is_found_under_the_default_hint(env: Env) -> None:
    access, refresh, _chain = env.login()
    _handler, result = env.revoke({"token": refresh})
    assert result["success"] is True
    assert env.alive(access, refresh) == (False, False)


def test_an_unrecognised_hint_is_ignored(env: Env) -> None:
    access, refresh, _chain = env.login()
    _handler, result = env.revoke({"token": refresh, "token_type_hint": "banana"})
    assert result["success"] is True
    assert env.alive(access, refresh) == (False, False)


def test_a_revoke_fault_is_503_with_retry_after_and_the_token_still_works(
    env: Env,
) -> None:
    access, refresh, _chain = env.login()
    env.store.chain_delete_fault = "zero"

    handler, result = env.revoke({"token": access})

    assert handler.response.status_code == 503
    assert handler.response.headers["Retry-After"] == "5"
    assert result.get("status_code") == 503
    assert handler.response.cookies == []
    assert env.provider_clears == []
    assert env.alive(access, refresh) == (True, True)
    assert env.mgr.validate_access_token(access) is not None

    env.store.chain_delete_fault = None
    _handler, ok = env.revoke({"token": access})
    assert ok["success"] is True
    assert env.alive(access, refresh) == (False, False)


def test_revoking_an_unknown_token_during_an_outage_is_503_not_a_false_200(
    env: Env,
) -> None:
    env.store.faulty_buckets.add(_ACCESS_TOKEN_BUCKET)
    handler, _result = env.revoke({"token": "anything"})
    assert handler.response.status_code == 503


def test_revoke_reads_the_refresh_cookie_when_the_body_has_no_token(env: Env) -> None:
    access, refresh, _chain = env.login()
    env.store.rows[f"{OAUTH2_SYSTEM_ACTOR}:{_ACCESS_TOKEN_BUCKET}"].pop(access)

    _handler, result = env.revoke(cookies={"refresh_token": refresh})

    assert result["success"] is True
    assert not env.has(_REFRESH_TOKEN_BUCKET, refresh)


def test_revoke_reads_the_bearer_header_and_the_access_cookies(env: Env) -> None:
    access, refresh, _chain = env.login()
    _handler, result = env.revoke(headers=_bearer(access))
    assert result["success"] is True
    assert env.alive(access, refresh) == (False, False)

    access, refresh, _chain = env.login()
    _handler, result = env.revoke(cookies={"access_token": access})
    assert result["success"] is True
    assert env.alive(access, refresh) == (False, False)


def test_revoke_with_a_non_object_body_is_400(env: Env) -> None:
    handler = env.spa()
    handler.request.body = json.dumps(["not", "an", "object"])
    result = handler._handle_revoke()
    assert result.get("status_code") == 400
    assert handler.response.status_code == 400


def test_revoke_without_any_token_is_400(env: Env) -> None:
    handler, result = env.revoke()
    assert result.get("status_code") == 400
    assert handler.response.status_code == 400


def test_the_provider_token_is_cleared_after_a_confirmed_revoke(env: Env) -> None:
    access, _refresh, _chain = env.login()
    env.revoke({"token": access})
    assert env.provider_clears == [ACTOR]


# ---------------------------------------------------------------------------
# The SPA handler no longer carries a second, unreachable logout
# ---------------------------------------------------------------------------


def test_the_spa_handler_has_no_logout_endpoint(env: Env) -> None:
    result = env.spa().post("logout")
    assert result.get("status_code") == 404
    assert "Unknown SPA endpoint" in result.get("message", "")
