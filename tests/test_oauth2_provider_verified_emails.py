"""
Tests for the provider-level "verified emails" contract used by the OAuth2
callback's email-required branches (3.14.5).

``[]`` means "the provider was asked and vouches for nothing" (a legitimate
result — the free-text email form is the documented next step). ``None``
means "we could not ask" (a failed API call) and must not be treated the
same way, since that previously sent a fully-verified GitHub user straight
to the free-text form on a transient/scope failure.
"""

from unittest.mock import Mock, patch

from actingweb.config import Config
from actingweb.oauth2 import (
    AppleOAuth2Provider,
    GitHubOAuth2Provider,
    GoogleOAuth2Provider,
    OAuth2Authenticator,
    OAuth2Provider,
    _get_github_verified_emails,
)


def _github_response(status_code: int, payload=None):
    resp = Mock()
    resp.status_code = status_code
    if payload is not None:
        resp.json.return_value = payload
    return resp


class TestGetGithubVerifiedEmails:
    def test_two_verified_one_unverified_returns_lowercased_verified(self):
        payload = [
            {"email": "A@Example.com", "verified": True, "primary": True},
            {"email": "b@example.com", "verified": True, "primary": False},
            {"email": "c@example.com", "verified": False, "primary": False},
        ]
        with patch(
            "actingweb.oauth2.requests.get",
            return_value=_github_response(200, payload),
        ):
            result = _get_github_verified_emails("tok")
        assert result == ["a@example.com", "b@example.com"]

    def test_200_with_none_verified_returns_empty_list(self):
        payload = [{"email": "a@example.com", "verified": False, "primary": True}]
        with patch(
            "actingweb.oauth2.requests.get",
            return_value=_github_response(200, payload),
        ):
            result = _get_github_verified_emails("tok")
        assert result == []

    def test_200_empty_list_returns_empty_list(self):
        with patch(
            "actingweb.oauth2.requests.get",
            return_value=_github_response(200, []),
        ):
            result = _get_github_verified_emails("tok")
        assert result == []

    def test_404_returns_none(self):
        with patch(
            "actingweb.oauth2.requests.get",
            return_value=_github_response(404),
        ):
            result = _get_github_verified_emails("tok")
        assert result is None

    def test_500_returns_none(self):
        with patch(
            "actingweb.oauth2.requests.get",
            return_value=_github_response(500),
        ):
            result = _get_github_verified_emails("tok")
        assert result is None

    def test_request_exception_returns_none(self):
        with patch("actingweb.oauth2.requests.get", side_effect=Exception("boom")):
            result = _get_github_verified_emails("tok")
        assert result is None

    def test_no_access_token_returns_none(self):
        assert _get_github_verified_emails("") is None


class TestProviderGetVerifiedEmailsDefault:
    def test_google_default_is_empty_list(self):
        config = Mock(spec=Config)
        config.oauth = {}
        config.proto = "https://"
        config.fqdn = "test.example.com"
        provider = GoogleOAuth2Provider(config)
        assert provider.get_verified_emails("tok") == []

    def test_apple_default_is_empty_list(self):
        config = Mock(spec=Config)
        config.oauth = {}
        config.proto = "https://"
        config.fqdn = "test.example.com"
        provider = AppleOAuth2Provider(config)
        assert provider.get_verified_emails("tok") == []

    def test_base_class_default_is_empty_list(self):
        provider = OAuth2Provider(
            "generic",
            {
                "client_id": "c",
                "client_secret": "s",
                "auth_uri": "https://p/auth",
                "token_uri": "https://p/token",
                "userinfo_uri": "https://p/userinfo",
                "scope": "openid email",
                "redirect_uri": "https://test.example.com/oauth/callback",
            },
        )
        assert provider.get_verified_emails("tok") == []

    def test_github_delegates_to_module_level_helper(self):
        config = Mock(spec=Config)
        config.oauth = {}
        config.proto = "https://"
        config.fqdn = "test.example.com"
        provider = GitHubOAuth2Provider(config)
        with patch(
            "actingweb.oauth2._get_github_verified_emails",
            return_value=["a@example.com"],
        ) as mock_helper:
            result = provider.get_verified_emails("tok")
        mock_helper.assert_called_once_with("tok")
        assert result == ["a@example.com"]


class TestAuthenticatorGetGithubVerifiedEmailsShim:
    def test_delegates_to_provider(self):
        config = Mock(spec=Config)
        config.oauth = {}
        config.proto = "https://"
        config.fqdn = "test.example.com"
        provider = GitHubOAuth2Provider(config)
        authenticator = OAuth2Authenticator(config, provider)

        with patch.object(
            provider, "get_verified_emails", return_value=None
        ) as mock_method:
            result = authenticator.get_github_verified_emails("tok")
        mock_method.assert_called_once_with("tok")
        assert result is None
