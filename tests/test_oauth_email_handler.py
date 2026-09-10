"""
Tests for ``POST /oauth/email`` (``OAuth2EmailHandler.post``) after the
3.14.5 fix: a free-text address that already has an actor is refused (409)
instead of silently adopted; the pending session is consumed on refusal;
``oauth_success`` fires on this path (previously it never did); a rejected
``oauth_success`` hook answers 403 without writing a verification token; the
membership check runs on the normalised address; the OAuth cookie is
HttpOnly; and CORS does not reflect an arbitrary origin.

Nothing exercised ``OAuth2EmailHandler.post()`` before this plan — see the
research doc referenced by the 3.14.5 plan.
"""

import json
from unittest.mock import MagicMock, patch

from actingweb.aw_web_request import AWWebObj
from actingweb.handlers.oauth_email import OAuth2EmailHandler

EXISTING_EMAIL = "probe.existing@example.com"
NEW_EMAIL = "new.user@example.com"


def _config(*, ui: bool = True, spa_cors_origins=None) -> MagicMock:
    config = MagicMock()
    config.ui = ui
    config.proto = "https://"
    config.fqdn = "test.example.com"
    config.service_registry = None
    config.spa_cors_origins = (
        spa_cors_origins if spa_cors_origins is not None else ["*"]
    )
    return config


def _webobj(
    *, session_id: str = "sess-1", email: str, json_client: bool = True, origin=None
) -> AWWebObj:
    headers = {}
    if json_client:
        headers["Accept"] = "application/json"
    if origin is not None:
        headers["Origin"] = origin
    return AWWebObj(
        url="https://test.example.com/oauth/email",
        params={},
        body=json.dumps({"session": session_id, "email": email}),
        headers=headers,
        cookies={},
    )


def _session(
    *,
    verified_emails=None,
    access_token: str = "provider-access-token",
    provider: str = "google",
) -> dict:
    return {
        "token_data": {"access_token": access_token, "expires_in": 3600},
        "user_info": {"sub": "u1", "email": None},
        "provider": provider,
        "verified_emails": verified_emails or [],
        "created_at": 0,
    }


def _hooks(*, oauth_success_result=True):
    """A hooks double that records every call and lets the test control
    oauth_success's return value (mirrors execute_lifecycle_hooks's own
    truthy/falsy-rejects contract)."""
    hooks = MagicMock()
    calls: list[tuple[str, dict]] = []

    def _exec(hook_name, actor_interface, **kwargs):
        calls.append((hook_name, kwargs))
        if hook_name == "oauth_success":
            return oauth_success_result
        return True

    hooks.execute_lifecycle_hooks.side_effect = _exec
    hooks.calls = calls
    return hooks


def _run_post(
    config,
    webobj,
    hooks,
    *,
    session,
    actor_exists: bool = False,
    complete_actor=None,
):
    existing_check = MagicMock()
    existing_check.get_from_creator.return_value = actor_exists

    session_mgr = MagicMock()
    session_mgr.get_session.return_value = session
    # try_claim_session() consumes the row and hands back the same dict; a
    # second concurrent caller would get None.
    session_mgr.try_claim_session.return_value = session
    session_mgr.complete_claimed_session.return_value = complete_actor

    with (
        patch("actingweb.actor.Actor", return_value=existing_check),
        patch(
            "actingweb.oauth_session.get_oauth2_session_manager",
            return_value=session_mgr,
        ),
    ):
        handler = OAuth2EmailHandler(webobj, config, hooks=hooks)
        result = handler.post()

    return result, session_mgr


def _new_actor(actor_id: str = "actor-new-1") -> MagicMock:
    actor = MagicMock()
    actor.id = actor_id
    actor.store = MagicMock()
    actor.store.oauth_token = "aw-oauth-token"
    return actor


class TestMixedCaseMatchesLowercasedVerifiedList:
    def test_mixed_case_against_lowercase_list_is_accepted(self):
        """Regression: the membership check must run on the normalised
        (stripped/lowercased) address, or 'Probe.Existing@Example.com'
        against ['probe.existing@example.com'] is wrongly rejected."""
        config = _config()
        webobj = _webobj(email="Probe.Existing@Example.com")
        hooks = _hooks()
        session = _session(verified_emails=[EXISTING_EMAIL])
        actor = _new_actor()

        result, session_mgr = _run_post(
            config, webobj, hooks, session=session, complete_actor=actor
        )

        assert result.get("status") == "success"
        session_mgr.complete_claimed_session.assert_called_once()
        call_args = session_mgr.complete_claimed_session.call_args[0]
        assert call_args[1] == EXISTING_EMAIL  # normalised


class TestFreeTextExistingAddressRefused:
    def test_returns_409_actor_exists_json(self):
        config = _config()
        webobj = _webobj(email=NEW_EMAIL)
        hooks = _hooks()
        session = _session(verified_emails=[])

        result, _session_mgr = _run_post(
            config, webobj, hooks, session=session, actor_exists=True
        )

        assert result["error"] is True
        assert result["code"] == "actor_exists"
        assert result["status_code"] == 409
        assert webobj.response.status_code == 409

    def test_session_is_consumed_before_the_existence_probe(self):
        """The claim is taken before get_from_creator() runs, so concurrent
        submissions of one session cannot each probe a different address."""
        config = _config()
        webobj = _webobj(email=NEW_EMAIL)
        hooks = _hooks()
        session = _session(verified_emails=[])

        _result, session_mgr = _run_post(
            config, webobj, hooks, session=session, actor_exists=True
        )

        session_mgr.try_claim_session.assert_called_once_with("sess-1")
        session_mgr.complete_claimed_session.assert_not_called()

    def test_losing_the_claim_race_is_an_expired_session_error(self):
        """A concurrent caller that loses the atomic claim gets the ordinary
        expired-session 400 and never reaches the existence probe."""
        config = _config()
        webobj = _webobj(email=NEW_EMAIL)
        hooks = _hooks()
        session = _session(verified_emails=[])

        existing_check = MagicMock()
        existing_check.get_from_creator.return_value = True

        session_mgr = MagicMock()
        session_mgr.get_session.return_value = session
        session_mgr.try_claim_session.return_value = None

        with (
            patch("actingweb.actor.Actor", return_value=existing_check),
            patch(
                "actingweb.oauth_session.get_oauth2_session_manager",
                return_value=session_mgr,
            ),
        ):
            result = OAuth2EmailHandler(webobj, config, hooks=hooks).post()

        assert result["status_code"] == 400
        assert "code" not in result
        existing_check.get_from_creator.assert_not_called()
        session_mgr.complete_claimed_session.assert_not_called()

    def test_no_hooks_fire(self):
        config = _config()
        webobj = _webobj(email=NEW_EMAIL)
        hooks = _hooks()
        session = _session(verified_emails=[])

        _run_post(config, webobj, hooks, session=session, actor_exists=True)

        assert hooks.calls == []

    def test_ui_mode_renders_409_template_at_200(self):
        """The integration renders template_values at 200 — the handler
        still records status 409 on the AWResponse, which is what the JSON
        branch and any direct caller sees."""
        config = _config(ui=True)
        webobj = _webobj(email=NEW_EMAIL, json_client=False)
        hooks = _hooks()
        session = _session(verified_emails=[])

        _run_post(config, webobj, hooks, session=session, actor_exists=True)

        assert webobj.response.status_code == 409
        assert webobj.response.template_values.get("status_code") == 409
        assert "already exists" in webobj.response.template_values.get("error", "")
        assert webobj.response.template_values.get("session_id") == ""


class TestDropdownExistingAddressStillReturningUser:
    def test_returns_200_same_actor(self):
        """A dropdown-selected address was verified by the provider in this
        session — this is a returning user, not the free-text refusal path."""
        config = _config()
        webobj = _webobj(email=EXISTING_EMAIL)
        hooks = _hooks()
        session = _session(verified_emails=[EXISTING_EMAIL])
        actor = _new_actor("actor-existing-1")

        result, _session_mgr = _run_post(
            config,
            webobj,
            hooks,
            session=session,
            actor_exists=True,  # irrelevant to this branch — not consulted
            complete_actor=actor,
        )

        assert result.get("status") == "success"
        assert result.get("actor_id") == "actor-existing-1"
        assert webobj.response.status_code == 200


class TestFreeTextNewAddressFiresOauthSuccess:
    def test_oauth_success_fires_with_session_data(self):
        config = _config()
        webobj = _webobj(email=NEW_EMAIL)
        hooks = _hooks(oauth_success_result=True)
        session = _session(
            verified_emails=[], access_token="raw-provider-at", provider="github"
        )
        actor = _new_actor()

        result, _session_mgr = _run_post(
            config, webobj, hooks, session=session, complete_actor=actor
        )

        assert result.get("status") == "success"
        oauth_success_calls = [c for c in hooks.calls if c[0] == "oauth_success"]
        assert len(oauth_success_calls) == 1
        kwargs = oauth_success_calls[0][1]
        assert kwargs["email"] == NEW_EMAIL
        assert kwargs["access_token"] == "raw-provider-at"
        assert kwargs["token_data"] == session["token_data"]
        assert kwargs["user_info"] == session["user_info"]

    def test_email_verified_false_visible_during_oauth_success(self):
        config = _config()
        webobj = _webobj(email=NEW_EMAIL)
        session = _session(verified_emails=[])
        actor = _new_actor()
        observed = {}

        hooks = MagicMock()

        def _exec(hook_name, actor_interface, **kwargs):
            if hook_name == "oauth_success":
                observed["email_verified"] = (
                    actor_interface.core_actor.store.email_verified
                )
            return True

        hooks.execute_lifecycle_hooks.side_effect = _exec

        _run_post(config, webobj, hooks, session=session, complete_actor=actor)

        assert observed["email_verified"] == "false"

    def test_no_handler_level_actor_created_call(self):
        """Phase 2: actor_created fires exactly once, inside Actor.create()
        itself — the handler must not fire it a second time. The handler
        instead threads self.hooks through to complete_session()."""
        config = _config()
        webobj = _webobj(email=NEW_EMAIL)
        hooks = _hooks()
        session = _session(verified_emails=[])
        actor = _new_actor()

        _result, session_mgr = _run_post(
            config, webobj, hooks, session=session, complete_actor=actor
        )

        assert not any(c[0] == "actor_created" for c in hooks.calls)
        _args, kwargs = session_mgr.complete_claimed_session.call_args
        assert kwargs["hooks"] is hooks

    def test_rejected_oauth_success_returns_403_and_writes_nothing(self):
        config = _config()
        webobj = _webobj(email=NEW_EMAIL)
        hooks = _hooks(oauth_success_result=False)
        session = _session(verified_emails=[])
        actor = _new_actor()

        with patch("actingweb.attribute.Attributes") as mock_attributes_cls:
            result, _session_mgr = _run_post(
                config, webobj, hooks, session=session, complete_actor=actor
            )
            mock_attributes_cls.assert_not_called()

        assert result["error"] is True
        assert result["code"] == "authentication_rejected"
        assert result["status_code"] == 403
        assert webobj.response.status_code == 403
        assert not any(c[0] == "email_verification_required" for c in hooks.calls)


class TestOauthTokenCookie:
    def test_cookie_is_httponly(self):
        config = _config()
        webobj = _webobj(email=EXISTING_EMAIL)
        hooks = _hooks()
        session = _session(verified_emails=[EXISTING_EMAIL])
        actor = _new_actor()

        _run_post(config, webobj, hooks, session=session, complete_actor=actor)

        cookies = {c["name"]: c for c in webobj.response.cookies}
        assert "oauth_token" in cookies
        assert cookies["oauth_token"]["httponly"] is True


class TestJsonVsTemplateErrorShape:
    def test_json_client_gets_json_body_no_template(self):
        config = _config()
        webobj_no_session = AWWebObj(
            url="https://test.example.com/oauth/email",
            params={},
            body=json.dumps({"session": "", "email": NEW_EMAIL}),
            headers={"Accept": "application/json"},
            cookies={},
        )
        handler = OAuth2EmailHandler(webobj_no_session, config, hooks=None)
        result = handler.post()

        assert result["error"] is True
        assert webobj_no_session.response.status_code == 400
        assert not webobj_no_session.response.template_values

    def test_browser_client_gets_template_values(self):
        config = _config()
        webobj_no_session = AWWebObj(
            url="https://test.example.com/oauth/email",
            params={},
            body=json.dumps({"session": "", "email": NEW_EMAIL}),
            headers={},
            cookies={},
        )
        handler = OAuth2EmailHandler(webobj_no_session, config, hooks=None)
        handler.post()

        assert webobj_no_session.response.template_values


class TestCorsAllowlist:
    def test_origin_outside_allowlist_is_not_reflected(self):
        config = _config(spa_cors_origins=["https://allowed.example.com"])
        webobj = _webobj(
            email=NEW_EMAIL, json_client=True, origin="https://evil.example.com"
        )
        hooks = _hooks()
        session = _session(verified_emails=[])

        _run_post(config, webobj, hooks, session=session, actor_exists=True)

        assert (
            webobj.response.headers["Access-Control-Allow-Origin"]
            == "https://allowed.example.com"
        )
