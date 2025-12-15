import json
import logging

from actingweb import auth
from actingweb.handlers import base_handler
from actingweb.permission_evaluator import PermissionResult, get_permission_evaluator

# Import permission system with fallback
try:
    from ..trust_permissions import (
        create_permission_override,
        get_trust_permission_store,
    )

    PERMISSION_SYSTEM_AVAILABLE = True
except ImportError:
    # Set fallback values for when permission system is not available
    get_trust_permission_store = None
    create_permission_override = None
    PERMISSION_SYSTEM_AVAILABLE = False  # pyright: ignore[reportConstantRedefinition]

# /trust aw_handlers
#
# GET /trust with query parameters (relationship, type, and peerid) to retrieve trust relationships (auth: only creator
# and admins allowed)
# POST /trust with json body to initiate a trust relationship between this
#   actor and another (reciprocal relationship) (auth: only creator and admins allowed)
# POST /trust/{trust_type} with json body to create new trust
#   relationship (see config.py for default relationship and auto-accept, no
#   auth required)
#   Note: {trust_type} is the permission level (friend, admin, etc.), not the mini-app type
# GET /trust/{trust_type}}/{actorid} to get details on a specific relationship (auth: creator, admin, or peer secret)
# POST /trust/{trust_type}}/{actorid} to send information to a peer about changes in the relationship
# PUT /trust/{trust_type}}/{actorid} with a json body to change details on a relationship (baseuri, secret, desc)
# (auth: creator,
#   admin, or peer secret)
# DELETE /trust/{trust_type}}/{actorid} to delete a relationship (with
#   ?peer=true if the delete is from the peer) (auth: creator, admin, or
#   peer secret)


# Handling requests to trust/
class TrustHandler(base_handler.BaseHandler):
    def get(self, actor_id):
        if self.request.get("_method") == "POST":
            # Web UI method override for creating trust
            self.post(actor_id)
            try:
                status = getattr(self.response, "status_code", 0)
            except Exception:
                status = 0
            if status in (200, 201, 202):
                # After successful creation, return to trust overview
                self.response.set_status(302, "Found")
                self.response.set_redirect(f"/{actor_id}/www/trust")
            return
        myself = self.require_authenticated_actor(actor_id, "trust", "GET")
        if not myself:
            return
        relationship = self.request.get("relationship")
        trust_type = self.request.get("type")
        peerid = self.request.get(
            "peerid",
        )

        pairs = myself.get_trust_relationships(
            relationship=relationship, peerid=peerid, trust_type=trust_type
        )
        # Return empty array with 200 OK when no relationships exist (SPA-friendly, spec v1.2)
        if not pairs:
            pairs = []
        out = json.dumps(pairs)
        self.response.write(out)
        self.response.headers["Content-Type"] = "application/json"
        self.response.set_status(200, "Ok")

    def post(self, actor_id):
        myself = self.require_authenticated_actor(actor_id, "trust", "POST")
        if not myself:
            return
        desc = ""
        relationship = self.config.default_relationship
        try:
            body = self.request.body
            if isinstance(body, bytes):
                body = body.decode("utf-8", "ignore")
            elif body is None:
                body = "{}"
            params = json.loads(body)
            if "url" in params:
                url = params["url"]
            else:
                url = ""
            if "relationship" in params:
                relationship = params["relationship"]
            if "desc" in params:
                desc = params["desc"]
        except ValueError:
            url = self.request.get("url")
            relationship = self.request.get("relationship")
        if len(url) == 0:
            self.response.set_status(400, "Missing peer URL")
            return

        # Use developer API - ActorInterface with TrustManager
        actor_interface = self._get_actor_interface(myself)
        if not actor_interface:
            if self.response:
                self.response.set_status(500, "Internal error")
            return

        secret = self.config.new_token()
        new_trust_rel = actor_interface.trust.create_relationship(
            peer_url=url,
            secret=secret,
            description=desc,
            relationship=relationship,
        )
        if not new_trust_rel:
            self.response.set_status(408, "Unable to create trust relationship")
            return

        new_trust = new_trust_rel.to_dict()
        self.response.headers["Location"] = str(
            self.config.root
            + (myself.id or "")
            + "/trust/"
            + new_trust["relationship"]
            + "/"
            + new_trust["peerid"]
        )
        out = json.dumps(new_trust)
        self.response.write(out)
        self.response.headers["Content-Type"] = "application/json"
        self.response.set_status(201, "Created")


# Handling requests to /trust/*, e.g. /trust/friend
class TrustRelationshipHandler(base_handler.BaseHandler):
    def get(self, actor_id, relationship):
        if self.request.get("_method") == "POST":
            # Web UI method override for creating specific relationship
            self.post(actor_id, relationship)
            try:
                status = getattr(self.response, "status_code", 0)
            except Exception:
                status = 0
            if status in (200, 201, 202):
                self.response.set_status(302, "Found")
                self.response.set_redirect(f"/{actor_id}/www/trust")
            return
        self.response.set_status(404, "Not found")

    def put(self, actor_id, relationship):
        # Use AuthResult for granular control since we need add_response=False
        auth_result = self.authenticate_actor(
            actor_id, "trust", subpath=relationship, add_response=False
        )
        if not auth_result.success:
            return
        myself = auth_result.actor
        if relationship != "trustee":
            if self.response:
                self.response.set_status(404, "Not found")
            return
        # Access is the same as /trust
        if not auth_result.authorize("POST", "trust"):
            return
        try:
            body = self.request.body
            if isinstance(body, bytes):
                body = body.decode("utf-8", "ignore")
            elif body is None:
                body = "{}"
            params = json.loads(body)
            if "trustee_root" in params:
                trustee_root = params["trustee_root"]
            else:
                trustee_root = ""
            if "creator" in params:
                creator = params["creator"]
            else:
                creator = None
        except ValueError:
            if self.response:
                self.response.set_status(400, "No json content")
            return

        # Use developer API - ActorInterface with TrustManager
        actor_interface = self._get_actor_interface(myself)
        if not actor_interface:
            if self.response:
                self.response.set_status(500, "Internal error")
            return

        if len(trustee_root) > 0:
            actor_interface.trust.trustee_root = trustee_root
        if creator:
            myself.modify(creator=creator)
        if self.response:
            self.response.set_status(204, "No content")

    def delete(self, actor_id, relationship):
        # Use AuthResult for granular control since we need add_response=False
        auth_result = self.authenticate_actor(
            actor_id, "trust", subpath=relationship, add_response=False
        )
        if not auth_result.success:
            return
        myself = auth_result.actor
        if relationship != "trustee":
            if self.response:
                self.response.set_status(404, "Not found")
            return
        # Access is the same as /trust
        if not auth_result.authorize("DELETE", "trust"):
            return

        # Use developer API - ActorInterface with TrustManager
        actor_interface = self._get_actor_interface(myself)
        if not actor_interface:
            if self.response:
                self.response.set_status(500, "Internal error")
            return

        actor_interface.trust.trustee_root = None
        if self.response:
            self.response.set_status(204, "No content")

    def post(self, actor_id, relationship):
        # This endpoint does not require authentication - trust creation can be done by peers
        # Load actor without any authentication or authorization checks
        auth_result = self.authenticate_actor(
            actor_id, "trust", subpath=relationship, add_response=False
        )
        if not auth_result.actor:
            self.response.set_status(404)
            logging.debug(
                "Got trust creation request for unknown Actor(" + str(actor_id) + ")"
            )
            return
        myself = auth_result.actor
        # Skip authentication and authorization checks for this public endpoint
        try:
            body = self.request.body
            if isinstance(body, bytes):
                body = body.decode("utf-8", "ignore")
            elif body is None:
                body = "{}"
            params = json.loads(body)
            if "baseuri" in params:
                baseuri = params["baseuri"]
            else:
                baseuri = ""
            if "id" in params:
                peerid = params["id"]
            else:
                peerid = ""
            if "secret" in params:
                secret = params["secret"]
            else:
                secret = ""
            if "desc" in params:
                desc = params["desc"]
            else:
                desc = ""
            if "verify" in params:
                verification_token = params["verify"]
            else:
                verification_token = None
        except ValueError:
            if self.response:
                self.response.set_status(400, "No json content")
            return

        if len(baseuri) == 0 or len(peerid) == 0:
            self.response.set_status(400, "Missing mandatory attributes")
            return
        if (
            self.config.auto_accept_default_relationship
            and self.config.default_relationship == relationship
        ):
            approved = True
        else:
            approved = False

        # Use developer API - ActorInterface with TrustManager
        actor_interface = self._get_actor_interface(myself)
        if not actor_interface:
            if self.response:
                self.response.set_status(500, "Internal error")
            return

        # Since we received a request for a relationship, assume that peer has approved
        # Note: trust_type is the peer's mini-app type (from JSON body "type" field)
        #       relationship is the trust type/permission level (from URL path)
        peer_app_type = params.get("type", "")
        new_trust = actor_interface.trust.create_verified_trust(
            baseuri=baseuri,
            peer_id=peerid,
            approved=approved,
            secret=secret,
            verification_token=verification_token,
            trust_type=peer_app_type,  # peer's mini-application type (e.g., "urn:actingweb:example.com:banking")
            peer_approved=True,
            relationship=relationship,  # trust type/permission level (e.g., "friend", "admin")
            description=desc,
        )
        if not new_trust:
            self.response.set_status(403, "Forbidden")
            return
        self.response.headers["Location"] = str(
            self.config.root
            + (myself.id or "")
            + "/trust/"
            + new_trust["relationship"]
            + "/"
            + new_trust["peerid"]
        )
        out = json.dumps(new_trust)
        self.response.write(out)
        self.response.headers["Content-Type"] = "application/json"
        if approved:
            self.response.set_status(201, "Created")
        else:
            self.response.set_status(202, "Accepted")


# Handling requests to specific relationships, e.g. /trust/friend/12f2ae53bd
class TrustPeerHandler(base_handler.BaseHandler):
    def get(self, actor_id, relationship, peerid):
        if self.request.get("_method") == "PUT":
            # Web UI method override for updating/approving trust
            self.put(actor_id, relationship, peerid)
            try:
                status = getattr(self.response, "status_code", 0)
            except Exception:
                status = 0
            if status in (200, 201, 202, 204):
                self.response.set_status(302, "Found")
                self.response.set_redirect(f"/{actor_id}/www/trust")
            return
        if self.request.get("_method") == "DELETE":
            # Perform deletion, then redirect back to the web UI trust page on success
            self.delete(actor_id, relationship, peerid)
            try:
                status = getattr(self.response, "status_code", 0)
            except Exception:
                status = 0
            if status in (200, 201, 202, 204):
                # Redirect to the trust overview so the browser view updates
                self.response.set_status(302, "Found")
                self.response.set_redirect(f"/{actor_id}/www/trust")
            return
        logging.debug("GET trust headers: " + str(self.request.headers))
        auth_result = self.authenticate_actor(actor_id, "trust", subpath=relationship)
        if not auth_result.success:
            return
        myself = auth_result.actor
        # Custom authorization check for peer access - peers can read their own trust relationship
        if not auth_result.auth_obj.check_authorisation(
            path="trust",
            subpath="<type>/<id>",
            method="GET",
            peerid=peerid,
            approved=False,  # Allow access even if not fully approved
        ):
            if self.response:
                self.response.set_status(403)
            return
        relationships = myself.get_trust_relationships(
            relationship=relationship, peerid=peerid
        )
        if not relationships or len(relationships) == 0:
            if self.response:
                self.response.set_status(404, "Not found")
            return
        my_trust = relationships[0]

        # Check access based on authentication type (needed for verification logic)
        _ = (
            auth_result.auth_obj.acl.get("authenticated")
            and auth_result.auth_obj.acl.get("role") == "creator"
        )  # pyright: ignore[reportUnusedExpression]
        is_peer_token = auth_result.auth_obj.trust is not None

        # The GET handler should return trust data for verification purposes but NOT modify verified status
        # Verification is handled by create_verified_trust() on the receiving side, not here

        # Check if permissions query is requested
        include_permissions = self.request.get("permissions") == "true"

        if (
            include_permissions
            and PERMISSION_SYSTEM_AVAILABLE
            and get_trust_permission_store
        ):
            # Add permission information to response
            permission_store = get_trust_permission_store(self.config)
            permissions = permission_store.get_permissions(actor_id, peerid)

            if permissions:
                my_trust["permissions"] = {
                    "properties": permissions.properties,
                    "methods": permissions.methods,
                    "actions": permissions.actions,
                    "tools": permissions.tools,
                    "resources": permissions.resources,
                    "prompts": permissions.prompts,
                    "created_by": permissions.created_by,
                    "updated_at": permissions.updated_at,
                    "notes": permissions.notes,
                }
            else:
                my_trust["permissions"] = None

        if not my_trust["approved"] and is_peer_token:
            # Peer with token but unapproved trust - deny access
            if self.response:
                self.response.set_status(403, "Trust relationship not approved")
            return

        out = json.dumps(my_trust)
        self.response.write(out)
        self.response.headers["Content-Type"] = "application/json"
        if my_trust["approved"]:
            self.response.set_status(200, "Ok")
        else:
            # Creator can see unapproved trust details with 202 status
            self.response.set_status(202, "Accepted")

    def post(self, actor_id, relationship, peerid):
        auth_result = self.authenticate_actor(actor_id, "trust", subpath=relationship)
        if not auth_result.success:
            return
        myself = auth_result.actor
        try:
            body = self.request.body
            if isinstance(body, bytes):
                body = body.decode("utf-8", "ignore")
            elif body is None:
                body = "{}"
            params = json.loads(body)
            peer_approved = None
            if "approved" in params:
                if params["approved"] and params["approved"] is True:
                    peer_approved = True
        except ValueError:
            if self.response:
                self.response.set_status(400, "No json content")
            return
        if peer_approved:
            # If this is a notification from a peer about approval, we cannot check if the relationship is approved!
            # Custom authorization check for peer approval case
            if not auth_result.auth_obj.check_authorisation(
                path="trust",
                subpath="<type>/<id>",
                method="POST",
                peerid=peerid,
                approved=False,
            ):
                if self.response:
                    self.response.set_status(403)
                return
        else:
            if not auth_result.authorize("POST", "trust", "<type>/<id>"):
                return

        # Use developer API - ActorInterface with TrustManager
        actor_interface = self._get_actor_interface(myself)
        if not actor_interface:
            if self.response:
                self.response.set_status(500, "Internal error")
            return

        # Update the trust relationship
        trust_updated = actor_interface.trust.modify_and_notify(
            peer_id=peerid, relationship=relationship, peer_approved=peer_approved
        )

        # Trigger trust_approved lifecycle hook when receiving peer approval notification
        # This is the critical step where Actor A (who initiated the trust) learns that
        # Actor B has approved, and can now create subscriptions
        logging.info(
            f"📬 POST notification received: peer_approved={peer_approved}, "
            f"has_hooks={self.hooks is not None}"
        )
        if peer_approved is True and self.hooks:
            try:
                # Get the trust relationship data to check if both sides approved
                relationships = myself.get_trust_relationships(
                    relationship=relationship, peerid=peerid
                )
                if relationships:
                    trust_data = relationships[0]
                    # Only trigger hook if BOTH sides have approved
                    if trust_data.get("approved") and trust_data.get("peer_approved"):
                        logging.info(
                            f"🎉 Trust fully approved via POST notification: {actor_id} <-> {peerid}, "
                            f"triggering trust_approved hook"
                        )
                        from actingweb.interface.actor_interface import ActorInterface

                        actor_interface = ActorInterface(myself, self.config)
                        self.hooks.execute_lifecycle_hooks(
                            "trust_approved",
                            actor=actor_interface,
                            peer_id=peerid,
                            relationship=relationship,
                            trust_data=trust_data,
                        )
                        logging.info(
                            f"✅ trust_approved hook triggered via POST for {actor_id} <-> {peerid}"
                        )
                    else:
                        logging.debug(
                            f"Trust not yet fully approved after POST: approved={trust_data.get('approved')}, "
                            f"peer_approved={trust_data.get('peer_approved')}"
                        )
            except Exception as e:
                logging.error(
                    f"❌ Error triggering trust_approved hook in POST handler: {e}"
                )

        if trust_updated:
            self.response.set_status(204, "Ok")
        else:
            self.response.set_status(500, "Not modified")

    def put(self, actor_id, relationship, peerid):
        auth_result = self.authenticate_actor(actor_id, "trust", subpath=relationship)
        if not auth_result.success:
            return
        myself = auth_result.actor
        if not auth_result.authorize("PUT", "trust", "<type>/<id>"):
            return
        approved = None
        permission_updates = None
        actor_interface = None  # Initialize to satisfy type checker
        try:
            body = self.request.body
            if isinstance(body, bytes):
                body = body.decode("utf-8", "ignore")
            elif body is None:
                body = "{}"
            params = json.loads(body)
            if "baseuri" in params:
                baseuri = params["baseuri"]
            else:
                baseuri = ""
            if "desc" in params:
                desc = params["desc"]
            else:
                desc = ""
            if "approved" in params:
                if params["approved"] is True or params["approved"].lower() == "true":
                    approved = True

            # Handle permission updates
            if "permissions" in params and PERMISSION_SYSTEM_AVAILABLE:
                permission_updates = params["permissions"]
        except ValueError:
            if not self.request.get("_method") or self.request.get("_method") != "PUT":
                if self.response:
                    self.response.set_status(400, "No json content")
                return
            if self.request.get("approved") and len(self.request.get("approved")) > 0:
                if self.request.get("approved").lower() == "true":
                    approved = True
            if self.request.get("baseuri") and len(self.request.get("baseuri")) > 0:
                baseuri = self.request.get("baseuri")
            else:
                baseuri = ""
            if self.request.get("desc") and len(self.request.get("desc")) > 0:
                desc = self.request.get("desc")
            else:
                desc = ""
        # Use developer API - ActorInterface with TrustManager
        if actor_interface is None:
            actor_interface = self._get_actor_interface(myself)
            if not actor_interface:
                if self.response:
                    self.response.set_status(500, "Internal error")
                return

        # Update trust relationship
        trust_updated = actor_interface.trust.modify_and_notify(
            peer_id=peerid,
            relationship=relationship,
            baseuri=baseuri,
            approved=approved,
            description=desc,
        )

        # Update permissions if provided
        permissions_updated = True
        if (
            permission_updates is not None
            and PERMISSION_SYSTEM_AVAILABLE
            and get_trust_permission_store
        ):
            try:
                permission_store = get_trust_permission_store(self.config)

                # Check if permissions already exist
                existing_permissions = permission_store.get_permissions(
                    actor_id, peerid
                )

                if existing_permissions:
                    # Update existing permissions
                    permissions_updated = permission_store.update_permissions(
                        actor_id, peerid, permission_updates
                    )
                elif create_permission_override:
                    # Create new permission override
                    permissions_obj = create_permission_override(
                        actor_id=actor_id,
                        peer_id=peerid,
                        trust_type=relationship,  # Use relationship as trust type
                        permission_updates=permission_updates,
                    )
                    permissions_updated = permission_store.store_permissions(
                        permissions_obj
                    )

                if not permissions_updated:
                    logging.error(
                        f"Failed to update permissions for trust relationship {actor_id}:{peerid}"
                    )

            except Exception as e:
                logging.error(
                    f"Error updating permissions for trust relationship {actor_id}:{peerid}: {e}"
                )
                permissions_updated = False

        if trust_updated and permissions_updated:
            self.response.set_status(204, "Ok")
        else:
            self.response.set_status(500, "Not modified")

    def delete(self, actor_id, relationship, peerid):
        # Use AuthResult for granular control since we need add_response=False and custom logic
        auth_result = self.authenticate_actor(
            actor_id, "trust", subpath=relationship, add_response=False
        )
        if (
            not auth_result.actor
            or not auth_result.auth_obj
            or (
                auth_result.auth_obj.response["code"] != 200
                and auth_result.auth_obj.response["code"] != 401
            )
        ):
            auth.add_auth_response(appreq=self, auth_obj=auth_result.auth_obj)
            return
        myself = auth_result.actor
        # We allow non-approved peers to delete even if we haven't approved the relationship yet
        if not auth_result.auth_obj.check_authorisation(
            path="trust",
            subpath="<type>/<id>",
            method="DELETE",
            peerid=peerid,
            approved=False,
        ):
            if self.response:
                self.response.set_status(403)
            return

        # Prevent actors from deleting trust relationships with themselves
        if peerid == actor_id:
            if self.response:
                self.response.set_status(
                    400, "Cannot delete trust relationship with self"
                )
            return
        is_peer = False
        if (
            auth_result.auth_obj
            and auth_result.auth_obj.trust
            and auth_result.auth_obj.trust["peerid"] == peerid
        ):
            is_peer = True
        else:
            # Use of GET param peer=true is a way of forcing no deletion of a peer
            # relationship even when requestor is not a peer (primarily for testing purposes)
            peer_get = self.request.get("peer").lower()
            if peer_get.lower() == "true":
                is_peer = True
        relationships = myself.get_trust_relationships(
            relationship=relationship, peerid=peerid
        )
        if not relationships or len(relationships) == 0:
            if self.response:
                self.response.set_status(404, "Not found")
            return

        # Use developer API - ActorInterface with TrustManager
        actor_interface = self._get_actor_interface(myself)
        if not actor_interface:
            if self.response:
                self.response.set_status(500, "Internal error")
            return

        # Trigger trust_deleted lifecycle hook BEFORE deleting
        if self.hooks:
            try:
                self.hooks.execute_lifecycle_hooks(
                    "trust_deleted",
                    actor=actor_interface,
                    peer_id=peerid,
                )
                logging.debug(f"trust_deleted hook triggered for {actor_id} <-> {peerid}")
            except Exception as e:
                logging.error(f"Error triggering trust_deleted hook: {e}")

        # Delete trust relationship with appropriate peer notification setting
        if is_peer:
            deleted = actor_interface.trust.delete_peer_trust(
                peer_id=peerid, notify_peer=False
            )
        else:
            deleted = actor_interface.trust.delete_peer_trust(
                peer_id=peerid, notify_peer=True
            )
        if not deleted:
            self.response.set_status(502, "Not able to delete relationship with peer.")
            return
        self.response.set_status(204, "Ok")


# Handling requests to trust permissions, e.g. /trust/friend/12f2ae53bd/permissions
class TrustPermissionHandler(base_handler.BaseHandler):
    def get(self, actor_id: str, relationship: str, peerid: str):
        """Get effective permissions for a specific trust relationship (custom or default from trust type)."""
        if not PERMISSION_SYSTEM_AVAILABLE or not get_trust_permission_store:
            if self.response:
                self.response.set_status(501, "Permission system not available")
            return

        auth_result = self.authenticate_actor(actor_id, "trust", subpath=relationship)
        if not auth_result.success:
            logging.error(
                f"TrustPermissionHandler auth failed: actor={auth_result.actor is not None}, auth_obj={auth_result.auth_obj is not None}, code={auth_result.auth_obj.response['code'] if auth_result.auth_obj else 'None'}"
            )
            return

        # Same authorization as trust endpoint
        if not auth_result.authorize("GET", "trust", "<type>/<id>"):
            return

        try:
            permission_store = get_trust_permission_store(self.config)
            custom_permissions = permission_store.get_permissions(actor_id, peerid)

            if custom_permissions:
                # Return custom permission overrides
                permission_data = {
                    "actor_id": custom_permissions.actor_id,
                    "peer_id": custom_permissions.peer_id,
                    "trust_type": custom_permissions.trust_type,
                    "properties": custom_permissions.properties,
                    "methods": custom_permissions.methods,
                    "actions": custom_permissions.actions,
                    "tools": custom_permissions.tools,
                    "resources": custom_permissions.resources,
                    "prompts": custom_permissions.prompts,
                    "created_by": custom_permissions.created_by,
                    "updated_at": custom_permissions.updated_at,
                    "notes": custom_permissions.notes,
                    "is_custom": True,
                    "source": "custom_override",
                }
            else:
                # No custom permissions, get defaults from trust type registry
                # The 'relationship' parameter is the trust type (friend, admin, etc.)
                try:
                    from ..trust_type_registry import get_registry

                    registry = get_registry(self.config)
                    logging.debug(f"Looking up trust type '{relationship}' in registry")
                    trust_type = registry.get_type(relationship)

                    if not trust_type:
                        logging.error(
                            f"Trust type '{relationship}' not found in registry"
                        )
                        available_types = (
                            [t.name for t in registry.list_types()] if registry else []
                        )
                        logging.error(f"Available trust types: {available_types}")
                        if self.response:
                            self.response.set_status(
                                404, f"Trust type '{relationship}' not found"
                            )
                        return

                    logging.debug(
                        f"Found trust type '{relationship}': {trust_type.display_name}"
                    )

                    # Return default permissions from trust type
                    permission_data = {
                        "actor_id": actor_id,
                        "peer_id": peerid,
                        "trust_type": relationship,
                        "properties": trust_type.base_permissions.get("properties", {}),
                        "methods": trust_type.base_permissions.get("methods", {}),
                        "actions": trust_type.base_permissions.get("actions", {}),
                        "tools": trust_type.base_permissions.get("tools", {}),
                        "resources": trust_type.base_permissions.get("resources", {}),
                        "prompts": trust_type.base_permissions.get("prompts", {}),
                        "created_by": trust_type.created_by,
                        "updated_at": None,
                        "notes": f"Default permissions for {trust_type.display_name}",
                        "is_custom": False,
                        "source": "trust_type_default",
                    }
                except Exception as registry_error:
                    logging.error(
                        f"Error accessing trust type registry for {relationship}: {registry_error}"
                    )
                    if self.response:
                        self.response.set_status(
                            500,
                            f"Error accessing trust type defaults: {registry_error}",
                        )
                    return

            out = json.dumps(permission_data)
            self.response.write(out)
            self.response.headers["Content-Type"] = "application/json"
            self.response.set_status(200, "Ok")

        except Exception as e:
            logging.error(f"Error retrieving permissions for {actor_id}:{peerid}: {e}")
            if self.response:
                self.response.set_status(500, "Internal server error")

    def put(self, actor_id: str, relationship: str, peerid: str):
        """Create or update permission overrides for a trust relationship."""
        if not PERMISSION_SYSTEM_AVAILABLE or not get_trust_permission_store:
            if self.response:
                self.response.set_status(501, "Permission system not available")
            return

        auth_result = self.authenticate_actor(actor_id, "trust", subpath=relationship)
        if not auth_result.success:
            return
        myself = auth_result.actor

        # Same authorization as trust endpoint
        if not auth_result.authorize("PUT", "trust", "<type>/<id>"):
            return

        try:
            body = self.request.body
            if isinstance(body, bytes):
                body = body.decode("utf-8", "ignore")
            elif body is None:
                body = "{}"
            params = json.loads(body)

            # Validate trust relationship exists
            relationships = myself.get_trust_relationships(
                relationship=relationship, peerid=peerid
            )
            if not relationships or len(relationships) == 0:
                if self.response:
                    self.response.set_status(404, "Trust relationship not found")
                return

            permission_store = get_trust_permission_store(self.config)
            existing_permissions = permission_store.get_permissions(actor_id, peerid)

            if existing_permissions:
                # Update existing permissions
                success = permission_store.update_permissions(actor_id, peerid, params)
                if success:
                    self.response.set_status(200, "Updated")
                else:
                    self.response.set_status(500, "Failed to update permissions")
            elif create_permission_override:
                # Create new permission override
                permissions_obj = create_permission_override(
                    actor_id=actor_id,
                    peer_id=peerid,
                    trust_type=relationship,
                    permission_updates=params,
                )

                success = permission_store.store_permissions(permissions_obj)
                if success:
                    self.response.set_status(201, "Created")
                else:
                    self.response.set_status(500, "Failed to create permissions")

        except ValueError as e:
            logging.error(f"Invalid JSON in permission request: {e}")
            if self.response:
                self.response.set_status(400, "Invalid JSON")
        except Exception as e:
            logging.error(f"Error updating permissions for {actor_id}:{peerid}: {e}")
            if self.response:
                self.response.set_status(500, "Internal server error")

    def delete(self, actor_id: str, relationship: str, peerid: str):
        """Delete permission overrides for a trust relationship."""
        if not PERMISSION_SYSTEM_AVAILABLE or not get_trust_permission_store:
            if self.response:
                self.response.set_status(501, "Permission system not available")
            return

        auth_result = self.authenticate_actor(actor_id, "trust", subpath=relationship)
        if not auth_result.success:
            return

        # Same authorization as trust endpoint
        if not auth_result.authorize("DELETE", "trust", "<type>/<id>"):
            return

        try:
            permission_store = get_trust_permission_store(self.config)
            success = permission_store.delete_permissions(actor_id, peerid)

            if success:
                self.response.set_status(204, "Deleted")
            else:
                self.response.set_status(404, "No permissions found")

        except Exception as e:
            logging.error(f"Error deleting permissions for {actor_id}:{peerid}: {e}")
            if self.response:
                self.response.set_status(500, "Internal server error")


class TrustSharedPropertiesHandler(base_handler.BaseHandler):
    """Handler for /{actor_id}/trust/{relationship}/{peerid}/shared_properties

    Returns properties the authenticated peer is permitted to subscribe to.
    Requires an active trust relationship with the requesting peer.
    """

    def get(self, actor_id: str, relationship: str, peerid: str):
        """Get properties available for subscription by this peer."""
        # Authenticate the request
        auth_result = self.authenticate_actor(
            actor_id, "trust", subpath=f"{relationship}/{peerid}/shared_properties"
        )
        if not auth_result.success or not auth_result.actor:
            return

        myself = auth_result.actor

        # Verify the requesting peer matches the authenticated peer
        authenticated_peerid = (
            auth_result.auth_obj.acl.get("peerid") if auth_result.auth_obj else None
        )
        if peerid != authenticated_peerid:
            if self.response:
                self.response.set_status(403, "Can only query own shared properties")
            return

        # Verify trust relationship exists and is active
        trust_rel = myself.get_trust_relationship(peerid)
        if not trust_rel:
            if self.response:
                self.response.set_status(404, "Trust relationship not found")
            return

        # Get permission evaluator
        evaluator = (
            get_permission_evaluator(self.config)
            if PERMISSION_SYSTEM_AVAILABLE
            else None
        )
        if not evaluator:
            if self.response:
                self.response.set_status(503, "Permission system not available")
            return

        # Get all properties to check
        all_properties = myself.get_properties()
        property_names = list(all_properties.keys()) if all_properties else []

        # Also check property lists (distributed storage)
        actor_interface = None
        try:
            from actingweb.interface.actor_interface import ActorInterface

            actor_interface = ActorInterface(myself, self.config)
            if hasattr(actor_interface, "property_lists"):
                list_names = actor_interface.property_lists.list_all()
                property_names.extend(list_names)
        except Exception as e:
            logging.debug(f"Could not get property lists: {e}")

        # Remove duplicates
        property_names = list(set(property_names))

        # Filter by peer's permissions
        shared = []
        excluded = []

        for prop_name in property_names:
            result = evaluator.evaluate_property_access(
                actor_id, peerid, prop_name, operation="subscribe"
            )
            if result == PermissionResult.ALLOWED:
                # Get item count if it's a property list
                item_count = 0
                try:
                    if actor_interface and hasattr(actor_interface, "property_lists"):
                        prop_list = getattr(
                            actor_interface.property_lists, prop_name, None
                        )
                        if prop_list and hasattr(prop_list, "__len__"):
                            item_count = len(prop_list)
                except Exception as e:
                    logging.debug(
                        f"Could not get item count for property list {prop_name}: {e}"
                    )

                shared.append(
                    {
                        "name": prop_name,
                        "display_name": prop_name.replace("_", " ").title(),
                        "item_count": item_count,
                        "operations": ["read", "subscribe"],
                    }
                )
            else:
                excluded.append(prop_name)

        response_data = {
            "actor_id": actor_id,
            "peer_id": peerid,
            "relationship": relationship,
            "shared_properties": shared,
            "excluded_properties": excluded,
        }

        if self.response:
            self.response.write(json.dumps(response_data))
            self.response.headers["Content-Type"] = "application/json"
            self.response.set_status(200)
