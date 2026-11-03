"""Signing in again with an emailed code (the email-form user whose provider
has no verified address).

Plan: thoughts/plans/2026-11-02-3-16-adoption-fault-followups.md, Iterations.
"""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import patch

import pytest

from actingweb import email_sign_in
from actingweb.aw_web_request import AWWebObj
from actingweb.db import get_attribute
from actingweb.handlers.oauth_email import OAuth2EmailHandler
from actingweb.interface.hooks import HookRegistry
from tests._adoption_helpers import aid, create_core_actor, make_config, uuid_email


@pytest.fixture
def config() -> Any:
    return make_config()


def _verified(config: Any) -> Any:
    return create_core_actor(config, uuid_email(), auth_method="email_verified")


class TestChallenge:
    def test_the_right_code_signs_in_once(self, config: Any) -> None:
        actor = _verified(config)
        challenge, code = email_sign_in.start_challenge(config, aid(actor), "a@x.com")
        assert email_sign_in.redeem(config, challenge, code) == aid(actor)
        assert email_sign_in.redeem(config, challenge, code) is None

    def test_a_wrong_code_counts_and_the_fifth_spends_it(self, config: Any) -> None:
        actor = _verified(config)
        challenge, code = email_sign_in.start_challenge(config, aid(actor), "a@x.com")
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(email_sign_in.MAX_TRIES - 1):
            assert email_sign_in.redeem(config, challenge, wrong) is None
        assert email_sign_in.redeem(config, challenge, code) == aid(actor)

        challenge, code = email_sign_in.start_challenge(config, aid(actor), "a@x.com")
        for _ in range(email_sign_in.MAX_TRIES):
            assert email_sign_in.redeem(config, challenge, wrong) is None
        assert email_sign_in.redeem(config, challenge, code) is None

    def test_an_attempt_that_cannot_be_counted_is_refused(self, config: Any) -> None:
        actor = _verified(config)
        challenge, code = email_sign_in.start_challenge(config, aid(actor), "a@x.com")
        with patch.object(
            type(get_attribute(config)), "conditional_update_attr", return_value=False
        ):
            assert email_sign_in.redeem(config, challenge, code) is None
        assert email_sign_in.redeem(config, challenge, code) == aid(actor)

    def test_an_expired_code_is_refused(self, config: Any) -> None:
        actor = _verified(config)
        challenge, code = email_sign_in.start_challenge(config, aid(actor), "a@x.com")
        with patch.object(time, "time", return_value=time.time() + 3600):
            assert email_sign_in.redeem(config, challenge, code) is None

    def test_the_code_is_not_stored(self, config: Any) -> None:
        actor = _verified(config)
        challenge, code = email_sign_in.start_challenge(config, aid(actor), "a@x.com")
        row = get_attribute(config).get_attr_strict(
            actor_id="_actingweb_system", bucket="_email_sign_in_codes", name=challenge
        )
        assert row is not None and code not in json.dumps(row["data"])


def _handler(config: Any, hooks: Any, body: dict[str, Any] | None = None) -> Any:
    webobj = AWWebObj(
        url="https://test.example.com/oauth/email",
        params={},
        body=json.dumps(body or {}),
        headers={"Accept": "application/json"},
        cookies={},
    )
    return OAuth2EmailHandler(webobj, config, hooks=hooks), webobj


class TestHandler:
    def _hooks(self, sent: list[dict[str, Any]]) -> HookRegistry:
        hooks = HookRegistry()
        hooks.register_lifecycle_hook(
            email_sign_in.HOOK, lambda actor, **kw: sent.append(kw)
        )
        return hooks

    def test_a_verified_address_gets_a_code_not_a_409(self, config: Any) -> None:
        sent: list[dict[str, Any]] = []
        actor = _verified(config)
        handler, _ = _handler(config, self._hooks(sent))
        answer = handler._offer_sign_in_code(actor, actor.creator)
        assert answer is not None and answer["status"] == "code_required"
        assert "code" not in answer  # only the mailbox gets the code
        assert len(sent) == 1 and len(sent[0]["code"]) == 6

    def test_without_the_hook_the_409_stays(self, config: Any) -> None:
        actor = _verified(config)
        handler, _ = _handler(config, HookRegistry())
        assert handler._offer_sign_in_code(actor, actor.creator) is None

    def test_an_unverified_actor_gets_no_code(self, config: Any) -> None:
        sent: list[dict[str, Any]] = []
        actor = create_core_actor(config, uuid_email(), auth_method="email_unverified")
        handler, _ = _handler(config, self._hooks(sent))
        assert handler._offer_sign_in_code(actor, actor.creator) is None
        assert sent == []

    def test_the_code_posted_back_signs_the_page_in(self, config: Any) -> None:
        from actingweb.oauth_session import get_oauth2_session_manager

        sent: list[dict[str, Any]] = []
        actor = _verified(config)
        hooks = self._hooks(sent)
        handler, _ = _handler(config, hooks)
        answer = handler._offer_sign_in_code(actor, actor.creator)
        assert answer is not None
        handler, _webobj = _handler(
            config,
            hooks,
            {"code_challenge": answer["code_challenge"], "code": sent[0]["code"]},
        )
        result = handler.post()
        assert result["status"] == "signed_in" and result["actor_id"] == aid(actor)
        token_data = get_oauth2_session_manager(config).validate_access_token(
            result["access_token"]
        )
        assert token_data is not None and token_data["actor_id"] == aid(actor)

    def test_a_wrong_code_answers_401(self, config: Any) -> None:
        sent: list[dict[str, Any]] = []
        actor = _verified(config)
        hooks = self._hooks(sent)
        handler, _ = _handler(config, hooks)
        answer = handler._offer_sign_in_code(actor, actor.creator)
        assert answer is not None
        handler, webobj = _handler(
            config, hooks, {"code_challenge": answer["code_challenge"], "code": "x"}
        )
        handler.post()
        assert webobj.response.status_code == 401


class TestHardening:
    def test_a_bound_challenge_needs_its_browser(self, config: Any) -> None:
        actor = _verified(config)
        challenge, code = email_sign_in.start_challenge(
            config, aid(actor), "a@x.com", binding="browser-1"
        )
        assert email_sign_in.redeem(config, challenge, code, "other-browser") is None
        assert email_sign_in.redeem(config, challenge, code, None) is None
        assert email_sign_in.redeem(config, challenge, code, "browser-1") == aid(actor)

    def test_a_new_challenge_does_not_void_the_previous_one(self, config: Any) -> None:
        """Whoever types the address cannot cancel the code its owner is
        typing; the hourly cap bounds the live challenges instead."""
        actor = _verified(config)
        first, first_code = email_sign_in.start_challenge(config, aid(actor), "a@x.com")
        second, second_code = email_sign_in.start_challenge(
            config, aid(actor), "a@x.com"
        )
        assert email_sign_in.redeem(config, first, first_code) == aid(actor)
        assert email_sign_in.redeem(config, second, second_code) == aid(actor)

    def test_a_json_challenge_cannot_be_redeemed_by_a_browser(
        self, config: Any
    ) -> None:
        """Login CSRF: an unbound (JSON) challenge posted from a browser form
        would plant the challenger's session; a cookie-issuing redemption
        needs a bound challenge."""
        actor = _verified(config)
        challenge, code = email_sign_in.start_challenge(config, aid(actor), "a@x.com")
        assert email_sign_in.redeem(config, challenge, code, None, browser=True) is None
        assert (
            email_sign_in.redeem(config, challenge, code, "any-cookie", browser=True)
            is None
        )
        assert email_sign_in.redeem(config, challenge, code) == aid(actor)

    def test_concurrent_starts_stay_within_the_cap(self, config: Any) -> None:
        from concurrent.futures import ThreadPoolExecutor

        actor = _verified(config)

        def start(_: int) -> str:
            try:
                email_sign_in.start_challenge(config, aid(actor), "a@x.com")
                return "ok"
            except email_sign_in.TooManyChallenges:
                return "capped"
            except Exception:  # lost the window race three times (503)
                return "fault"

        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(start, range(12)))
        assert results.count("ok") <= email_sign_in.MAX_CHALLENGES_PER_HOUR

    def test_a_malformed_challenge_id_is_refused_before_the_store(
        self, config: Any
    ) -> None:
        assert email_sign_in.redeem(config, "A" * 2000, "123456") is None

    def test_challenges_per_actor_are_capped(self, config: Any) -> None:
        actor = _verified(config)
        for _ in range(email_sign_in.MAX_CHALLENGES_PER_HOUR):
            email_sign_in.start_challenge(config, aid(actor), "a@x.com")
        with pytest.raises(email_sign_in.TooManyChallenges):
            email_sign_in.start_challenge(config, aid(actor), "a@x.com")

    def test_the_web_form_sets_the_binding_cookie(self, config: Any) -> None:
        sent: list[dict[str, Any]] = []
        hooks = HookRegistry()
        hooks.register_lifecycle_hook(
            email_sign_in.HOOK, lambda actor, **kw: sent.append(kw)
        )
        actor = _verified(config)
        webobj = AWWebObj(
            url="https://test.example.com/oauth/email",
            params={},
            body="",
            headers={},
            cookies={},
        )
        handler = OAuth2EmailHandler(webobj, config, hooks=hooks)
        handler._offer_sign_in_code(actor, actor.creator)
        cookies = {c["name"]: c for c in webobj.response.cookies}
        assert email_sign_in.BINDING_COOKIE.startswith("__Host-")
        assert email_sign_in.BINDING_COOKIE in cookies
        cookie = cookies[email_sign_in.BINDING_COOKIE]
        assert cookie["httponly"] is True and cookie["secure"] is True
        assert cookie["path"] == "/" and cookie["samesite"] == "Strict"

    def test_a_tombstoned_actor_gets_no_code(self, config: Any) -> None:
        from actingweb import deletion

        sent: list[dict[str, Any]] = []
        hooks = HookRegistry()
        hooks.register_lifecycle_hook(
            email_sign_in.HOOK, lambda actor, **kw: sent.append(kw)
        )
        actor = _verified(config)
        deletion.mark_actor_deleted(aid(actor), config, reason="deleted")
        handler, _ = _handler(config, hooks)
        assert handler._offer_sign_in_code(actor, actor.creator) is None
        assert sent == []


# --- Through the integrations: the binding cookie reaches the browser -----


def _apps(hooks_sent: list[dict[str, Any]]) -> tuple[Any, Any, Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from flask import Flask

    from actingweb.interface import ActingWebApp
    from actingweb.interface.integrations.fastapi_integration import (
        FastAPIIntegration,
    )
    from actingweb.interface.integrations.flask_integration import FlaskIntegration

    aw_app = ActingWebApp(
        aw_type="urn:actingweb:test:sign-in-code",
        database="dynamodb",
        fqdn="test.example.com",
        proto="https://",
    ).with_devtest(enable=True)
    aw_app.hooks.register_lifecycle_hook(
        email_sign_in.HOOK, lambda actor, **kw: hooks_sent.append(kw)
    )
    flask_app = Flask(__name__)
    FlaskIntegration(aw_app, flask_app).setup_routes()
    fastapi_app = FastAPI()
    FastAPIIntegration(aw_app, fastapi_app).setup_routes()
    return aw_app, flask_app, TestClient(fastapi_app, base_url="https://testserver")


def _offer_through_route(actor: Any) -> Any:
    """Replace the form submission (which needs a claimed provider session)
    by the offer it ends in, so the request still goes through the route."""

    def post(self: OAuth2EmailHandler) -> dict[str, Any]:
        return self._offer_sign_in_code(actor, actor.creator) or {}

    return patch.object(OAuth2EmailHandler, "post", post)


class TestThroughTheIntegrations:
    @pytest.mark.parametrize("framework", ["flask", "fastapi"])
    def test_offer_then_redeem_in_one_browser_signs_in(self, framework: str) -> None:
        sent: list[dict[str, Any]] = []
        aw_app, flask_app, fastapi_client = _apps(sent)
        actor = create_core_actor(
            aw_app.get_config(), uuid_email(), auth_method="email_verified"
        )
        client = flask_app.test_client() if framework == "flask" else fastapi_client
        kwargs: dict[str, Any] = (
            {"base_url": "https://localhost"} if framework == "flask" else {}
        )
        with _offer_through_route(actor):
            page = client.post("/oauth/email", data={"email": "x"}, **kwargs)
        set_cookie = (
            " ".join(page.headers.get_all("Set-Cookie"))
            if framework == "flask"
            else page.headers.get("set-cookie", "")
        )
        assert email_sign_in.BINDING_COOKIE in set_cookie
        assert "samesite=strict" in set_cookie.lower()
        body = page.get_data(as_text=True) if framework == "flask" else page.text
        assert 'name="code_challenge"' in body
        challenge = body.split('name="code_challenge" value="')[1].split('"')[0]

        done = (
            client.post(
                "/oauth/email",
                data={"code_challenge": challenge, "code": sent[0]["code"]},
                **kwargs,
            )
            if framework == "flask"
            else client.post(
                "/oauth/email",
                data={"code_challenge": challenge, "code": sent[0]["code"]},
                follow_redirects=False,
            )
        )
        assert done.status_code == 302
        done_cookies = (
            " ".join(done.headers.get_all("Set-Cookie"))
            if framework == "flask"
            else done.headers.get("set-cookie", "")
        )
        assert "oauth_token=" in done_cookies

    def test_another_browser_gets_401_and_the_code_page_again(self) -> None:
        sent: list[dict[str, Any]] = []
        aw_app, flask_app, _ = _apps(sent)
        actor = create_core_actor(
            aw_app.get_config(), uuid_email(), auth_method="email_verified"
        )
        with _offer_through_route(actor):
            page = flask_app.test_client().post(
                "/oauth/email", data={"email": "x"}, base_url="https://localhost"
            )
        challenge = (
            page.get_data(as_text=True)
            .split('name="code_challenge" value="')[1]
            .split('"')[0]
        )
        other = flask_app.test_client().post(
            "/oauth/email",
            data={"code_challenge": challenge, "code": sent[0]["code"]},
            base_url="https://localhost",
        )
        assert other.status_code == 401
        assert "oauth_token=" not in " ".join(other.headers.get_all("Set-Cookie"))
        body = other.get_data(as_text=True)
        assert "Invalid or expired sign-in code" in body
        assert 'name="code_challenge"' in body

    def test_a_json_challenge_posted_by_a_cross_site_form_is_refused(self) -> None:
        """The attack: a challenge the attacker created over JSON, with the
        code from their own mailbox, auto-submitted by the victim's browser."""
        sent: list[dict[str, Any]] = []
        aw_app, flask_app, _ = _apps(sent)
        actor = create_core_actor(
            aw_app.get_config(), uuid_email(), auth_method="email_verified"
        )
        with _offer_through_route(actor):
            answer = flask_app.test_client().post(
                "/oauth/email",
                json={"email": "x"},
                headers={"Accept": "application/json"},
                base_url="https://localhost",
            )
        challenge = answer.get_json()["code_challenge"]
        victim = flask_app.test_client().post(
            "/oauth/email",
            data={"code_challenge": challenge, "code": sent[0]["code"]},
            base_url="https://localhost",
        )
        assert victim.status_code == 401
        assert "oauth_token=" not in " ".join(victim.headers.get_all("Set-Cookie"))
