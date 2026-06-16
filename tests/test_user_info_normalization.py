"""Tests for normalize_user_info (consistent oauth_success user_info shape)."""

from actingweb.handlers.oauth2_utils import normalize_user_info


class TestNormalizeUserInfo:
    def test_apple_first_last_name(self) -> None:
        out = normalize_user_info(
            "apple-mobile",
            {"firstName": "Jane", "lastName": "Doe", "sub": "a", "email": "j@x.com"},
        )
        assert out["given_name"] == "Jane"
        assert out["family_name"] == "Doe"
        assert out["display_name"] == "Jane Doe"
        # Passthrough preserved.
        assert out["sub"] == "a"
        assert out["email"] == "j@x.com"

    def test_google_passthrough(self) -> None:
        out = normalize_user_info(
            "google-native",
            {"given_name": "Bob", "family_name": "Smith", "email": "b@x.com"},
        )
        assert out["given_name"] == "Bob"
        assert out["family_name"] == "Smith"
        assert out["display_name"] == "Bob Smith"

    def test_github_name_to_display_name(self) -> None:
        out = normalize_user_info("github", {"name": "Octo Cat", "login": "octo"})
        assert out["display_name"] == "Octo Cat"

    def test_github_falls_back_to_login_when_name_missing(self) -> None:
        # GitHub's `name` is optional; `login` (username) is always present.
        out = normalize_user_info("github", {"name": None, "login": "octo", "email": "o@x.com"})
        assert out["display_name"] == "octo"

    def test_github_falls_back_to_login_when_name_absent(self) -> None:
        out = normalize_user_info("github", {"login": "octo"})
        assert out["display_name"] == "octo"

    def test_github_mobile_variant_also_falls_back_to_login(self) -> None:
        # Native-mobile variant carries the same provider semantics as `github`.
        out = normalize_user_info("github-mobile", {"login": "octo"})
        assert out["display_name"] == "octo"

    def test_login_fallback_gated_to_github(self) -> None:
        # A non-GitHub provider's `login` field must NOT become the display name,
        # since `login` may carry different semantics for other providers.
        out = normalize_user_info("google", {"login": "someacct", "email": "x@x.com"})
        assert "display_name" not in out

    def test_existing_display_name_wins(self) -> None:
        out = normalize_user_info(
            "apple", {"display_name": "Custom", "firstName": "A", "lastName": "B"}
        )
        assert out["display_name"] == "Custom"

    def test_empty_input(self) -> None:
        assert normalize_user_info("google", {}) == {}

    def test_partial_name_only_first(self) -> None:
        out = normalize_user_info("apple", {"firstName": "Solo"})
        assert out["given_name"] == "Solo"
        assert out["display_name"] == "Solo"
