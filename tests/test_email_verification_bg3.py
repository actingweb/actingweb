"""BG3: the emailed link verifies by a confirmed POST, issues no session, and
links the provider account so a later sign-in lands in the verified actor.

Plan: thoughts/plans/2026-11-02-3-16-adoption-fault-followups.md, Phase 2.
"""

from __future__ import annotations

import time
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from actingweb import actor as actor_module
from actingweb.attribute import Attributes
from actingweb.aw_web_request import AWWebObj
from actingweb.constants import (
    ACTINGWEB_SYSTEM_ACTOR,
    EMAIL_VERIFY_TOKEN_INDEX_BUCKET,
)
from actingweb.handlers.oauth_email import OAuth2EmailHandler
from actingweb.interface import ActingWebApp
from actingweb.interface.actor_interface import ActorInterface
from actingweb.oauth2 import GitHubOAuth2Provider, OAuth2Authenticator


@pytest.fixture
def config() -> Any:
    cfg = ActingWebApp(
        aw_type="urn:actingweb:test:bg3",
        database="dynamodb",
        fqdn="test.example.com",
    ).get_config()
    cfg.unique_creator = False
    return cfg


def _index(config: Any, bucket: str = EMAIL_VERIFY_TOKEN_INDEX_BUCKET) -> Attributes:
    return Attributes(actor_id=ACTINGWEB_SYSTEM_ACTOR, bucket=bucket, config=config)


@pytest.fixture
def pending(config: Any) -> Any:
    token = f"bg3-{uuid.uuid4()}"
    creator = f"{uuid.uuid4()}@example.com"
    core = ActorInterface.create(
        creator=creator, config=config, auth_method="email_unverified"
    ).core_actor
    store = core.store
    assert store is not None
    store.email_verified = "false"
    store.email_verification_token = token
    store.email_verification_address = creator
    store.email_verification_created_at = str(int(time.time()))
    _index(config).set_attr(token, data=core.id)
    yield core, token
    _index(config).delete_attr(token)
    core.delete()


def _call(config: Any, token: str, method: str, json_client: bool = True) -> Any:
    webobj = AWWebObj(
        url=f"https://test.example.com/oauth/email?verify={token}",
        params={"verify": token},
        body="",
        headers={"Accept": "application/json"} if json_client else {},
        cookies={},
    )
    handler = OAuth2EmailHandler(webobj, config, hooks=None)
    result = handler.get() if method == "GET" else handler.post()
    return result, webobj


class TestConfirmPage:
    def test_a_get_changes_nothing(self, config: Any, pending: Any) -> None:
        core, token = pending
        result, _ = _call(config, token, "GET")
        assert result["status"] == "confirm_required"
        assert result["confirm"]["params"] == {"verify": token}
        again = actor_module.Actor(actor_id=core.id, config=config)
        assert again.store is not None and again.store.email_verified == "false"

    def test_a_browser_get_shows_the_confirm_form(
        self, config: Any, pending: Any
    ) -> None:
        _core, token = pending
        _result, webobj = _call(config, token, "GET", json_client=False)
        values = webobj.response.template_values
        assert values["status"] == "confirm" and values["verify_token"] == token


class TestConfirm:
    def test_the_post_verifies_and_issues_no_session(
        self, config: Any, pending: Any
    ) -> None:
        core, token = pending
        result, webobj = _call(config, token, "POST")
        assert result["status"] == "verified"
        assert "access_token" not in result and "refresh_token" not in result
        assert "oauth_token" not in (webobj.response.cookies or {})
        reloaded = actor_module.Actor(actor_id=core.id, config=config)
        assert reloaded.store is not None
        assert reloaded.store.email_verified == "true"
        assert _index(config).get_attr(token) is None  # consumed

    def test_a_fault_in_the_verification_leaves_the_link_usable(
        self, config: Any, pending: Any
    ) -> None:
        _core, token = pending
        with patch(
            "actingweb.oauth2.adopt_actor", return_value=None
        ):  # the adoption fails
            _call(config, token, "POST")
        assert _index(config).get_attr(token) is not None
        result, _ = _call(config, token, "POST")
        assert result["status"] == "verified"


class TestNoLink:
    def test_a_confirm_links_no_provider_account(
        self, config: Any, pending: Any
    ) -> None:
        """A victim who confirms an attacker's request verifies the address
        and gives the attacker's provider account nothing."""
        _core, token = pending
        _call(config, token, "POST")
        auth = OAuth2Authenticator(config, GitHubOAuth2Provider(config))
        with patch.object(GitHubOAuth2Provider, "get_primary_email", return_value=None):
            assert (
                auth.get_email_from_user_info(
                    {"id": 424242424, "login": "attacker"}, "tok", require_email=True
                )
                is None
            )


class TestVerificationEmailNamesTheAccount:
    def test_the_hook_gets_the_provider_and_account(self) -> None:
        from actingweb.handlers.oauth_email import _provider_account

        config = MagicMock()
        with patch("actingweb.oauth2.create_oauth2_authenticator") as factory:
            factory.return_value.provider.extract_identifier_from_user_info.return_value = "github:7"
            assert _provider_account(config, "github", {"id": 7}) == "github:7"
        assert _provider_account(config, "", {"id": 7}) is None
