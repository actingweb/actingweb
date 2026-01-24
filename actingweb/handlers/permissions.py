"""
Permission Query Handler for ActingWeb.

Provides HTTP endpoint for querying permissions granted by the actor to peers.
"""

import json
import logging
from typing import TYPE_CHECKING, Any

from actingweb.handlers import base_handler
from actingweb.trust_permissions import get_trust_permission_store
from actingweb.trust_type_registry import get_registry

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class PermissionsHandler(base_handler.BaseHandler):
    """Handler for GET /{actor_id}/permissions/{peer_id} endpoint."""

    def get(self, actor_id: str, peer_id: str):
        """
        Get permissions that this actor has granted to a specific peer.

        This endpoint allows peers to query what permissions they've been granted,
        supporting proactive permission discovery (complementing the reactive
        callback-based push mechanism).

        Args:
            actor_id: The actor granting permissions
            peer_id: The peer querying their granted permissions

        Returns:
            JSON response with permission structure or error
        """
        # Authenticate the requesting peer
        auth_result = self.authenticate_actor(actor_id, "permissions", subpath=peer_id)

        if not auth_result.success:
            logger.warning(
                f"Permission query auth failed for actor={actor_id}, peer={peer_id}"
            )
            return

        myself = auth_result.actor

        # Get ActorInterface to access trust relationship
        actor_interface = self._get_actor_interface(myself)
        if not actor_interface:
            if self.response:
                self.response.set_status(500, "Internal error")
            return

        # Verify trust relationship exists
        try:
            trust_rel = actor_interface.trust.get_relationship(peer_id)
            if not trust_rel:
                if self.response:
                    self.response.set_status(404, "Trust relationship not found")
                return
        except Exception as e:
            logger.warning(
                f"Error verifying trust relationship for {actor_id} <-> {peer_id}: {e}"
            )
            if self.response:
                self.response.set_status(404, "Trust relationship not found")
            return

        # Check authorization - peer must be requesting their own permissions
        check = auth_result.auth_obj
        if not check or not check.check_authorisation(
            path="permissions",
            subpath=peer_id,
            method="GET",
            peerid=peer_id,
        ):
            logger.warning(
                f"Authorization failed: peer {peer_id} querying permissions from {actor_id}"
            )
            if self.response:
                self.response.set_status(403, "Forbidden")
            return

        # Get permissions from TrustPermissionStore
        try:
            perm_store = get_trust_permission_store(self.config)
            custom_permissions = perm_store.get_permissions(actor_id, peer_id)

            response_data: dict[str, Any] = {
                "actor_id": actor_id,
                "peer_id": peer_id,
            }

            if custom_permissions:
                # Return custom permission overrides
                response_data["permissions"] = {
                    "properties": custom_permissions.properties or {},
                    "methods": custom_permissions.methods or {},
                    "actions": custom_permissions.actions or {},
                    "tools": custom_permissions.tools or {},
                    "resources": custom_permissions.resources or {},
                    "prompts": custom_permissions.prompts or {},
                }
                response_data["source"] = "custom_override"
                response_data["trust_type"] = custom_permissions.trust_type

                logger.debug(
                    f"Returning custom permissions for {actor_id} -> {peer_id}"
                )
            else:
                # Return defaults from trust type
                registry = get_registry(self.config)
                trust_type = registry.get_type(trust_rel.relationship)

                if not trust_type:
                    logger.error(
                        f"Trust type '{trust_rel.relationship}' not found in registry"
                    )
                    if self.response:
                        self.response.set_status(
                            500, f"Trust type '{trust_rel.relationship}' not configured"
                        )
                    return

                response_data["permissions"] = {
                    "properties": trust_type.base_permissions.get("properties", {}),
                    "methods": trust_type.base_permissions.get("methods", {}),
                    "actions": trust_type.base_permissions.get("actions", {}),
                    "tools": trust_type.base_permissions.get("tools", {}),
                    "resources": trust_type.base_permissions.get("resources", {}),
                    "prompts": trust_type.base_permissions.get("prompts", {}),
                }
                response_data["source"] = "trust_type_default"
                response_data["trust_type"] = trust_rel.relationship

                logger.debug(
                    f"Returning trust type defaults for {actor_id} -> {peer_id}: {trust_rel.relationship}"
                )

            # Send response
            if self.response:
                self.response.set_status(200, "OK")
                self.response.headers["Content-Type"] = "application/json"
                self.response.write(json.dumps(response_data))

        except Exception as e:
            logger.error(
                f"Error retrieving permissions for {actor_id} -> {peer_id}: {e}",
                exc_info=True,
            )
            if self.response:
                self.response.set_status(500, "Internal server error")
