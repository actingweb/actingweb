"""A permission-store fault never grants access (3.16 iteration, Issue A of
``thoughts/verifications/2026-10-29-db-fault-semantics-and-creator-uniqueness.md``).

The permission evaluator raises ``DbError`` on a store fault instead of
answering DENIED. Its callers used to catch every exception and fall back to
the legacy access list, which grants a ``friend`` peer ``properties``,
``methods`` and ``actions``: a throttle then overrode an explicit DENY. Every
caller must let the fault through (the integrations answer 503).
"""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest

from actingweb.db.exceptions import DbError
from tests._adoption_helpers import make_config


class _FaultingEvaluator:
    """Every evaluation hits a store fault."""

    def __getattr__(self, name: str) -> Any:
        def fault(*_a: Any, **_k: Any) -> Any:
            raise DbError("simulated permission-store fault")

        return fault


def _friend_auth() -> Any:
    """A trust-authenticated peer whose legacy access list would allow it."""
    auth = mock.Mock()
    auth.acl = {"peerid": "peer-1", "relationship": "friend"}
    auth.check_authorisation.return_value = True
    return auth


@pytest.fixture
def config() -> Any:
    return make_config()


@pytest.mark.parametrize(
    "module,cls_name,args",
    [
        ("properties", "PropertiesHandler", ("a1", "secret/x", "write")),
        ("properties", "PropertyMetadataHandler", ("a1", "secret/x", "read")),
        ("properties", "PropertyListItemsHandler", ("a1", "secret", "read")),
        ("methods", "MethodsHandler", ("a1", "wipe")),
        ("actions", "ActionsHandler", ("a1", "wipe")),
    ],
)
def test_handler_permission_check_does_not_fall_back_to_legacy(
    config: Any, module: str, cls_name: str, args: tuple[str, ...]
) -> None:
    import importlib

    from actingweb.aw_web_request import AWWebObj

    mod = importlib.import_module(f"actingweb.handlers.{module}")
    handler = getattr(mod, cls_name)(AWWebObj(), config)
    check = next(
        getattr(handler, n)
        for n in (
            "_check_property_permission",
            "_check_method_permission",
            "_check_action_permission",
        )
        if hasattr(handler, n)
    )
    auth = _friend_auth()
    actor_id, *rest = args

    with (
        mock.patch.object(
            mod, "get_permission_evaluator", lambda _c: _FaultingEvaluator()
        ),
        pytest.raises(DbError),
    ):
        check(actor_id, auth, *rest)

    auth.check_authorisation.assert_not_called()


def test_hook_permission_check_does_not_allow_on_a_fault(config: Any) -> None:
    from actingweb.interface import hooks as hooks_module

    registry = hooks_module.HookRegistry()
    actor = mock.Mock(id="a1")

    with (
        mock.patch.object(
            hooks_module, "get_permission_evaluator", lambda _c: _FaultingEvaluator()
        ),
        pytest.raises(DbError),
    ):
        registry._check_hook_permission(
            "property",
            "secret",
            actor,
            {"peer_id": "peer-1", "config": config, "operation": "put"},
        )


def test_evaluator_raises_on_a_store_fault_against_a_deny_override(
    config: Any,
) -> None:
    """The real evaluator over a store that faults: a raise, never ALLOWED."""
    from actingweb.permission_evaluator import PermissionEvaluator, PermissionType
    from actingweb.trust_permissions import initialize_trust_permission_store

    initialize_trust_permission_store(config)
    evaluator = PermissionEvaluator(config)
    with (
        mock.patch.object(
            evaluator.permission_store,
            "get_permissions",
            side_effect=DbError("simulated"),
        ),
        pytest.raises(DbError),
    ):
        evaluator.evaluate_permission(
            "a1", "peer-1", PermissionType.PROPERTIES, "secret/x", operation="write"
        )
