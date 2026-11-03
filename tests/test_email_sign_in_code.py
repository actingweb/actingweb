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

    def test_a_new_challenge_replaces_the_previous_one(self, config: Any) -> None:
        actor = _verified(config)
        first, first_code = email_sign_in.start_challenge(config, aid(actor), "a@x.com")
        second, second_code = email_sign_in.start_challenge(
            config, aid(actor), "a@x.com"
        )
        assert email_sign_in.redeem(config, first, first_code) is None
        assert email_sign_in.redeem(config, second, second_code) == aid(actor)

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
        assert email_sign_in.BINDING_COOKIE in cookies
        assert cookies[email_sign_in.BINDING_COOKIE]["httponly"] is True
