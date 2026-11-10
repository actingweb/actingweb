"""The levels an OAuth2/MCP client may be given (3.16, plan Phase 3).

The application's list answers; with none (or ``{"allowed": None}``) every
registered type except ``admin`` is acceptable; an unknown type never is.
The decision hook fails closed.
"""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest

from actingweb.db.exceptions import DbError
from actingweb.interface.hooks import HookRegistry
from actingweb.permission_integration import (
    client_trust_type_acceptable,
    default_client_trust_type,
)

REGISTERED = {"admin", "friend", "mcp_client", "viewer"}


class _Config:
    def __init__(self, configured: dict[str, Any] | None = None):
        if configured is not None:
            self._oauth2_trust_types = configured


@pytest.fixture(autouse=True)
def registry():
    reg = mock.Mock()
    reg.get_type.side_effect = lambda n: mock.Mock(name=n) if n in REGISTERED else None
    reg.list_types.return_value = [mock.Mock(**{"name": n}) for n in sorted(REGISTERED)]
    for t, n in zip(reg.list_types.return_value, sorted(REGISTERED), strict=True):
        t.name = n
    with mock.patch("actingweb.trust_type_registry.get_registry", return_value=reg):
        yield reg


@pytest.mark.parametrize("configured", [None, {"allowed": None, "default": None}])
def test_without_a_list_every_registered_type_but_admin(configured) -> None:
    config = _Config(configured)
    assert client_trust_type_acceptable(config, "friend")
    assert client_trust_type_acceptable(config, "mcp_client")
    assert not client_trust_type_acceptable(config, "admin")
    assert not client_trust_type_acceptable(config, "unknown")
    assert not client_trust_type_acceptable(config, None)
    assert default_client_trust_type(config) == "mcp_client"


def test_a_list_answers_and_admin_only_when_listed() -> None:
    config = _Config({"allowed": ["viewer", "admin", "unknown"], "default": None})
    assert client_trust_type_acceptable(config, "admin")
    assert client_trust_type_acceptable(config, "viewer")
    assert not client_trust_type_acceptable(config, "friend")
    assert not client_trust_type_acceptable(config, "unknown")  # not registered
    assert default_client_trust_type(config) == "viewer"


def test_a_configured_default_wins_when_acceptable() -> None:
    assert (
        default_client_trust_type(
            _Config({"allowed": ["friend", "viewer"], "default": "friend"})
        )
        == "friend"
    )
    assert (
        default_client_trust_type(_Config({"allowed": ["viewer"], "default": "admin"}))
        == "viewer"
    )


def _decide(*hooks: Any, requested: str = "mcp_client") -> str | None:
    registry = HookRegistry()
    for hook in hooks:
        registry.register_lifecycle_hook("oauth2_trust_requested", hook)
    return registry.decide_oauth2_trust(
        mock.Mock(), requested, _Config(), client_id="c", confirmed=False
    )


def test_no_hook_keeps_the_requested_type() -> None:
    assert _decide() == "mcp_client"
    assert _decide(requested="admin") is None  # not acceptable


def test_a_hook_lowers_declines_or_raises() -> None:
    assert _decide(lambda actor, **kw: "viewer") == "viewer"
    assert _decide(lambda actor, **kw: None) == "mcp_client"
    assert _decide(lambda actor, **kw: False) is None

    def boom(actor: Any, **kw: Any) -> Any:
        raise RuntimeError("bug")

    assert _decide(boom) is None
    assert _decide(lambda actor, **kw: "viewer", lambda actor, **kw: "friend") is None
    assert _decide(lambda actor, **kw: "admin") is None  # not acceptable


def test_a_hook_sees_what_is_asked() -> None:
    seen: dict[str, Any] = {}

    def hook(actor: Any, **kw: Any) -> None:
        seen.update(kw)

    _decide(hook)
    assert seen["trust_type"] == "mcp_client"
    assert seen["client_id"] == "c" and seen["confirmed"] is False


def test_a_storage_fault_propagates() -> None:
    def fault(actor: Any, **kw: Any) -> Any:
        raise DbError("fault")

    with pytest.raises(DbError):
        _decide(fault)
