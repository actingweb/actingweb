"""``prompt`` on the authorize URL (3.16): additive to the always-sent
``consent``, Google only."""

from urllib.parse import parse_qs, urlparse

from actingweb.config import Config
from actingweb.oauth2 import (
    AppleOAuth2Provider,
    GitHubOAuth2Provider,
    GoogleOAuth2Provider,
    OAuth2Authenticator,
)


def _url(provider_cls, **kwargs) -> dict[str, list[str]]:
    config = Config(database="dynamodb", fqdn="test.example.com", proto="https://")
    config.oauth = {"client_id": "cid", "client_secret": "csec"}
    provider = provider_cls(config)
    auth = OAuth2Authenticator(config, provider)
    return parse_qs(urlparse(auth.create_authorization_url(**kwargs)).query)


class TestAuthorizePrompt:
    def test_google_adds_select_account_before_consent(self) -> None:
        query = _url(GoogleOAuth2Provider, prompt="select_account")
        assert query["prompt"] == ["select_account consent"]
        assert query["access_type"] == ["offline"]

    def test_google_default_is_unchanged(self) -> None:
        assert _url(GoogleOAuth2Provider)["prompt"] == ["consent"]

    def test_github_drops_the_addition(self) -> None:
        assert _url(GitHubOAuth2Provider, prompt="select_account")["prompt"] == [
            "consent"
        ]

    def test_apple_drops_the_addition(self) -> None:
        # Apple's authorize URL needs signing material; the strategy method
        # is what create_authorization_url consults.
        apple = AppleOAuth2Provider.__new__(AppleOAuth2Provider)
        assert apple.authorize_prompt_params("select_account") == {}
