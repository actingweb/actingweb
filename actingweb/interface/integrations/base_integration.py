"""
Base integration logic shared between Flask and FastAPI implementations.

This module contains common handler selection logic, utility methods, and
patterns used by both Flask and FastAPI integrations.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...config import Config
    from ...handlers import base_handler
    from ..app import ActingWebApp


class BaseActingWebIntegration:
    """Base class for ActingWeb framework integrations.

    Provides shared handler selection logic and common patterns.
    Subclassed by FlaskActingWebIntegration and FastAPIActingWebIntegration.
    """

    def __init__(self, aw_app: "ActingWebApp"):
        """Initialize base integration with ActingWeb app."""
        self.aw_app = aw_app

    def get_handler_class(
        self,
        endpoint: str,
        webobj: Any,
        config: "Config",
        **kwargs: Any,
    ) -> "base_handler.BaseHandler | None":
        """Get the appropriate handler class for an endpoint.

        This method contains the shared logic for selecting handlers based on
        endpoint and path parameters. Both Flask and FastAPI integrations use
        this method to avoid duplication.

        Args:
            endpoint: The endpoint name (e.g., "trust", "properties", "subscriptions")
            webobj: Framework-specific request/response wrapper
            config: ActingWeb configuration
            **kwargs: Path parameters and other context

        Returns:
            Handler instance or None if no handler matches
        """
        from ...handlers import (
            actions,
            callbacks,
            devtest,
            meta,
            methods,
            properties,
            resources,
            root,
            www,
        )

        # Create handler dictionary - most endpoints map directly to handlers
        handlers = {
            "root": lambda: root.RootHandler(webobj, config, hooks=self.aw_app.hooks),
            "meta": lambda: meta.MetaHandler(webobj, config, hooks=self.aw_app.hooks),
            "www": lambda: www.WwwHandler(webobj, config, hooks=self.aw_app.hooks),
            "properties": lambda: properties.PropertiesHandler(
                webobj, config, hooks=self.aw_app.hooks
            ),
            "resources": lambda: resources.ResourcesHandler(
                webobj, config, hooks=self.aw_app.hooks
            ),
            "callbacks": lambda: callbacks.CallbacksHandler(
                webobj, config, hooks=self.aw_app.hooks
            ),
            "devtest": lambda: devtest.DevtestHandler(
                webobj, config, hooks=self.aw_app.hooks
            ),
            "methods": lambda: methods.MethodsHandler(
                webobj, config, hooks=self.aw_app.hooks
            ),
            "actions": lambda: actions.ActionsHandler(
                webobj, config, hooks=self.aw_app.hooks
            ),
        }

        # Special handling for properties metadata endpoint
        if endpoint == "properties" and kwargs.get("metadata"):
            return properties.PropertyMetadataHandler(
                webobj, config, hooks=self.aw_app.hooks
            )

        # Special handling for properties list items endpoint
        if endpoint == "properties" and kwargs.get("items"):
            return properties.PropertyListItemsHandler(
                webobj, config, hooks=self.aw_app.hooks
            )

        # Special handling for trust endpoint
        if endpoint == "trust":
            return self._get_trust_handler(webobj, config, kwargs)

        # Special handling for subscriptions endpoint
        if endpoint == "subscriptions":
            return self._get_subscription_handler(webobj, config, kwargs)

        # Standard handler lookup
        if endpoint in handlers:
            return handlers[endpoint]()

        return None

    def _get_trust_handler(
        self,
        webobj: Any,
        config: "Config",
        kwargs: dict[str, Any],
    ) -> "base_handler.BaseHandler":
        """Select appropriate trust handler based on path parameters.

        Trust endpoints follow this pattern:
        - GET/POST /trust -> TrustHandler (list/create)
        - GET/PUT/DELETE /trust/{relationship} -> TrustRelationshipHandler
        - GET/PUT/DELETE /trust/{relationship}/{peerid} -> TrustPeerHandler
        - GET /trust/{relationship}/{peerid}/shared_properties -> TrustSharedPropertiesHandler
        - GET/POST /trust/{relationship}/{peerid}/permissions -> TrustPermissionHandler

        Special case: UI forms that send GET /trust/<peerid>?_method=DELETE|PUT
        are treated as peer operations (TrustPeerHandler).
        """
        from ...handlers import trust

        relationship = kwargs.get("relationship")
        peerid = kwargs.get("peerid")

        # Check for shared_properties endpoint
        if kwargs.get("shared_properties"):
            return trust.TrustSharedPropertiesHandler(
                webobj, config, hooks=self.aw_app.hooks
            )

        # Check for permissions endpoint
        if kwargs.get("permissions"):
            return trust.TrustPermissionHandler(
                webobj, config, hooks=self.aw_app.hooks
            )

        # Check for _method override (used by UI forms for DELETE/PUT)
        # When present, a single path segment should be treated as a peer ID
        method_override = (webobj.request.get("_method") or "").upper()
        is_method_override = method_override in ("DELETE", "PUT")

        # Determine handler based on path depth
        # Only count actual path parameters (non-None, non-empty)
        path_parts = []
        if relationship is not None and relationship != "":
            path_parts.append(relationship)
        if peerid is not None and peerid != "":
            path_parts.append(peerid)

        if len(path_parts) == 0:
            return trust.TrustHandler(webobj, config, hooks=self.aw_app.hooks)
        elif len(path_parts) == 1:
            # If _method override is present with DELETE/PUT, treat as peer operation
            # (the single path segment will be interpreted as peerid by the caller)
            if is_method_override:
                return trust.TrustPeerHandler(webobj, config, hooks=self.aw_app.hooks)
            else:
                return trust.TrustRelationshipHandler(
                    webobj, config, hooks=self.aw_app.hooks
                )
        else:
            return trust.TrustPeerHandler(webobj, config, hooks=self.aw_app.hooks)

    def _get_subscription_handler(
        self,
        webobj: Any,
        config: "Config",
        kwargs: dict[str, Any],
    ) -> "base_handler.BaseHandler":
        """Select appropriate subscription handler based on path parameters.

        Subscription endpoints follow this pattern:
        - GET/POST /subscriptions -> SubscriptionRootHandler
        - GET /subscriptions/{peerid} -> SubscriptionRelationshipHandler
        - GET/DELETE /subscriptions/{peerid}/{subid} -> SubscriptionHandler
        - GET /subscriptions/{peerid}/{subid}/diffs -> SubscriptionDiffHandler (subid may be numeric)
        - GET /subscriptions/{peerid}/{subid}/{seqnr} -> SubscriptionDiffHandler (specific diff)
        """
        from ...handlers import subscription

        peerid = kwargs.get("peerid")
        subid = kwargs.get("subid")
        seqnr = kwargs.get("seqnr")

        # Count path parts
        path_parts = [p for p in [peerid, subid] if p]

        if len(path_parts) == 0:
            return subscription.SubscriptionRootHandler(
                webobj, config, hooks=self.aw_app.hooks
            )
        elif len(path_parts) == 1:
            return subscription.SubscriptionRelationshipHandler(
                webobj, config, hooks=self.aw_app.hooks
            )
        elif len(path_parts) == 2 and seqnr is None:
            return subscription.SubscriptionHandler(
                webobj, config, hooks=self.aw_app.hooks
            )
        else:
            return subscription.SubscriptionDiffHandler(
                webobj, config, hooks=self.aw_app.hooks
            )

    @staticmethod
    def get_oauth_discovery_metadata(config: "Config") -> dict[str, Any]:
        """Create OAuth2 Authorization Server Discovery response (RFC 8414).

        Shared between Flask and FastAPI implementations.
        """
        base_url = f"{config.proto}{config.fqdn}"

        return {
            "issuer": base_url,
            "authorization_endpoint": f"{base_url}/oauth/authorize",
            "token_endpoint": f"{base_url}/oauth/token",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "scopes_supported": ["openid", "profile", "email", "mcp"],
            "token_endpoint_auth_methods_supported": ["client_secret_post"],
        }

    @staticmethod
    def normalize_http_method(method: str) -> str:
        """Normalize HTTP method name to uppercase.

        Handles framework differences in method naming.
        """
        return method.upper() if method else "GET"

    @staticmethod
    def extract_path_params(path: str, pattern: str) -> dict[str, str]:
        """Extract path parameters from URL path based on pattern.

        Helper for both Flask and FastAPI routing.
        Returns dict of parameter names to values.
        """
        # This is a simplified implementation - frameworks handle this internally
        # Keeping as placeholder for potential future use
        return {}

    @staticmethod
    def build_error_response(status_code: int, message: str) -> dict[str, Any]:
        """Build standardized error response.

        Returns JSON error structure used by both frameworks.
        """
        return {
            "error": {
                "code": status_code,
                "message": message,
            }
        }

    @staticmethod
    def build_success_response(data: Any, status_code: int = 200) -> dict[str, Any]:
        """Build standardized success response.

        Returns JSON response structure.
        """
        if isinstance(data, dict):
            return data
        return {"data": data, "status": "success"}
