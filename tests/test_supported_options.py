"""``/meta/actingweb/supported`` advertises what the app serves (3.16).

``Config.aw_supported`` is computed from the configuration on every read, so
a feature switched on after construction cannot leave a stale tag, and a tag
is advertised only when its path or behaviour exists.
"""

import re
from pathlib import Path
from unittest import mock

import pytest

from actingweb.config import Config
from actingweb.interface import ActingWebApp

# An app with the web UI and an OAuth provider (what the guides show).
GUIDE_EXAMPLE = (
    "actions,callbacks,listproperties,methods,nestedproperties,oauth,resources,"
    "subscriptionbatch,subscriptionresync,subscriptions,trust,trustpermissions,www"
)


def _tags(config: Config) -> set[str]:
    return set(config.aw_supported.split(","))


def _app() -> ActingWebApp:
    with mock.patch.object(ActingWebApp, "_initialize_permission_system"):
        return ActingWebApp(
            aw_type="urn:actingweb:test:supported", fqdn="x.example.com"
        )


def test_the_default_list_is_sorted_and_exact() -> None:
    config = Config()
    tags = config.aw_supported.split(",")
    assert tags == sorted(tags)
    assert set(tags) == {
        "actions",
        "callbacks",
        "listproperties",
        "methods",
        "nestedproperties",
        "resources",
        "subscriptionbatch",
        "subscriptionresync",
        "subscriptions",
        "trust",
        "trustpermissions",
        "www",
    }


def test_sessions_and_onewaytrust_are_never_advertised() -> None:
    for config in (Config(), Config(mcp=True, ui=False)):
        assert not {"sessions", "onewaytrust"} & _tags(config)
    assert "listproperties" in _tags(Config())


def test_www_follows_the_web_ui() -> None:
    assert "www" not in _tags(Config(ui=False))
    config = Config()
    config.ui = False  # a change after construction is reflected
    assert "www" not in _tags(config)


def test_oauth_needs_a_provider() -> None:
    assert "oauth" not in _tags(Config())
    assert "oauth" in _tags(Config(oauth={"client_id": "cid", "redirect_uri": "x"}))
    config = Config()
    config.oauth_providers = {"google": {"client_id": "cid"}}
    assert "oauth" in _tags(config)


def test_with_oauth_adds_the_tag() -> None:
    app = _app().with_oauth(
        client_id="cid",
        client_secret="s",
        scope="openid",
        auth_uri="https://a.example/auth",
        token_uri="https://a.example/token",
        redirect_uri="https://x.example.com/oauth",
    )
    assert "oauth" in _tags(app.get_config())


def test_with_mcp_adds_and_removes_the_tag_without_a_recompute() -> None:
    app = _app().with_mcp(enable=False)
    config = app.get_config()
    assert "mcp" not in _tags(config)
    with mock.patch.object(Config, "update_supported_options") as recompute:
        app.with_mcp(enable=True)
        assert "mcp" in _tags(config)
        app.with_mcp(enable=False)
        assert "mcp" not in _tags(config)
    recompute.assert_not_called()


def test_peer_permissions_caching_adds_its_two_tags() -> None:
    config = Config()
    config.peer_permissions_caching = True
    assert {"permissioncallback", "permissionquery"} <= _tags(config)


def test_aw_supported_is_read_only() -> None:
    with pytest.raises(AttributeError):
        Config().aw_supported = "x"  # type: ignore[misc]


def test_the_trustpermissions_tag_follows_availability() -> None:
    with mock.patch.object(
        Config, "_check_trust_permissions_available", return_value=False
    ):
        assert "trustpermissions" not in _tags(Config())


def test_the_two_guides_show_the_same_list_the_code_builds() -> None:
    config = Config(oauth={"client_id": "cid", "redirect_uri": "x"})
    assert config.aw_supported == GUIDE_EXAMPLE
    root = Path(__file__).resolve().parent.parent / "docs" / "guides"
    for name in ("access-control.rst", "access-control-simple.rst"):
        text = (root / name).read_text()
        assert re.search(rf"^\s+{re.escape(GUIDE_EXAMPLE)}$", text, re.M), name


def test_redirect_uri_follows_the_given_host_not_the_default() -> None:
    config = Config(fqdn="x.example", proto="https://")
    assert config.oauth["redirect_uri"] == "https://x.example/oauth"


def test_a_callers_own_redirect_uri_wins() -> None:
    config = Config(
        fqdn="x.example",
        proto="https://",
        oauth={"client_id": "c", "redirect_uri": "https://other.example/cb"},
    )
    assert config.oauth["redirect_uri"] == "https://other.example/cb"
