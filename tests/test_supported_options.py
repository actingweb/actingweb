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
    "actions,callbacks,listproperties,methods,nestedproperties,oauth,"
    "permissioncallback,permissionquery,resources,subscriptionresync,"
    "subscriptions,trust,trustpermissions,www"
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
        "permissioncallback",
        "permissionquery",
        "resources",
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


def test_the_permission_tags_are_advertised_with_caching_off() -> None:
    """Both endpoints are always served, so both tags are always there
    (3.16; they needed peer permission caching)."""
    config = Config()
    assert not getattr(config, "peer_permissions_caching", False)
    assert {"permissioncallback", "permissionquery"} <= _tags(config)
    config.peer_permissions_caching = True
    assert {"permissioncallback", "permissionquery"} <= _tags(config)


def test_subscriptionbatch_is_not_advertised() -> None:
    """Defined by no specification and served by nothing (3.16)."""
    for config in (Config(), Config(mcp=True, ui=False)):
        assert "subscriptionbatch" not in _tags(config)


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


def test_the_application_version_is_served_when_set() -> None:
    from actingweb import __version__

    assert _app().get_config().version == __version__
    app = _app().with_app_version("2.3.1")
    assert app.get_config().version == "2.3.1"
    # Set after the config exists: reflected.
    app = _app()
    config = app.get_config()
    app.with_app_version("7.0")
    assert config.version == "7.0"


def test_the_application_version_must_be_a_string() -> None:
    with pytest.raises(ValueError):
        _app().with_app_version("")
