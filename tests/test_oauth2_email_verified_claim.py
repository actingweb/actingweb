"""E1: a provider's email is an identity or a stored address only when the
provider vouches for it.

Plan: thoughts/plans/2026-11-02-3-16-adoption-fault-followups.md, Phase 2.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from actingweb.oauth2 import (
    AppleOAuth2Provider,
    GitHubOAuth2Provider,
    GoogleOAuth2Provider,
    OAuth2Authenticator,
    _proven_email,
    drop_unverified_email,
    verified_email_of,
)
from tests._adoption_helpers import make_config


@pytest.fixture
def config() -> Any:
    return make_config()


def _gh_emails(entries: list[dict[str, Any]] | None, status: int = 200) -> Any:
    response = MagicMock()
    response.status_code = status
    response.json.return_value = entries
    return response


class TestClaims:
    @pytest.mark.parametrize(
        "claims,expected",
        [
            ({"verified_email": True}, True),  # Google web userinfo (v2)
            ({"email_verified": True}, True),  # Google id_token
            ({"email_verified": "true"}, True),
            ({"verified_email": False}, False),
            ({"email_verified": "false"}, False),
            ({"email_verified": "yes"}, False),  # truthy, not true
            ({}, False),  # absent counts as unverified
        ],
    )
    def test_google(self, config: Any, claims: dict[str, Any], expected: bool) -> None:
        provider = GoogleOAuth2Provider(config)
        assert provider.email_is_verified({"email": "a@x.com", **claims}) is expected

    @pytest.mark.parametrize(
        "claims,expected",
        [
            ({"email_verified": "true"}, True),
            ({"email_verified": True}, True),
            ({"email_verified": "false"}, False),
            ({}, False),
        ],
    )
    def test_apple(self, config: Any, claims: dict[str, Any], expected: bool) -> None:
        provider = AppleOAuth2Provider(config)
        assert provider.email_is_verified({"email": "a@x.com", **claims}) is expected

    def test_github_checks_the_verified_list(self, config: Any) -> None:
        provider = GitHubOAuth2Provider(config)
        entries = [
            {"email": "in@x.com", "verified": True, "primary": True},
            {"email": "not@x.com", "verified": False, "primary": False},
        ]
        with patch(
            "actingweb.oauth2.requests.get", return_value=_gh_emails(entries)
        ) as get:
            assert provider.email_is_verified({"email": "In@x.com"}, "tok")
            assert not provider.email_is_verified({"email": "not@x.com"}, "tok")
            assert not provider.email_is_verified({"email": "other@x.com"}, "tok")
        assert get.call_count == 1  # one /user/emails per token

    def test_github_without_a_token_or_on_a_failed_call_is_unverified(
        self, config: Any
    ) -> None:
        provider = GitHubOAuth2Provider(config)
        assert not provider.email_is_verified({"email": "in@x.com"})
        with patch(
            "actingweb.oauth2.requests.get", return_value=_gh_emails(None, status=500)
        ):
            assert not provider.email_is_verified({"email": "in@x.com"}, "tok2")


class TestDrop:
    def test_an_unverified_address_is_moved_aside(self, config: Any) -> None:
        info = drop_unverified_email(
            GoogleOAuth2Provider(config),
            {"email": "Victim@X.com", "verified_email": False, "sub": "1"},
        )
        assert info is not None
        assert "email" not in info and info["unverified_email"] == "victim@x.com"
        assert verified_email_of(info) is None

    def test_a_verified_address_is_marked(self, config: Any) -> None:
        provider = GitHubOAuth2Provider(config)
        with patch(
            "actingweb.oauth2.requests.get",
            return_value=_gh_emails([{"email": "me@x.com", "verified": True}]),
        ):
            info = drop_unverified_email(provider, {"email": "me@x.com"}, "tok3")
        assert info is not None and info["email_verified"] is True
        # A later check with no token still sees it.
        assert provider.email_is_verified(info)
        assert verified_email_of(info) == "me@x.com"


class TestIdentity:
    def _auth(self, config: Any, provider: Any) -> OAuth2Authenticator:
        return OAuth2Authenticator(config, provider)

    def test_an_unverified_google_address_is_not_the_identity(
        self, config: Any
    ) -> None:
        """The regression: before 3.16 it was."""
        auth = self._auth(config, GoogleOAuth2Provider(config))
        identifier = auth.get_email_from_user_info(
            {"email": "victim@example.com", "verified_email": False, "sub": "g1"}
        )
        assert identifier == "google:g1"

    def test_with_require_email_it_falls_through_to_the_form(self, config: Any) -> None:
        auth = self._auth(config, GoogleOAuth2Provider(config))
        assert (
            auth.get_email_from_user_info(
                {"email": "victim@example.com", "sub": "g1"}, require_email=True
            )
            is None
        )

    def test_a_verified_address_is(self, config: Any) -> None:
        auth = self._auth(config, GoogleOAuth2Provider(config))
        assert (
            auth.get_email_from_user_info(
                {"email": "Me@Example.com", "verified_email": True, "sub": "g1"}
            )
            == "me@example.com"
        )


class TestStoredAddress:
    def test_an_unverified_address_is_never_proven(self) -> None:
        assert _proven_email("google:1", {"email": "victim@example.com"}) is None
        assert (
            _proven_email(
                "google:1", {"email": "victim@example.com", "verified_email": False}
            )
            is None
        )

    def test_a_marked_one_is(self) -> None:
        assert (
            _proven_email("google:1", {"email": "Me@X.com", "email_verified": True})
            == "me@x.com"
        )

    def test_the_create_does_not_store_an_unverified_address(self, config: Any) -> None:
        from actingweb.oauth2 import _create_actor_for_identifier

        created = _create_actor_for_identifier(
            config,
            GoogleOAuth2Provider(config),
            "google:unverified-1",
            {"email": "victim@example.com", "sub": "unverified-1"},
            None,
        )
        assert created.store is not None and created.store.email is None
        created.delete()

    def test_the_seeding_does_not_seed_one(self, config: Any) -> None:
        from actingweb.oauth2 import _seed_missing_email
        from tests._adoption_helpers import create_core_actor, istore

        owner = create_core_actor(config, "google:seed-1", auth_method="google_oauth2")
        istore(owner).email = None
        _seed_missing_email(owner, istore(owner), {"email": "victim@example.com"})
        assert istore(owner).email is None
        owner.delete()


class TestAppleFormPost:
    def test_the_posted_address_is_never_verified(self) -> None:
        import json

        from actingweb.handlers.oauth2_callback import OAuth2CallbackHandler

        handler = OAuth2CallbackHandler.__new__(OAuth2CallbackHandler)
        handler._pending_apple_user_json = json.dumps({"email": "Posted@X.com"})
        merged = handler._merge_apple_user_payload(
            {"sub": "a1", "email_verified": "true"}
        )
        assert merged is not None
        assert "email" not in merged and merged["unverified_email"] == "posted@x.com"
