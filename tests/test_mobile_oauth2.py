"""
Tests for mobile OAuth2 support (authorization code exchange via /oauth/spa/token).

Tests cover:
- Provider redirect_uri override from config
- Provider name variant matching (google-mobile, github-mobile)
- exchange_code_for_token redirect_uri parameter
- Full authorization_code grant type flow in SPA handler
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from actingweb.config import Config
from actingweb.oauth2 import (
    GitHubOAuth2Provider,
    GoogleOAuth2Provider,
    OAuth2Authenticator,
    create_oauth2_authenticator,
)


class TestProviderRedirectUriOverride:
    """Test that providers respect redirect_uri from provider config."""

    def test_google_provider_uses_default_redirect_uri(self) -> None:
        config = Config(fqdn="test.example.com", database="dynamodb")
        provider = GoogleOAuth2Provider(config)
        # When no provider_config is given, uses hardcoded {proto}{fqdn}/oauth/callback
        assert provider.redirect_uri == f"{config.proto}{config.fqdn}/oauth/callback"

    def test_google_provider_respects_redirect_uri_from_config(self) -> None:
        config = Config(fqdn="test.example.com", database="dynamodb")
        prov_cfg = {
            "client_id": "cid",
            "client_secret": "csec",
            "redirect_uri": "io.actingweb.memory://callback",
        }
        provider = GoogleOAuth2Provider(config, provider_config=prov_cfg)
        assert provider.redirect_uri == "io.actingweb.memory://callback"

    def test_github_provider_uses_default_redirect_uri(self) -> None:
        config = Config(fqdn="test.example.com", database="dynamodb")
        provider = GitHubOAuth2Provider(config)
        assert provider.redirect_uri == f"{config.proto}{config.fqdn}/oauth/callback"

    def test_github_provider_respects_redirect_uri_from_config(self) -> None:
        config = Config(fqdn="test.example.com", database="dynamodb")
        prov_cfg = {
            "client_id": "cid",
            "client_secret": "csec",
            "redirect_uri": "io.actingweb.memory://callback",
        }
        provider = GitHubOAuth2Provider(config, provider_config=prov_cfg)
        assert provider.redirect_uri == "io.actingweb.memory://callback"

    def test_google_provider_falls_back_when_redirect_uri_empty(self) -> None:
        config = Config(fqdn="test.example.com", database="dynamodb")
        prov_cfg = {
            "client_id": "cid",
            "client_secret": "csec",
            "redirect_uri": "",
        }
        provider = GoogleOAuth2Provider(config, provider_config=prov_cfg)
        assert provider.redirect_uri == f"{config.proto}{config.fqdn}/oauth/callback"


class TestProviderNameVariants:
    """Test that create_oauth2_authenticator handles provider name variants."""

    def _make_config(self, provider_name: str) -> Config:
        config = Config(fqdn="test.example.com", database="dynamodb")
        config.oauth_providers = {
            provider_name: {
                "client_id": "test_cid",
                "client_secret": "test_csec",
            }
        }
        return config

    def test_google_mobile_creates_google_provider(self) -> None:
        config = self._make_config("google-mobile")
        auth = create_oauth2_authenticator(config, "google-mobile")
        assert auth.provider.name == "google"

    def test_github_mobile_creates_github_provider(self) -> None:
        config = self._make_config("github-mobile")
        auth = create_oauth2_authenticator(config, "github-mobile")
        assert auth.provider.name == "github"

    def test_google_exact_still_works(self) -> None:
        config = self._make_config("google")
        auth = create_oauth2_authenticator(config, "google")
        assert auth.provider.name == "google"

    def test_github_exact_still_works(self) -> None:
        config = self._make_config("github")
        auth = create_oauth2_authenticator(config, "github")
        assert auth.provider.name == "github"

    def test_google_tablet_creates_google_provider(self) -> None:
        config = self._make_config("google-tablet")
        auth = create_oauth2_authenticator(config, "google-tablet")
        assert auth.provider.name == "google"

    def test_apple_creates_apple_provider(self) -> None:
        from actingweb.oauth2 import AppleOAuth2Provider

        config = self._make_config("apple")
        auth = create_oauth2_authenticator(config, "apple")
        assert isinstance(auth.provider, AppleOAuth2Provider)
        assert auth.provider.name == "apple"

    def test_apple_mobile_creates_apple_provider(self) -> None:
        from actingweb.oauth2 import AppleOAuth2Provider

        config = self._make_config("apple-mobile")
        auth = create_oauth2_authenticator(config, "apple-mobile")
        assert isinstance(auth.provider, AppleOAuth2Provider)


class TestExchangeCodeRedirectUriOverride:
    """Test that exchange_code_for_token accepts redirect_uri override."""

    def test_redirect_uri_override_used_in_token_request(self) -> None:
        config = Config(fqdn="test.example.com", database="dynamodb")
        config.oauth = {"client_id": "cid", "client_secret": "csec"}
        authenticator = OAuth2Authenticator(config, GoogleOAuth2Provider(config))

        with patch("actingweb.oauth2.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "access_token": "tok",
                "token_type": "Bearer",
            }
            mock_response.text = json.dumps(
                {"access_token": "tok", "token_type": "Bearer"}
            )
            mock_post.return_value = mock_response

            authenticator.exchange_code_for_token(
                code="test_code",
                redirect_uri="io.actingweb.memory://callback",
            )

            # Verify the redirect_uri was passed in the request body
            call_kwargs = mock_post.call_args
            body_str = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data", "")
            assert (
                "io.actingweb.memory%3A%2F%2Fcallback" in body_str
                or "io.actingweb.memory://callback" in body_str
            )

    def test_default_redirect_uri_when_no_override(self) -> None:
        config = Config(fqdn="test.example.com", database="dynamodb")
        config.oauth = {"client_id": "cid", "client_secret": "csec"}
        authenticator = OAuth2Authenticator(config, GoogleOAuth2Provider(config))

        with patch("actingweb.oauth2.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "access_token": "tok",
                "token_type": "Bearer",
            }
            mock_response.text = json.dumps(
                {"access_token": "tok", "token_type": "Bearer"}
            )
            mock_post.return_value = mock_response

            authenticator.exchange_code_for_token(code="test_code")

            call_kwargs = mock_post.call_args
            body_str = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data", "")
            assert "test.example.com" in body_str


class TestAuthorizationCodeGrant:
    """Test the _handle_authorization_code method in OAuth2SPAHandler."""

    @pytest.fixture
    def mock_config(self) -> MagicMock:
        config = MagicMock()
        config.proto = "https://"
        config.fqdn = "test.example.com"
        config.oauth = {"client_id": "cid", "client_secret": "csec"}
        config.oauth_providers = {
            "github-mobile": {
                "client_id": "gh_mob_cid",
                "client_secret": "gh_mob_csec",
                "redirect_uri": "io.actingweb.memory://callback",
            }
        }
        config.oauth2_provider = "google"
        config.new_token = MagicMock(return_value="spa-access-token-123")
        config.force_email_prop_as_creator = False
        config.devtest = False
        config.service_registry = None
        return config

    @pytest.fixture
    def mock_webobj(self) -> MagicMock:
        webobj = MagicMock()
        webobj.request = MagicMock()
        webobj.request.headers = {"Accept": "application/json"}
        webobj.request.cookies = {}
        webobj.request.get = MagicMock(return_value="")
        webobj.response = MagicMock()
        webobj.response.headers = {}
        webobj.response._cookies = []
        webobj.response.set_status = MagicMock()
        webobj.response.write = MagicMock()
        webobj.response.set_cookie = MagicMock()
        return webobj

    def test_missing_code_returns_400(
        self, mock_config: MagicMock, mock_webobj: MagicMock
    ) -> None:
        from actingweb.handlers.oauth2_spa import OAuth2SPAHandler

        handler = OAuth2SPAHandler(mock_webobj, mock_config)
        result = handler._handle_authorization_code(
            {"grant_type": "authorization_code"}, "json"
        )
        assert result.get("error") is True
        assert result.get("status_code") == 400

    @patch("actingweb.oauth2.requests.post")
    @patch("actingweb.oauth2.requests.get")
    def test_successful_authorization_code_exchange(
        self,
        mock_get: MagicMock,
        mock_post: MagicMock,
        mock_config: MagicMock,
        mock_webobj: MagicMock,
    ) -> None:
        from actingweb.handlers.oauth2_spa import OAuth2SPAHandler

        # Mock token exchange response
        token_response = MagicMock()
        token_response.status_code = 200
        token_response.json.return_value = {
            "access_token": "provider-access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        token_response.text = json.dumps(token_response.json.return_value)
        mock_post.return_value = token_response

        # Mock userinfo response
        userinfo_response = MagicMock()
        userinfo_response.status_code = 200
        userinfo_response.json.return_value = {
            "id": 12345,
            "login": "testuser",
            "email": "test@example.com",
        }
        mock_get.return_value = userinfo_response

        # Mock actor lookup/creation
        with (
            patch("actingweb.actor.Actor") as mock_actor_cls,
            patch(
                "actingweb.oauth_session.get_oauth2_session_manager"
            ) as mock_session_mgr_factory,
        ):
            # Setup mock for existing actor check (also used as the actor instance)
            mock_existing = MagicMock()
            mock_existing.id = "actor-123"
            mock_existing.store = MagicMock()
            mock_existing.creator = "test@example.com"
            mock_existing.get_from_creator.return_value = True
            mock_actor_cls.return_value = mock_existing

            # Setup session manager
            mock_session_mgr = MagicMock()
            mock_session_mgr.create_refresh_token.return_value = "spa-refresh-token"
            mock_session_mgr_factory.return_value = mock_session_mgr

            handler = OAuth2SPAHandler(mock_webobj, mock_config, hooks=None)
            result = handler._handle_authorization_code(
                {
                    "grant_type": "authorization_code",
                    "code": "test-auth-code",
                    "provider": "github-mobile",
                    "redirect_uri": "io.actingweb.memory://callback",
                    "code_verifier": "test-pkce-verifier",
                    "token_delivery": "json",
                },
                "json",
            )

            assert result["success"] is True
            assert result["actor_id"] == "actor-123"
            assert result["email"] == "test@example.com"
            assert result["access_token"] == "spa-access-token-123"
            assert result["refresh_token"] == "spa-refresh-token"
            assert result["token_type"] == "Bearer"
            assert "expires_in" in result
            assert "expires_at" in result

    @patch("actingweb.oauth2.requests.post")
    def test_failed_token_exchange_returns_401(
        self,
        mock_post: MagicMock,
        mock_config: MagicMock,
        mock_webobj: MagicMock,
    ) -> None:
        from actingweb.handlers.oauth2_spa import OAuth2SPAHandler

        # Mock failed token exchange
        token_response = MagicMock()
        token_response.status_code = 400
        token_response.text = "invalid_grant"
        mock_post.return_value = token_response

        handler = OAuth2SPAHandler(mock_webobj, mock_config, hooks=None)
        result = handler._handle_authorization_code(
            {
                "code": "bad-code",
                "provider": "github-mobile",
                "redirect_uri": "io.actingweb.memory://callback",
                "code_verifier": "test-pkce-verifier",
            },
            "json",
        )

        assert result.get("success") is not True
        assert result.get("status_code") == 401
        assert "token exchange" in result.get("message", "").lower()

    def test_disabled_provider_returns_400(
        self, mock_config: MagicMock, mock_webobj: MagicMock
    ) -> None:
        from actingweb.handlers.oauth2_spa import OAuth2SPAHandler

        # Provider with no credentials
        mock_config.oauth_providers = {
            "github-mobile": {"client_id": "", "client_secret": ""}
        }
        mock_config.oauth = {"client_id": "", "client_secret": ""}

        handler = OAuth2SPAHandler(mock_webobj, mock_config, hooks=None)
        result = handler._handle_authorization_code(
            {
                "code": "test-code",
                "provider": "github-mobile",
                "code_verifier": "test-pkce-verifier",
            },
            "json",
        )

        assert result.get("success") is not True

    def test_unknown_provider_returns_400(
        self, mock_config: MagicMock, mock_webobj: MagicMock
    ) -> None:
        from actingweb.handlers.oauth2_spa import OAuth2SPAHandler

        handler = OAuth2SPAHandler(mock_webobj, mock_config, hooks=None)
        result = handler._handle_authorization_code(
            {
                "code": "test-code",
                "provider": "unknown-provider",
            },
            "json",
        )

        assert result.get("error") is True
        assert result.get("status_code") == 400
        assert "Unknown OAuth provider" in result.get("message", "")

    def test_invalid_token_delivery_returns_400(
        self, mock_config: MagicMock, mock_webobj: MagicMock
    ) -> None:
        from actingweb.handlers.oauth2_spa import OAuth2SPAHandler

        mock_webobj.request.body = json.dumps(
            {
                "grant_type": "authorization_code",
                "code": "test-code",
                "provider": "github-mobile",
                "token_delivery": "invalid",
            }
        ).encode("utf-8")

        handler = OAuth2SPAHandler(mock_webobj, mock_config, hooks=None)
        result = handler._handle_token()

        assert result.get("error") is True
        assert result.get("status_code") == 400
        assert "Invalid token_delivery" in result.get("message", "")

    @patch("actingweb.oauth2.requests.post")
    @patch("actingweb.oauth2.requests.get")
    def test_cookie_token_delivery(
        self,
        mock_get: MagicMock,
        mock_post: MagicMock,
        mock_config: MagicMock,
        mock_webobj: MagicMock,
    ) -> None:
        from actingweb.handlers.oauth2_spa import OAuth2SPAHandler

        # Mock token exchange response
        token_response = MagicMock()
        token_response.status_code = 200
        token_response.json.return_value = {
            "access_token": "provider-access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        token_response.text = json.dumps(token_response.json.return_value)
        mock_post.return_value = token_response

        # Mock userinfo response
        userinfo_response = MagicMock()
        userinfo_response.status_code = 200
        userinfo_response.json.return_value = {
            "id": 12345,
            "login": "testuser",
            "email": "test@example.com",
        }
        mock_get.return_value = userinfo_response

        with (
            patch(
                "actingweb.oauth2.OAuth2Authenticator.lookup_or_create_actor_by_identifier"
            ) as mock_lookup,
            patch("actingweb.actor.Actor") as mock_actor_cls,
            patch(
                "actingweb.oauth_session.get_oauth2_session_manager"
            ) as mock_session_mgr_factory,
        ):
            mock_actor = MagicMock()
            mock_actor.id = "actor-123"
            mock_actor.store = MagicMock()
            mock_actor.creator = "test@example.com"
            mock_lookup.return_value = mock_actor

            mock_existing = MagicMock()
            mock_existing.get_from_creator.return_value = True
            mock_actor_cls.return_value = mock_existing

            mock_session_mgr = MagicMock()
            mock_session_mgr.create_refresh_token.return_value = "spa-refresh-token"
            mock_session_mgr_factory.return_value = mock_session_mgr

            handler = OAuth2SPAHandler(mock_webobj, mock_config, hooks=None)
            result = handler._handle_authorization_code(
                {
                    "grant_type": "authorization_code",
                    "code": "test-auth-code",
                    "provider": "github-mobile",
                    "redirect_uri": "io.actingweb.memory://callback",
                    "code_verifier": "test-pkce-verifier",
                },
                "cookie",
            )

            assert result["success"] is True
            assert result["token_delivery"] == "cookie"
            assert "access_token" not in result
            assert "refresh_token" not in result

    @patch("actingweb.oauth2.requests.post")
    @patch("actingweb.oauth2.requests.get")
    def test_hybrid_token_delivery(
        self,
        mock_get: MagicMock,
        mock_post: MagicMock,
        mock_config: MagicMock,
        mock_webobj: MagicMock,
    ) -> None:
        from actingweb.handlers.oauth2_spa import OAuth2SPAHandler

        # Mock token exchange response
        token_response = MagicMock()
        token_response.status_code = 200
        token_response.json.return_value = {
            "access_token": "provider-access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        token_response.text = json.dumps(token_response.json.return_value)
        mock_post.return_value = token_response

        # Mock userinfo response
        userinfo_response = MagicMock()
        userinfo_response.status_code = 200
        userinfo_response.json.return_value = {
            "id": 12345,
            "login": "testuser",
            "email": "test@example.com",
        }
        mock_get.return_value = userinfo_response

        with (
            patch(
                "actingweb.oauth2.OAuth2Authenticator.lookup_or_create_actor_by_identifier"
            ) as mock_lookup,
            patch("actingweb.actor.Actor") as mock_actor_cls,
            patch(
                "actingweb.oauth_session.get_oauth2_session_manager"
            ) as mock_session_mgr_factory,
        ):
            mock_actor = MagicMock()
            mock_actor.id = "actor-123"
            mock_actor.store = MagicMock()
            mock_actor.creator = "test@example.com"
            mock_lookup.return_value = mock_actor

            mock_existing = MagicMock()
            mock_existing.get_from_creator.return_value = True
            mock_actor_cls.return_value = mock_existing

            mock_session_mgr = MagicMock()
            mock_session_mgr.create_refresh_token.return_value = "spa-refresh-token"
            mock_session_mgr_factory.return_value = mock_session_mgr

            handler = OAuth2SPAHandler(mock_webobj, mock_config, hooks=None)
            result = handler._handle_authorization_code(
                {
                    "grant_type": "authorization_code",
                    "code": "test-auth-code",
                    "provider": "github-mobile",
                    "redirect_uri": "io.actingweb.memory://callback",
                    "code_verifier": "test-pkce-verifier",
                },
                "hybrid",
            )

            assert result["success"] is True
            assert result["token_delivery"] == "hybrid"
            assert "access_token" in result
            assert result["token_type"] == "Bearer"
            assert "refresh_token" not in result
