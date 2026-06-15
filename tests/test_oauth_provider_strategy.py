"""
Unit tests for the OAuth2Provider strategy methods (Phase 1 refactor).

These verify that provider-specific behavior lives on the provider subclasses
rather than as ``provider.name == ...`` branches in ``OAuth2Authenticator``.
"""

from actingweb.config import Config
from actingweb.oauth2 import (
    GitHubOAuth2Provider,
    GoogleOAuth2Provider,
    OAuth2Provider,
)


def _config() -> Config:
    return Config(fqdn="test.example.com", database="dynamodb")


class TestTokenRequestHeaders:
    def test_base_headers(self) -> None:
        provider = OAuth2Provider("generic", {"client_id": "c", "client_secret": "s"})
        headers = provider.token_request_headers()
        assert headers["Content-Type"] == "application/x-www-form-urlencoded"
        assert headers["Accept"] == "application/json"
        assert "User-Agent" not in headers

    def test_github_adds_user_agent(self) -> None:
        provider = GitHubOAuth2Provider(_config())
        headers = provider.token_request_headers()
        assert headers["User-Agent"] == "ActingWeb-OAuth2-Client"

    def test_google_no_user_agent(self) -> None:
        provider = GoogleOAuth2Provider(_config())
        assert "User-Agent" not in provider.token_request_headers()


class TestUserinfoRequestHeaders:
    def test_base_includes_bearer(self) -> None:
        provider = OAuth2Provider("generic", {"client_id": "c", "client_secret": "s"})
        headers = provider.userinfo_request_headers("tok123")
        assert headers["Authorization"] == "Bearer tok123"
        assert "User-Agent" not in headers

    def test_github_adds_user_agent(self) -> None:
        provider = GitHubOAuth2Provider(_config())
        headers = provider.userinfo_request_headers("tok123")
        assert headers["Authorization"] == "Bearer tok123"
        assert headers["User-Agent"] == "ActingWeb-OAuth2-Client"


class TestRefreshSupport:
    def test_base_supports_refresh(self) -> None:
        provider = OAuth2Provider("generic", {})
        assert provider.supports_refresh_tokens() is True

    def test_google_supports_refresh(self) -> None:
        assert GoogleOAuth2Provider(_config()).supports_refresh_tokens() is True

    def test_github_no_refresh(self) -> None:
        assert GitHubOAuth2Provider(_config()).supports_refresh_tokens() is False


class TestRevokeSupport:
    def test_revoke_follows_revocation_uri(self) -> None:
        # Google has a revocation_uri
        assert GoogleOAuth2Provider(_config()).supports_revoke() is True

    def test_github_no_revoke(self) -> None:
        assert GitHubOAuth2Provider(_config()).supports_revoke() is False


class TestAuthorizeExtraParams:
    def test_google_login_hint(self) -> None:
        provider = GoogleOAuth2Provider(_config())
        assert provider.authorize_extra_params("a@b.com") == {"login_hint": "a@b.com"}
        assert provider.authorize_extra_params("") == {}

    def test_github_no_login_hint(self) -> None:
        provider = GitHubOAuth2Provider(_config())
        assert provider.authorize_extra_params("a@b.com") == {}


class TestMakeClientSecret:
    def test_returns_static_secret(self) -> None:
        prov_cfg = {"client_id": "c", "client_secret": "secret-value"}
        provider = GoogleOAuth2Provider(_config(), provider_config=prov_cfg)
        assert provider.make_client_secret() == "secret-value"


class TestExtractIdentifierFromUserInfo:
    def test_google_sub(self) -> None:
        provider = GoogleOAuth2Provider(_config())
        assert (
            provider.extract_identifier_from_user_info({"sub": "123"}) == "google:123"
        )

    def test_google_falls_back_to_preferred_username(self) -> None:
        provider = GoogleOAuth2Provider(_config())
        result = provider.extract_identifier_from_user_info(
            {"preferred_username": "BobUser"}
        )
        assert result == "google:bobuser"

    def test_google_no_identifier(self) -> None:
        provider = GoogleOAuth2Provider(_config())
        assert provider.extract_identifier_from_user_info({}) is None

    def test_github_id(self) -> None:
        provider = GitHubOAuth2Provider(_config())
        assert provider.extract_identifier_from_user_info({"id": 99}) == "github:99"

    def test_github_login_fallback(self) -> None:
        provider = GitHubOAuth2Provider(_config())
        result = provider.extract_identifier_from_user_info({"login": "Octocat"})
        assert result == "github:octocat"

    def test_github_no_identifier(self) -> None:
        provider = GitHubOAuth2Provider(_config())
        assert provider.extract_identifier_from_user_info({}) is None


class TestExtractUserInfoFromTokenResponse:
    def test_base_returns_none(self) -> None:
        provider = OAuth2Provider("generic", {})
        assert provider.extract_user_info_from_token_response({"id_token": "x"}) is None


class TestDiscoveryExtras:
    def test_base_empty(self) -> None:
        assert OAuth2Provider("generic", {}).discovery_extras() == {}

    def test_google_jwks(self) -> None:
        extras = GoogleOAuth2Provider(_config()).discovery_extras()
        assert extras["jwks_uri"] == "https://www.googleapis.com/oauth2/v3/certs"
        assert extras["id_token_signing_alg_values_supported"] == ["RS256"]
        assert "refresh_token" in extras["grant_types_supported"]

    def test_github_empty(self) -> None:
        assert GitHubOAuth2Provider(_config()).discovery_extras() == {}


class TestStoreProviderIdentity:
    class _Store:
        pass

    def test_google_writes_oauth_sub(self) -> None:
        store = self._Store()
        GoogleOAuth2Provider(_config()).store_provider_identity(store, "google:abc")
        assert store.oauth_sub == "abc"  # type: ignore[attr-defined]

    def test_github_writes_oauth_github_id(self) -> None:
        store = self._Store()
        GitHubOAuth2Provider(_config()).store_provider_identity(store, "github:42")
        assert store.oauth_github_id == "42"  # type: ignore[attr-defined]

    def test_base_noop(self) -> None:
        store = self._Store()
        OAuth2Provider("generic", {}).store_provider_identity(store, "x:y")
        assert not hasattr(store, "oauth_sub")


class TestDisplayName:
    def test_google(self) -> None:
        assert GoogleOAuth2Provider(_config()).display_name == "Google"

    def test_github(self) -> None:
        assert GitHubOAuth2Provider(_config()).display_name == "GitHub"

    def test_unknown(self) -> None:
        assert OAuth2Provider("custom", {}).display_name == "Custom"
