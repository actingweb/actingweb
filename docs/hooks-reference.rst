================
Hooks Reference
================

This page summarizes hook types, signatures, and behaviors exposed by the modern interface. Prefer the decorators on ``ActingWebApp`` (``app.property_hook(...)`` etc.).

Overview
========

Hook execution applies unified access control when enabled. For property hooks, returning ``None`` during write operations (PUT/POST/DELETE) rejects the change; returning ``None`` during GET hides the value from the caller and from the web UI.

Property Hooks
==============

Decorator: ``app.property_hook(name: str = "*")``

Signature: ``func(actor, operation: str, value: Any, path: List[str]) -> Optional[Any]``

- ``operation``: ``get|put|post|delete``
- ``path``: Subkeys for nested access (e.g., ``["settings", "theme"]``)
- Return new value to allow/transform, or ``None`` to hide/deny
- Matching: exact name first, then wildcard ``"*"`` handlers

Example:

.. code-block:: python

    @app.property_hook("email")
    def email_guard(actor, operation, value, path):
        if operation in ("put", "post", "delete"):
            return None  # read-only
        return value if actor.is_owner() else None  # hide from non-owner

Callback Hooks
==============

Decorator: ``app.callback_hook(name: str = "*")``

Signature: ``func(actor, name: str, data: dict) -> bool | dict``

- Return ``True`` when processed; optionally return a ``dict`` as response payload
- Used for custom endpoints registered by the framework (e.g., ``bot``)

Application Callback Hooks
==========================

Decorator: ``app.app_callback_hook(name: str)``

Signature: ``func(data: dict) -> bool | dict``

- Like callback hooks but without actor context (application-level)

Subscription Hooks
==================

Decorator: ``app.subscription_hook``

Signature: ``func(actor, subscription: dict, peer_id: str, data: dict) -> bool``

- Return ``True`` when the subscription callback was handled

Lifecycle Hooks
================

Decorator: ``app.lifecycle_hook(event: str)``

Signature: ``func(actor, **kwargs) -> Any``

- Common events: ``actor_created``, ``actor_deleted``, ``oauth_success``, ``trust_approved``, ``trust_deleted``

Method Hooks
============

Decorator: ``app.method_hook(name: str = "*")``

Signature: ``func(actor, method_name: str, data: dict) -> Any``

- Implements RPC-style methods under ``/methods``; first non-None return wins

Action Hooks
============

Decorator: ``app.action_hook(name: str = "*")``

Signature: ``func(actor, action_name: str, data: dict) -> Any``

- Implements side-effecting operations under ``/actions``; first non-None return wins

Matching & Ordering
===================

- Specific-name hooks execute before wildcard hooks
- For methods/actions, the first hook returning a non-None value wins
- For properties, hooks can transform the value; ``None`` hides/denies

Path Semantics (Properties)
===========================

- ``path`` conveys nested segments. Example: GET ``/properties/settings/theme`` → ``path=["settings", "theme"]``
- Use path to enforce fine-grained access or type normalization

