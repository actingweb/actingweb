"""PKCE (RFC 7636) is bound on the library's own MCP authorize paths.

GET and POST ``/oauth/authorize`` read ``code_challenge`` and
``code_challenge_method``; both show-form responses echo them; the
provider-button state and the POST redirect state carry them into the
callback, which stores them, with the ``redirect_uri``, on the code. The
library path requires ``S256``; exchange still accepts a ``plain`` challenge
stored directly through ``create_authorization_code`` (the consumer's own
password path).
"""

import base64
import contextlib
import hashlib
from collections.abc import Iterator
from typing import Any
from unittest import mock
from urllib.parse import parse_qs, urlencode, urlparse

import pytest

from actingweb.oauth2_server.oauth2_server import ActingWebOAuth2Server
from tests.mcp_oauth_server_helpers import make_handler, make_server, register
from tests.mcp_token_double import MemoryStore, make_config

VERIFIER = "a" * 20 + "b" * 30  # 50 unreserved characters
REDIRECT = "https://client/cb"


def _s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


CHALLENGE = _s256(VERIFIER)


@pytest.fixture
def env() -> tuple[ActingWebOAuth2Server, MemoryStore]:
    config, store = make_config()
    config.oauth_providers = {"google": {"client_id": "gid", "client_secret": "gsec"}}
    return make_server(config), store


@contextlib.contextmanager
def _patched(server: ActingWebOAuth2Server) -> Iterator[None]:
    with (
        mock.patch(
            "actingweb.oauth2_server.oauth2_server.get_actingweb_oauth2_server",
            return_value=server,
        ),
        mock.patch(
            "actingweb.trust_type_registry.get_registry",
            side_effect=RuntimeError("no registry in this test"),
        ),
    ):
        yield


def _authorize_params(client_id: str, **extra: str) -> dict[str, str]:
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "state": "client-state",
        "code_challenge": CHALLENGE,
        "code_challenge_method": "S256",
    }
    params.update(extra)
    return params


def _state_of(url: str) -> str:
    return parse_qs(urlparse(url).query)["state"][0]


class TestAuthorizeEcho:
    def test_html_get_carries_challenge_to_template_and_provider_state(
        self, env: Any
    ) -> None:
        server, _ = env
        cid = register(server, token_endpoint_auth_method="none")["client_id"]
        with _patched(server):
            handler = make_handler(
                server, params=_authorize_params(cid), headers={"Accept": "text/html"}
            )
            handler._handle_authorization_request("GET")
        values = handler.response.template_values
        assert values["code_challenge"] == CHALLENGE
        assert values["code_challenge_method"] == "S256"
        providers = values["oauth_providers"]
        assert providers
        ctx = server.state_manager.extract_mcp_context(_state_of(providers[0]["url"]))
        assert ctx is not None
        assert ctx["code_challenge"] == CHALLENGE
        assert ctx["code_challenge_method"] == "S256"

    def test_json_get_echoes_challenge_in_form_data(self, env: Any) -> None:
        server, _ = env
        cid = register(server, token_endpoint_auth_method="none")["client_id"]
        with _patched(server):
            handler = make_handler(
                server,
                params=_authorize_params(cid),
                headers={"Accept": "application/json"},
            )
            out = handler._handle_authorization_request("GET")
        assert out["form_data"]["code_challenge"] == CHALLENGE
        assert out["form_data"]["code_challenge_method"] == "S256"


class TestProviderRoundTrip:
    def _post_and_callback(self, server: ActingWebOAuth2Server, cid: str) -> str:
        body = urlencode(_authorize_params(cid, provider="google"))
        with _patched(server):
            handler = make_handler(server, body=body)
            out = handler._handle_authorization_request("POST")
        assert out.get("status") == "redirect", out
        state = _state_of(out["location"])
        ctx = server.state_manager.extract_mcp_context(state)
        assert ctx is not None
        assert ctx["code_challenge"] == CHALLENGE
        assert ctx["code_challenge_method"] == "S256"

        auth = mock.Mock()
        auth.exchange_code_for_token.return_value = {"access_token": "g"}
        auth.provider.extract_user_info_from_token_response.return_value = {
            "email": "u@example.com"
        }
        auth.get_email_from_user_info.return_value = "u@example.com"
        server._authenticator_cache["google"] = auth
        with (
            mock.patch.object(
                server,
                "_get_or_create_actor_for_email",
                return_value=mock.Mock(id="actor-pkce"),
            ),
            mock.patch("actingweb.oauth2.create_oauth2_trust_relationship"),
        ):
            result = server.handle_oauth_callback({"code": "upstream", "state": state})
        del server._authenticator_cache["google"]
        assert result["action"] == "redirect", result
        return parse_qs(urlparse(result["url"]).query)["code"][0]

    def test_stored_code_is_bound_and_verified(self, env: Any) -> None:
        server, store = env
        cid = register(server, token_endpoint_auth_method="none")["client_id"]
        tm = server.token_manager

        code = self._post_and_callback(server, cid)
        stored = store.data("actor-pkce", "mcp_auth_codes", code)
        assert stored["code_challenge"] == CHALLENGE
        assert stored["redirect_uri"] == REDIRECT
        assert (
            tm.exchange_authorization_code(
                code, cid, code_verifier="z" * 50, redirect_uri=REDIRECT
            )
            is None
        )

        code = self._post_and_callback(server, cid)
        assert tm.exchange_authorization_code(
            code, cid, code_verifier=VERIFIER, redirect_uri=REDIRECT
        )

        code = self._post_and_callback(server, cid)
        assert (
            tm.exchange_authorization_code(
                code, cid, code_verifier=VERIFIER, redirect_uri="https://other/cb"
            )
            is None
        )


class TestCallbackDoesNotUseCachedClientInfo:
    """The OAuth callback is a browser redirect with nothing linking it to an
    MCP session. It used to copy the most recent cached ``clientInfo`` (any
    user's) into the signing-in user's trust row; it must write none."""

    def test_callback_writes_no_cached_client_name(self, env: Any) -> None:
        from actingweb.handlers import mcp as mcp_mod

        server, _ = env
        cid = register(server, token_endpoint_auth_method="none")["client_id"]
        spoofed = {"name": "Spoofed Client", "version": "6.6.6"}
        mcp_mod._mcp_client_info_cache.clear()
        for key in ("mcp-session:someone-else", "unknown:0", "token:" + "0" * 32):
            mcp_mod.MCPHandler._cache_client_info(key, spoofed)

        body = urlencode(_authorize_params(cid, provider="google"))
        with _patched(server):
            out = make_handler(server, body=body)._handle_authorization_request("POST")
        state = _state_of(out["location"])
        auth = mock.Mock()
        auth.exchange_code_for_token.return_value = {"access_token": "g"}
        auth.provider.extract_user_info_from_token_response.return_value = {
            "email": "u@example.com"
        }
        auth.get_email_from_user_info.return_value = "u@example.com"
        server._authenticator_cache["google"] = auth
        core_actor = mock.Mock(id="actor-cb")
        try:
            with (
                mock.patch.object(
                    server, "_get_or_create_actor_for_email", return_value=core_actor
                ),
                mock.patch(
                    "actingweb.oauth2.create_oauth2_trust_relationship"
                ) as create_trust,
                mock.patch("actingweb.actor.Actor") as actor_cls,
            ):
                result = server.handle_oauth_callback(
                    {"code": "upstream", "state": state}
                )
        finally:
            del server._authenticator_cache["google"]
            mcp_mod._mcp_client_info_cache.clear()

        assert result["action"] == "redirect", result
        create_trust.assert_called_once()
        writes = [
            *create_trust.call_args_list,
            *core_actor.modify_trust_and_notify.call_args_list,
            *actor_cls.return_value.modify_trust_and_notify.call_args_list,
        ]
        assert "Spoofed Client" not in repr(writes)
        assert "6.6.6" not in repr(writes)
        assert "client_name" not in create_trust.call_args.kwargs


class TestAuthorizeValidation:
    @pytest.mark.parametrize(
        "overrides",
        [
            {"code_challenge_method": "plain"},
            {"code_challenge_method": ""},
            {"code_challenge": "x" * 42},
            {"code_challenge": "a+" * 30},
        ],
    )
    def test_refused(self, env: Any, overrides: dict[str, str]) -> None:
        server, _ = env
        cid = register(server)["client_id"]
        params: dict[str, Any] = _authorize_params(cid, **overrides)
        if not params["code_challenge_method"]:
            params["code_challenge_method"] = None
        resp = server.handle_authorization_request(params, "GET")
        assert resp["error"] == "invalid_request"

    def test_public_client_without_challenge(self, env: Any) -> None:
        server, _ = env
        cid = register(server, token_endpoint_auth_method="none")["client_id"]
        params: dict[str, Any] = _authorize_params(cid)
        params["code_challenge"] = None
        params["code_challenge_method"] = None
        resp = server.handle_authorization_request(params, "GET")
        assert resp["error"] == "invalid_request"


class TestLenientExchange:
    def test_explicit_plain_still_exchanges(self, env: Any) -> None:
        server, _ = env
        tm = server.token_manager
        code = tm.create_authorization_code(
            "actor-1",
            "mcp_c",
            {"access_token": "g"},
            code_challenge=VERIFIER,
            code_challenge_method="plain",
        )
        assert tm.exchange_authorization_code(code, "mcp_c", code_verifier=VERIFIER)

    def test_absent_method_does_not_exchange(self, env: Any) -> None:
        server, _ = env
        tm = server.token_manager
        code = tm.create_authorization_code(
            "actor-1", "mcp_c", {"access_token": "g"}, code_challenge=VERIFIER
        )
        assert (
            tm.exchange_authorization_code(code, "mcp_c", code_verifier=VERIFIER)
            is None
        )


def test_authorize_debug_log_holds_no_values(
    env: Any, caplog: pytest.LogCaptureFixture
) -> None:
    server, _ = env
    cid = register(server, token_endpoint_auth_method="none")["client_id"]
    body = urlencode(_authorize_params(cid, email="secret.person@example.com"))
    with (
        _patched(server),
        caplog.at_level("DEBUG", logger="actingweb.handlers.oauth2_endpoints"),
    ):
        handler = make_handler(server, body=body)
        handler._handle_authorization_request("POST")
    assert "code_challenge" in caplog.text  # the key name is logged
    assert "secret.person@example.com" not in caplog.text
    assert CHALLENGE not in caplog.text
