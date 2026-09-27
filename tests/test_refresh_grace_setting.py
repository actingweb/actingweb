"""``ActingWebApp.with_refresh_token_grace()``: bounds, and the value reaching
``Config.refresh_token_grace_period`` (read by both refresh ladders)."""

from unittest.mock import patch

import pytest

from actingweb.config import Config
from actingweb.constants import MCP_REFRESH_TOKEN_GRACE_PERIOD, REFRESH_TOKEN_GRACE_MAX
from actingweb.interface.app import ActingWebApp


def _app() -> ActingWebApp:
    with patch.object(ActingWebApp, "_initialize_permission_system"):
        return ActingWebApp(aw_type="urn:actingweb:test:grace", fqdn="test.example.com")


def test_the_default_is_60_seconds() -> None:
    assert MCP_REFRESH_TOKEN_GRACE_PERIOD == 60
    assert _app().get_config().refresh_token_grace_period == 60
    assert Config().refresh_token_grace_period == 60


@pytest.mark.parametrize("seconds", [0, 1, 30, REFRESH_TOKEN_GRACE_MAX])
def test_values_in_range_reach_config(seconds: int) -> None:
    app = _app().with_refresh_token_grace(seconds)
    assert app.get_config().refresh_token_grace_period == seconds


@pytest.mark.parametrize("seconds", [-1, REFRESH_TOKEN_GRACE_MAX + 1, 3600])
def test_values_out_of_range_are_refused(seconds: int) -> None:
    app = _app()
    with pytest.raises(ValueError):
        app.with_refresh_token_grace(seconds)
    assert app.get_config().refresh_token_grace_period == 60


@pytest.mark.parametrize("seconds", [True, 30.0, "30"])
def test_non_integers_are_refused(seconds: object) -> None:
    with pytest.raises(ValueError):
        _app().with_refresh_token_grace(seconds)  # type: ignore[arg-type]


def test_a_call_after_the_config_exists_still_reaches_it() -> None:
    app = _app()
    config = app.get_config()
    app.with_refresh_token_grace(15)
    assert config.refresh_token_grace_period == 15
    assert app.get_config() is config


def test_other_builder_calls_keep_the_value() -> None:
    app = _app().with_refresh_token_grace(15)
    app.get_config()
    app.with_sync_callbacks()
    assert app.get_config().refresh_token_grace_period == 15


@pytest.mark.parametrize(
    "value", [-1, REFRESH_TOKEN_GRACE_MAX + 1, 2592000, "sixty", None]
)
def test_config_refuses_a_bad_value_at_construction(value: object) -> None:
    """``Config(...)`` enforces the builder's bound, so a bad value fails
    when the app is configured, never on the request that reads it."""
    with pytest.raises(ValueError):
        Config(refresh_token_grace_period=value)


def test_config_accepts_a_value_in_range() -> None:
    assert Config(refresh_token_grace_period=0).refresh_token_grace_period == 0


def test_a_direct_assignment_survives_get_config() -> None:
    """Without a builder call, ``get_config()`` does not write the default
    back over a value assigned on the Config."""
    app = _app()
    app.get_config().refresh_token_grace_period = 10
    assert app.get_config().refresh_token_grace_period == 10


@pytest.mark.parametrize(
    "value", [-1, REFRESH_TOKEN_GRACE_MAX + 1, 3600, 0.0, "0", False, True, None]
)
def test_assigning_a_bad_value_raises(value: object) -> None:
    """Every write goes through the same check as the builder: an operator
    who assigns ``0.0`` or ``"0"`` is told, instead of silently getting the
    default."""
    config = Config()
    with pytest.raises(ValueError):
        config.refresh_token_grace_period = value  # type: ignore[assignment]
    assert config.refresh_token_grace_period == 60


def test_assigning_a_value_in_range_works() -> None:
    config = Config()
    config.refresh_token_grace_period = 0
    assert config.refresh_token_grace_period == 0


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, 0), (30, 30), (-5, 0), (3600, REFRESH_TOKEN_GRACE_MAX), (True, 60), ("x", 60)],
)
def test_the_ladders_clamp_a_config_that_bypasses_the_property(
    value: object, expected: int
) -> None:
    """Defence in depth for a duck-typed config object (not ``Config``):
    the ladders still never apply a grace outside 0 to 60."""
    from types import SimpleNamespace

    from actingweb.single_use import refresh_token_grace

    config = SimpleNamespace(refresh_token_grace_period=value)
    assert refresh_token_grace(config) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("age", "grace", "expected"),
    [
        (0, 0, "theft"),
        (-3, 0, "theft"),
        (0, 1, "grace"),
        (-3, 60, "grace"),
        (60, 60, "grace"),
        (61, 60, "theft"),
        (100, 60, "theft"),
        (101, 60, "expired"),
    ],
)
def test_classify_reuse(age: int, grace: int, expected: str) -> None:
    from actingweb.single_use import classify_reuse

    assert classify_reuse(age, grace, reuse_window=100) == expected
