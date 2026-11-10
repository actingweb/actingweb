"""A stand-in permission evaluator for tests of the shared access decision.

``actingweb.access_decision.decide`` reads a peer's grant once
(``PermissionEvaluator.snapshot``) and applies its rule
(``evaluate_rules_for``). Tests written against the per-path API mock
``evaluate_property_access`` (and its siblings) to answer a fixed result;
``StubEvaluator`` routes the decision's two calls to those mocks, so such a
test keeps its result and its assertions. Not a test file.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

from actingweb.permission_evaluator import (
    GrantSnapshot,
    PermissionResult,
    PermissionType,
)

_BY_TYPE = {
    PermissionType.PROPERTIES: "evaluate_property_access",
    PermissionType.METHODS: "evaluate_method_access",
    PermissionType.ACTIONS: "evaluate_action_access",
    PermissionType.RESOURCES: "evaluate_resource_access",
}


class StubEvaluator(Mock):
    """A ``Mock`` evaluator whose grant mentions every category, approved,
    of ``relationship``; each rule check asks the matching
    ``evaluate_*_access`` mock (which a test sets)."""

    def __init__(self, *args: Any, relationship: str = "friend", **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._relationship = relationship
        self._ids = ("", "")

    def snapshot(self, actor_id: str, peer_id: str) -> GrantSnapshot:
        self._ids = (actor_id, peer_id)
        return GrantSnapshot(
            actor_id=actor_id,
            peer_id=peer_id,
            has_row=True,
            approved=True,
            relationship=self._relationship,
            is_client=False,
            permissions={t.value: {} for t in PermissionType},
        )

    def evaluate_rules_for(
        self,
        permission_type: PermissionType,
        rules: Any,
        target: str,
        operation: str,
        *,
        suppress_logging: bool = False,
    ) -> PermissionResult:
        actor_id, peer_id = self._ids
        method = getattr(self, _BY_TYPE[permission_type])
        if permission_type in (PermissionType.METHODS, PermissionType.ACTIONS):
            return method(actor_id, peer_id, target)
        return method(actor_id, peer_id, target, operation)

    def evaluate_snapshot(
        self,
        snapshot: GrantSnapshot,
        permission_type: PermissionType,
        target: str,
        operation: str,
        *,
        suppress_logging: bool = True,
    ) -> PermissionResult:
        self._ids = (snapshot.actor_id, snapshot.peer_id)
        return self.evaluate_rules_for(permission_type, None, target, operation)
