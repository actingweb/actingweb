import html
import json
import logging
from typing import Any

from actingweb import auth
from actingweb.client_text import sanitize_client_name, sanitize_label
from actingweb.handlers import base_handler
from actingweb.permission_evaluator import get_permission_evaluator

from ..db import get_actor
from ..db.creator_rules import is_refused_from_callers, normalise_creator
from ..db.exceptions import CreatorTaken, DbError
from ..secret_compare import secret_equals

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

logger = logging.getLogger(__name__)

# Fields of a trust row that are bearer credentials. The list route never
# returns them; the per-relationship GET does (see TrustPeerHandler.get).
_TRUST_LIST_CREDENTIAL_FIELDS = ("secret", "verification_token")


def _sanitize_trust_text(row: dict[str, Any]) -> dict[str, Any]:
    """Sanitise the client-supplied text fields of a trust row copy.

    ``client_name`` and ``client_version`` come from MCP clients and
    registrations, ``desc`` from users and peers. Rows written before 3.15
    were stored raw, so both trust GET routes sanitise on the way out.
    ``desc`` is stripped but never capped: users edit it.
    """
    for key in ("client_name", "client_version"):
        if isinstance(row.get(key), str):
            row[key] = sanitize_client_name(row[key])
    if isinstance(row.get("client_platform"), str):
        row["client_platform"] = sanitize_client_name(
            row["client_platform"], max_len=200
        )
    if isinstance(row.get("desc"), str):
        row["desc"] = sanitize_label(row["desc"])
    return row


def _public_trust_row(row: Any) -> Any:
    """Return ``row`` without its credential fields, for the trust list.

    A dict is copied so the caller's row (shared with ``auth.py``, the proxy
    and peer verification) keeps its secret; its client-supplied text is
    sanitised. Anything else is returned as is.
    """
    if not isinstance(row, dict):
        return row
    return _sanitize_trust_text(
        {k: v for k, v in row.items() if k not in _TRUST_LIST_CREDENTIAL_FIELDS}
    )


# Handling requests to trust/
def _is_non_admin_peer(auth_obj: Any) -> bool:
    """Whether the caller is a peer other than an ``admin`` one. A peer may
    read and delete its own trust row, but never approve it or write its own
    permissions, whatever an application row admits."""
    acl = getattr(auth_obj, "acl", None)
    if not isinstance(acl, dict):
        return False
    peer = acl.get("peerid") or ""
    relationship = str(acl.get("relationship") or "").lower()
    return isinstance(peer, str) and bool(peer) and relationship != "admin"


class TrustHandler(base_handler.BaseHandler):
    def get(self, actor_id):
        # A GET with a _method override changes state: refuse one a
        # page on another site started (see BaseHandler).
        if self._refuse_cross_site_override():
            return
        if self.request.get("_method") == "POST":
            # Web UI method override for creating trust
            self.post(actor_id)
            try:
                status = getattr(self.response, "status_code", 0)
            except Exception:  # folds DbError: no DB access
                status = 0
            if status in (200, 201, 202):
                # After successful creation, return to trust overview
                self.response.set_status(302, "Found")
                self.response.set_redirect(self._www_path(actor_id, "/trust"))
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
        # The list never carries peer credentials: a browser session or SPA
        # cache must not hold every peer's bearer secret. The per-relationship
        # GET still returns them to creator and admin.
        out = json.dumps([_public_trust_row(row) for row in pairs])
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

        # Trigger trust_initiated lifecycle hook to notify application of outgoing trust request
        # (none when the create approved the peer's waiting request instead:
        # no request went out, and trust_fully_approved_local ran)
        if self.hooks and not actor_interface.core_actor.last_trust_approved_on_create:
            try:
                peerid = new_trust.get("peerid", "")
                logger.debug(
                    f"trust_initiated hook called for {actor_id} -> {peerid}, "
                    f"relationship={relationship}"
                )
                self.hooks.execute_lifecycle_hooks(
                    "trust_initiated",
                    actor=actor_interface,
                    peer_id=peerid,
                    relationship=relationship,
                    trust_data=new_trust,
                )
                logger.info(
                    f"trust_initiated hook triggered for {actor_id} -> {peerid}"
                )
            except Exception as e:  # folds DbError: hook after the trust committed
                logger.error(f"Error triggering trust_initiated hook: {e}")

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


def _trust_request_answer(row: dict[str, Any]) -> dict[str, Any]:
    """The body of the answer to a trust request (a creation or a re-pair):
    the row, without its verification token and secret while this actor
    has not approved it (3.16). Whoever filed a request under another
    actor's id could otherwise answer that actor's verification with the
    token; the secret is the requester's own."""
    answer = dict(row)
    if str(answer.get("approved")).lower() != "true":
        answer.pop("verification_token", None)
        answer.pop("secret", None)
    return answer


# Handling requests to /trust/*, e.g. /trust/friend
class TrustRelationshipHandler(base_handler.BaseHandler):
    def get(self, actor_id, relationship):
        # A GET with a _method override changes state: refuse one a
        # page on another site started (see BaseHandler).
        if self._refuse_cross_site_override():
            return
        if self.request.get("_method") == "POST":
            # Web UI method override for creating specific relationship
            self.post(actor_id, relationship)
            try:
                status = getattr(self.response, "status_code", 0)
            except Exception:  # folds DbError: no DB access
                status = 0
            if status in (200, 201, 202):
                self.response.set_status(302, "Found")
                self.response.set_redirect(self._www_path(actor_id, "/trust"))
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

        if creator and not self._change_creator(myself, creator):
            # Refused or failed; the status is set. Nothing else is applied.
            return
        if len(trustee_root) > 0:
            actor_interface.trust.trustee_root = trustee_root
        if self.response:
            self.response.set_status(204, "No content")

    def _change_creator(self, myself: Any, creator: str) -> bool:
        """Change the creator for ``PUT /<id>/trust/trustee``.

        Returns False with the response status set when the change was
        refused or did not land.
        """
        # A creator set over HTTP is self-asserted, like the factory's: nothing
        # proved the caller owns the new address, so the change unvouches the
        # actor (Actor.modify_creator_unvouched has the rules, the pin too).
        # An unreadable _internal bucket fails there, as a 500.
        if not isinstance(creator, str) or is_refused_from_callers(creator):
            # "#…" and "#dup-" belong to the uniqueness bookkeeping.
            if self.response:
                self.response.set_status(400, "creator is reserved")
            return False
        if myself.creator_change_pinned(creator):
            if self.response:
                self.response.set_status(
                    400,
                    "creator is pinned to the stored email "
                    "(force_email_prop_as_creator)",
                )
            return False
        original = myself.creator
        try:
            if myself.modify_creator_unvouched(creator):
                return True
        except CreatorTaken:  # folds DbError: answered as the 409 conflict
            # Another actor holds the address (with_unique_creator). Both
            # actors are as they were.
            self._conflict("creator is held by another actor")
            return False
        # A stale handle answers False (another request renamed the actor
        # since it was loaded): a conflict, not a server error. Unless the
        # stored value is the one asked for (this request's own write, whose
        # answer was lost), or the actor is gone.
        row = (
            get_actor(myself.config).get(actor_id=myself.id) if myself.config else None
        )
        if myself.config and not row:
            if self.response:
                self.response.set_status(404, "Not found")
            return False
        if row and normalise_creator(row.get("creator")) == normalise_creator(creator):
            return True
        if row and row.get("creator") != original:
            self._conflict("the actor's creator changed meanwhile; reload and retry")
            return False
        if self.response:
            self.response.set_status(500, "Internal error")
        return False

    def _conflict(self, message: str) -> None:
        if self.response:
            self.response.set_status(409, "Conflict")
            self.response.write(
                json.dumps({"error": True, "status_code": 409, "message": message})
            )
            self.response.headers["Content-Type"] = "application/json"

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
            logger.debug(
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
        from actingweb.trust import is_valid_peer_baseuri, is_valid_peer_id

        if not is_valid_peer_id(peerid) or not is_valid_peer_baseuri(baseuri):
            # Both are shown to the owner and built into links on the
            # owner's own pages: refuse anything that is not plainly an id
            # and plainly a base URL.
            self.response.set_status(400, "Invalid id or baseuri")
            return
        # A peer that already has a row re-pairs: a credential swap, never a
        # replacement of the row (read once here). A pending row (neither
        # verified nor approved) is left to the creation path, which replaces
        # it only with a request that verifies.
        existing = myself.get_trust_relationship(peerid=peerid)
        acl = getattr(auth_result.auth_obj, "acl", None)
        proven = (
            isinstance(acl, dict)
            and bool(acl.get("authenticated"))
            and acl.get("peerid") == peerid
        )
        if existing and (existing.get("verified") or existing.get("approved")):
            # A re-pair applies to a verified or approved row only (audit A2):
            # a pending row's holder proves only the secret it chose, and the
            # row is replaced only by a request that verifies (below).
            bearer = getattr(auth_result.auth_obj, "token", None) if proven else None
            self._re_pair(
                myself, proven, peerid, relationship, secret, str(bearer or "")
            )
            return
        headers = getattr(self.request, "headers", None) or {}
        if not existing and str(headers.get("Authorization", "")).lower().startswith(
            "bearer "
        ):
            # A re-pair for a trust this actor does not hold: the initiator
            # pairs afresh (it removes its own row first), never by creating
            # a row here that the bearer could not have proven.
            logger.warning(
                f"Refused a re-pair for {peerid} at {myself.id}: no trust row"
            )
            self.response.set_status(403, "No trust to re-pair")
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

        # Trigger trust_request_received lifecycle hook to notify application of incoming trust request
        if self.hooks:
            try:
                logger.debug(
                    f"trust_request_received hook called for {actor_id} <- {peerid}, "
                    f"relationship={relationship}"
                )
                self.hooks.execute_lifecycle_hooks(
                    "trust_request_received",
                    actor=actor_interface,
                    peer_id=peerid,
                    relationship=relationship,
                    trust_data=new_trust,
                )
                logger.info(
                    f"trust_request_received hook triggered for {actor_id} <- {peerid}"
                )
            except Exception as e:  # folds DbError: hook after the trust committed
                logger.error(f"Error triggering trust_request_received hook: {e}")

        self.response.headers["Location"] = str(
            self.config.root
            + (myself.id or "")
            + "/trust/"
            + new_trust["relationship"]
            + "/"
            + new_trust["peerid"]
        )
        out = json.dumps(_trust_request_answer(new_trust))
        self.response.write(out)
        self.response.headers["Content-Type"] = "application/json"
        # The stored approval: auto-accept approves only a request that
        # verified (create_verified_trust). The created row's copy carries its
        # flags as the strings "true"/"false" (Trust.create).
        if str(new_trust.get("approved")).lower() == "true":
            self.response.set_status(201, "Created")
        else:
            self.response.set_status(202, "Accepted")

    def _re_pair(
        self,
        myself: Any,
        proven: bool,
        peerid: str,
        relationship: str,
        secret: str,
        bearer: str = "",
    ) -> None:
        """A trust request for a peer that already has a row.

        Accepted only from the peer itself, authenticated with the trust's
        current secret; then only the secret is swapped
        (``Actor.replace_trust_secret``). The answer follows the stored
        approval (201 or 202) and no ``trust_request_received`` hook runs: no
        new relationship was requested. Anything else answers 403 and
        changes nothing. ``proven``: the request authenticated as this peer
        (its bearer is the trust's current secret)."""
        reason = "the request did not carry the trust's current secret"
        new_trust = None
        if proven:
            new_trust, reason = myself.replace_trust_secret(
                peerid=peerid,
                relationship=relationship,
                secret=secret,
                proven_secret=bearer or None,
            )
        if not new_trust:
            # Never the body's base URI in the log: it is the requester's.
            logger.warning(
                f"Refused a re-pair for {peerid} at {myself.id}: {reason}; the "
                "trust is unchanged"
            )
            self.response.set_status(403, "Existing trust not verified")
            return
        logger.info(f"Re-paired {myself.id} with {peerid}: the secret was replaced")
        self.response.headers["Location"] = str(
            self.config.root
            + (myself.id or "")
            + "/trust/"
            + new_trust["relationship"]
            + "/"
            + new_trust["peerid"]
        )
        self.response.write(json.dumps(_trust_request_answer(new_trust)))
        self.response.headers["Content-Type"] = "application/json"
        if new_trust.get("approved"):
            self.response.set_status(201, "Created")
        else:
            self.response.set_status(202, "Accepted")


# Handling requests to specific relationships, e.g. /trust/friend/12f2ae53bd
class TrustPeerHandler(base_handler.BaseHandler):
    def get(self, actor_id, relationship, peerid):
        # A GET with a _method override changes state: refuse one a
        # page on another site started (see BaseHandler).
        if self._refuse_cross_site_override():
            return
        if self.request.get("_method") == "PUT":
            # Web UI method override for updating/approving trust
            self.put(actor_id, relationship, peerid)
            try:
                status = getattr(self.response, "status_code", 0)
            except Exception:  # folds DbError: no DB access
                status = 0
            if status in (200, 201, 202, 204):
                self.response.set_status(302, "Found")
                self.response.set_redirect(self._www_path(actor_id, "/trust"))
            return
        if self.request.get("_method") == "DELETE":
            # Perform deletion, then redirect back to the web UI trust page on success
            self.delete(actor_id, relationship, peerid)
            try:
                status = getattr(self.response, "status_code", 0)
            except Exception:  # folds DbError: no DB access
                status = 0
            if status in (200, 201, 202, 204):
                # Redirect to the trust overview so the browser view updates
                self.response.set_status(302, "Found")
                self.response.set_redirect(self._www_path(actor_id, "/trust"))
            return
        logger.debug("GET trust request received")
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
            path_peer=peerid,
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

        caller_peer = ""
        if isinstance(auth_result.auth_obj.acl, dict):
            caller_peer = auth_result.auth_obj.acl.get("peerid") or ""
        if not my_trust["approved"] and is_peer_token:
            if caller_peer != peerid:
                # Another peer (an ``admin`` one) on an unapproved row.
                if self.response:
                    self.response.set_status(403, "Trust relationship not approved")
                return
            # The row's own peer reads its status while the owner has not
            # approved it ("approved, pending", the spec's trust GET); an
            # initiator whose re-pair answer was lost reads it with the new
            # secret to learn that the swap happened (3.16).

        # Unlike the list route, this response keeps ``secret`` and
        # ``verification_token`` for the creator, the trustee and the peer the
        # row belongs to, the token to that peer only while the row is
        # approved: peer verification reads ``verification_token`` from this
        # route (Actor.create_verified_trust, actor.py), and only from an
        # approved row (3.16, the mirrored request). Any other peer,
        # an ``admin`` one included, never receives them: with another peer's
        # secret it could act as that peer, re-pair its trust and lock it
        # out (3.16). Client-supplied text is sanitised as on the list route.
        if isinstance(my_trust, dict):
            my_trust = _sanitize_trust_text(dict(my_trust))
            if caller_peer and caller_peer != peerid:
                my_trust.pop("secret", None)
                my_trust.pop("verification_token", None)
            elif caller_peer and not my_trust.get("approved"):
                # A pending row's own peer reads its status, never its token:
                # whoever filed the row chose its secret, and the token would
                # let it answer another actor's verification of a request it
                # filed there under our id (3.16). A verification reads an
                # initiator's own row, which is approved.
                my_trust.pop("verification_token", None)
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
                path_peer=peerid,
            ):
                if self.response:
                    self.response.set_status(403)
                return
        else:
            if not auth_result.authorize(
                "POST", "trust", "<type>/<id>", path_peer=peerid
            ):
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

        # Trigger trust_fully_approved_remote lifecycle hook when receiving peer approval notification
        # This is the critical step where Actor A (who initiated the trust) learns that
        # Actor B has approved, and can now create subscriptions
        logger.info(
            f"POST notification received: peer_approved={peer_approved}, "
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
                        logger.info(
                            f"Trust fully approved remotely via POST notification: {peerid} approved, completing relationship with {actor_id}"
                        )
                        from actingweb.interface.actor_interface import ActorInterface

                        actor_interface = ActorInterface(myself, self.config)
                        self.hooks.execute_lifecycle_hooks(
                            "trust_fully_approved_remote",
                            actor=actor_interface,
                            peer_id=peerid,
                            relationship=relationship,
                            trust_data=trust_data,
                        )
                        logger.info(
                            f"trust_fully_approved_remote hook triggered via POST for {actor_id} <-> {peerid}"
                        )
                    else:
                        logger.debug(
                            f"Trust not yet fully approved after POST: approved={trust_data.get('approved')}, "
                            f"peer_approved={trust_data.get('peer_approved')}"
                        )
            except Exception as e:  # folds DbError: hook after approval committed
                logger.error(
                    f"Error triggering trust_fully_approved_remote hook in POST handler: {e}"
                )

        if trust_updated:
            self.response.set_status(204, "Ok")
        else:
            self.response.set_status(500, "Not modified")

    def _refuse_unverified_approval(self, actor_id: str) -> None:
        """403 for an approval of an unverified request, with a body that
        says why: the web UI's Approve form (``_method=PUT``) gets a page
        with a way back to the trust list, an API client a JSON error."""
        if not self.response:
            return
        message = (
            "The trust request is not verified, so it cannot be approved. "
            "To pair with this peer, create the trust toward its URL."
        )
        self.response.set_status(
            403, "The trust request is not verified; it cannot be approved"
        )
        if self.request.get("_method") == "PUT":
            back = html.escape(self._www_path(actor_id, "/trust"), quote=True)
            self.response.headers["Content-Type"] = "text/html; charset=utf-8"
            self.response.write(
                f"<!doctype html><html><head><title>Not approved</title></head>"
                f"<body><p>{html.escape(message)}</p>"
                f'<p><a href="{back}">Back to trust relationships</a></p>'
                f"</body></html>"
            )
        else:
            self.response.headers["Content-Type"] = "application/json"
            self.response.write(json.dumps({"error": message}))

    def put(self, actor_id, relationship, peerid):
        auth_result = self.authenticate_actor(actor_id, "trust", subpath=relationship)
        if not auth_result.success:
            return
        myself = auth_result.actor
        if not auth_result.authorize("PUT", "trust", "<type>/<id>", path_peer=peerid):
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
                if str(params["approved"]).lower() == "true":
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
        from actingweb.trust import is_valid_peer_baseuri

        # Another peer's row (an ``admin`` peer is admitted to it) keeps its
        # base URI: it is where the trust's secret goes.
        put_acl = getattr(auth_result.auth_obj, "acl", None)
        put_caller = put_acl.get("peerid") if isinstance(put_acl, dict) else ""
        if (
            isinstance(put_caller, str)
            and put_caller
            and put_caller != peerid
            and baseuri
        ):
            logger.warning(
                f"Refused a peer's base URI change on another peer's trust row at "
                f"{actor_id}"
            )
            if self.response:
                self.response.set_status(403, "Forbidden")
            return
        # A peer on its own row (an application row may admit it) never
        # approves the relationship or writes its own permissions: those are
        # the owner's.
        if _is_non_admin_peer(auth_result.auth_obj) and (
            approved is not None or permission_updates is not None
        ):
            logger.warning(
                f"Refused a peer's PUT on its own trust row for {actor_id}: "
                "approval and permissions are the owner's"
            )
            if self.response:
                self.response.set_status(403, "Forbidden")
            return
        if baseuri and not is_valid_peer_baseuri(baseuri):
            # The peer may PUT its own row: the base URI it moves to must be
            # as plain as the one it was admitted with (it is fetched and
            # shown). Checked before the row is read, compared or fetched.
            if self.response:
                self.response.set_status(400, "Invalid baseuri")
            return
        current = myself.get_trust_relationship(peerid=peerid)
        if not current or str(current.get("relationship") or "") != str(
            relationship or ""
        ):
            # The relationship in the path must be the row's: nothing is
            # verified or written for a PUT that names another.
            if self.response:
                self.response.set_status(404, "Trust relationship not found")
            return
        if approved is True and not current.get("approved"):
            if baseuri and baseuri.rstrip("/") != str(
                current.get("baseuri") or ""
            ).rstrip("/"):
                # The second verification asks the stored base URI; a move in
                # the same request would approve a row checked elsewhere.
                if self.response:
                    self.response.set_status(
                        400, "Approve and change the base URI in two requests"
                    )
                return
            if not myself.reverify_pending_trust(peerid):
                # Only a verified request is approved (3.16): an unverified
                # row's secret is whatever its requester chose, and anyone can
                # file a request under a peer's id. Pair by creating the
                # trust toward the peer's URL instead.
                logger.warning(
                    f"Refused to approve the trust with {peerid} at {actor_id}: "
                    "the request is not verified"
                )
                self._refuse_unverified_approval(actor_id)
                return
        if (
            isinstance(put_caller, str)
            and put_caller
            and put_caller == peerid
            and baseuri
            and baseuri.rstrip("/")
            != str(
                (myself.get_trust_relationship(peerid=peerid) or {}).get("baseuri")
                or ""
            ).rstrip("/")
            and not myself._base_uri_serves(baseuri, peerid)
        ):
            # A peer moving its own row: the new base URI must name it on
            # /meta, as a creation's must (Actor.create_verified_trust), or
            # the trust's traffic would go to a host nobody checked.
            logger.warning(
                f"Refused a base URI move for {peerid} at {actor_id}: its /meta "
                "does not name the peer"
            )
            if self.response:
                self.response.set_status(400, "The base URI does not serve this peer")
            return
        # Use developer API - ActorInterface with TrustManager
        if actor_interface is None:
            actor_interface = self._get_actor_interface(myself)
            if not actor_interface:
                if self.response:
                    self.response.set_status(500, "Internal error")
                return

        # The permissions first, then the trust (3.16): a peer told of an
        # approval is never left on a grant that failed to store. The
        # override as it was is kept to restore it if the trust write fails.
        permission_store = None
        previous_override = None
        if (
            permission_updates is not None
            and PERMISSION_SYSTEM_AVAILABLE
            and get_trust_permission_store
        ):
            permission_store = get_trust_permission_store(self.config)
            # From the store, not the cache (3.16): a failed trust write
            # restores this, and a stale entry would write it back over a
            # live override (or delete one).
            previous_override = permission_store.get_permissions_uncached(
                actor_id, peerid
            )
            try:
                # Stored silently: the peer is told once the trust write
                # landed (below), never of a grant a failed write rolls back.
                if previous_override:
                    permissions_updated = permission_store.update_permissions(
                        actor_id, peerid, permission_updates, notify_peer=False
                    )
                elif create_permission_override:
                    permissions_updated = permission_store.store_permissions(
                        create_permission_override(
                            actor_id=actor_id,
                            peer_id=peerid,
                            trust_type=relationship,  # Use relationship as trust type
                            permission_updates=permission_updates,
                        ),
                        notify_peer=False,
                    )
                else:
                    permissions_updated = False
            except DbError:
                raise
            except Exception as e:
                logger.error(
                    f"Error updating permissions for trust relationship {actor_id}:{peerid}: {e}"
                )
                permissions_updated = False
            if not permissions_updated:
                # Stopped before the trust write: the row stays as it was
                # (unapproved when this was its approval), the peer is not told.
                logger.warning(
                    f"Permissions update failed for actor={actor_id}, peer={peerid}"
                )
                self.response.set_status(500, "Failed to update permissions")
                return

        trust_updated = False
        try:
            trust_updated = actor_interface.trust.modify_and_notify(
                peer_id=peerid,
                relationship=relationship,
                baseuri=baseuri,
                approved=approved,
                description=desc,
            )
        finally:
            if permission_store is not None and not trust_updated:
                # The trust was not written: the override goes back to what
                # it was (an override on an unapproved row grants nothing).
                if previous_override:
                    permission_store.store_permissions(
                        previous_override, notify_peer=False
                    )
                else:
                    permission_store.delete_permissions(actor_id, peerid)

        if trust_updated and permission_store is not None:
            permission_store.notify_stored_grant(actor_id, peerid)

        if trust_updated and approved is True:
            # trust_fully_approved_local, once, on this approval completing
            # the mutual trust (a repeat PUT fires nothing).
            try:
                after = myself.get_trust_relationships(
                    relationship=relationship, peerid=peerid
                )
            except DbError as e:  # folds DbError: hook after the approval committed
                logger.error(f"Approval hook for {peerid} skipped: {e}")
                after = []
            actor_interface.trust.fire_approved(
                peerid, current, after[0] if after else None
            )

        if trust_updated:
            self.response.set_status(204, "Ok")
            return
        # Trust modification failed - check if it's because trust doesn't
        # exist or because of a validation error
        relationships = myself.get_trust_relationships(
            relationship=relationship, peerid=peerid
        )
        if not relationships:
            logger.warning(
                f"Trust modification failed: no trust relationship found for "
                f"actor={actor_id}, peer={peerid}, relationship={relationship}"
            )
            self.response.set_status(404, "Trust relationship not found")
        else:
            logger.warning(
                f"Trust modification failed for actor={actor_id}, peer={peerid}, "
                f"relationship={relationship} (trust exists but modify failed)"
            )
            self.response.set_status(400, "Failed to modify trust relationship")

    def delete(self, actor_id, relationship, peerid):
        # Use AuthResult for granular control since we need add_response=False and custom logic
        auth_result = self.authenticate_actor(
            actor_id, "trust", subpath=relationship, add_response=False
        )

        # Special case: if actor doesn't exist, return 404 for delete_reciprocal_trust cleanup
        # This allows the peer to clean up orphaned relationships when the remote actor no longer exists
        if not auth_result.actor:
            logger.info(
                f"DELETE trust: actor {actor_id} not found, returning 404 for cleanup"
            )
            if self.response:
                self.response.set_status(404, "Not found")
            return

        # Special handling: if authentication failed but actor was loaded,
        # check if relationship exists. If not, return 404 instead of auth error.
        # This allows cleanup of orphaned relationships during delete_reciprocal_trust.
        if auth_result.actor and (
            not auth_result.auth_obj
            or (
                auth_result.auth_obj.response["code"] != 200
                and auth_result.auth_obj.response["code"] != 401
            )
        ):
            # Actor loaded but auth failed - check if relationship exists
            relationships = auth_result.actor.get_trust_relationships(
                relationship=relationship, peerid=peerid
            )
            logger.debug(
                f"DELETE trust auth failed, checking relationship: actor={actor_id}, "
                f"peerid={peerid}, found={len(relationships) if relationships else 0}"
            )
            if not relationships or len(relationships) == 0:
                # Relationship doesn't exist - return 404 (expected by delete_reciprocal_trust)
                logger.info(
                    f"Trust relationship not found after auth failure: actor={actor_id}, "
                    f"peerid={peerid}, returning 404"
                )
                if self.response:
                    self.response.set_status(404, "Not found")
                return
            # Relationship exists but auth failed - return auth error
            auth.add_auth_response(appreq=self, auth_obj=auth_result.auth_obj)
            return

        # Actor loaded but auth_obj missing (should not happen, but handle gracefully)
        if not auth_result.auth_obj:
            logger.warning(
                f"DELETE trust: actor {actor_id} loaded but auth_obj missing"
            )
            if self.response:
                self.response.set_status(500, "Internal server error")
            return

        myself = auth_result.actor

        # Check if relationship exists BEFORE authorization
        # This ensures we return 404 (not 403) when peer tries to delete non-existent relationship
        # The delete_reciprocal_trust flow expects 404 for missing relationships
        relationships = myself.get_trust_relationships(
            relationship=relationship, peerid=peerid
        )
        logger.debug(
            f"DELETE trust check: actor={actor_id}, peerid={peerid}, "
            f"relationship={relationship}, found={len(relationships) if relationships else 0} relationships"
        )
        if not relationships or len(relationships) == 0:
            logger.info(
                f"Trust relationship not found for deletion: actor={actor_id}, peerid={peerid}, "
                f"returning 404"
            )
            if self.response:
                self.response.set_status(404, "Not found")
            return

        # We allow non-approved peers to delete even if we haven't approved the relationship yet
        if not auth_result.auth_obj.check_authorisation(
            path="trust",
            subpath="<type>/<id>",
            method="DELETE",
            peerid=peerid,
            approved=False,
            path_peer=peerid,
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
        # ?notify=false: the creator removes the local row and its cascade
        # without contacting the peer (a dead or unreachable peer).
        local_only = (self.request.get("notify") or "").lower() == "false"
        if local_only and (
            str(auth_result.auth_obj.acl.get("relationship") or "").lower() != "creator"
        ):
            if self.response:
                self.response.set_status(403, "Forbidden")
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

        # Use developer API - ActorInterface with TrustManager
        actor_interface = self._get_actor_interface(myself)
        if not actor_interface:
            if self.response:
                self.response.set_status(500, "Internal error")
            return

        # Delete the row this request was authorised against, and only that
        # one (3.16): a re-pair that replaced it meanwhile keeps its row (the
        # request answers 404). A peer's bearer names its row's secret; the
        # creator acted on the row read above.
        bearer_row = (
            auth_result.auth_obj.trust
            if auth_result.auth_obj
            and auth_result.auth_obj.trust
            and auth_result.auth_obj.trust.get("peerid") == peerid
            else None
        )
        expected_secret = (
            str((bearer_row or relationships[0]).get("secret") or "") or None
        )
        if expected_secret is not None and not secret_equals(
            str(relationships[0].get("secret") or ""), expected_secret
        ):
            # The bearer authenticated against a row since replaced (a stale
            # index entry): no hook fires for the new row, nothing is deleted.
            if self.response:
                self.response.set_status(404, "Not found")
            return

        # trust_deleted fires through TrustManager.fire_deleted (the row as
        # trust_data) after the delete's last secret check and before
        # anything local goes (3.16): a delete that loses to a re-pair fires
        # nothing for the row that stands.
        def before_local_delete(row: dict[str, Any]) -> None:
            # fire_deleted logs a hook's error and lets a DbError through.
            if self.hooks:
                actor_interface.trust.fire_deleted(row, initiated_by_peer=is_peer)

        from ..actor import TrustReplaced

        try:
            if local_only:
                deleted = myself.delete_reciprocal_trust(
                    peerid=peerid,
                    notify_peers=False,
                    expected_secret=expected_secret,
                    before_local_delete=before_local_delete,
                )
            elif is_peer:
                deleted = actor_interface.trust.delete_peer_trust(
                    peer_id=peerid,
                    notify_peer=False,
                    expected_secret=expected_secret,
                    before_local_delete=before_local_delete,
                )
            else:
                deleted = actor_interface.trust.delete_peer_trust(
                    peer_id=peerid,
                    notify_peer=True,
                    expected_secret=expected_secret,
                    before_local_delete=before_local_delete,
                )
        except TrustReplaced:
            logger.info(
                f"Trust {actor_id}:{peerid} was replaced while being deleted; kept"
            )
            if self.response:
                self.response.set_status(404, "Not found")
            return
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
            logger.error(
                f"TrustPermissionHandler auth failed: actor={auth_result.actor is not None}, auth_obj={auth_result.auth_obj is not None}, code={auth_result.auth_obj.response['code'] if auth_result.auth_obj else 'None'}"
            )
            return

        # Same authorization as trust endpoint
        if not auth_result.authorize("GET", "trust", "<type>/<id>", path_peer=peerid):
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
                    logger.debug(f"Looking up trust type '{relationship}' in registry")
                    trust_type = registry.get_type(relationship)

                    if not trust_type:
                        logger.error(
                            f"Trust type '{relationship}' not found in registry"
                        )
                        available_types = (
                            [t.name for t in registry.list_types()] if registry else []
                        )
                        logger.error(f"Available trust types: {available_types}")
                        if self.response:
                            self.response.set_status(
                                404, f"Trust type '{relationship}' not found"
                            )
                        return

                    logger.debug(
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
                except DbError:
                    raise
                except Exception as registry_error:
                    logger.error(
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

        except DbError:
            raise
        except Exception as e:
            logger.error(f"Error retrieving permissions for {actor_id}:{peerid}: {e}")
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
        if not auth_result.authorize("PUT", "trust", "<type>/<id>", path_peer=peerid):
            return
        # A peer never writes its own permissions (they are the owner's grant).
        if _is_non_admin_peer(auth_result.auth_obj):
            if self.response:
                self.response.set_status(403, "Forbidden")
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
            logger.error(f"Invalid JSON in permission request: {e}")
            if self.response:
                self.response.set_status(400, "Invalid JSON")
        except DbError:
            raise
        except Exception as e:
            logger.error(f"Error updating permissions for {actor_id}:{peerid}: {e}")
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
        if not auth_result.authorize(
            "DELETE", "trust", "<type>/<id>", path_peer=peerid
        ):
            return
        # A peer never resets its own permissions (they are the owner's grant).
        if _is_non_admin_peer(auth_result.auth_obj):
            if self.response:
                self.response.set_status(403, "Forbidden")
            return

        try:
            permission_store = get_trust_permission_store(self.config)
            # Read first, from the store (3.16): a delete of nothing is 404
            # and tells the peer nothing (the store answered True for an
            # absent row, so the 404 never came).
            existing = permission_store.get_permissions_uncached(actor_id, peerid)
            if not existing:
                self.response.set_status(404, "No permissions found")
                return
            if not permission_store.delete_permissions(actor_id, peerid):
                self.response.set_status(500, "Failed to delete permissions")
                return
            # The peer's grant is back to its type's default: it is told, as
            # a PUT of the grant tells it (spec: a permission change is
            # pushed to the peer).
            permission_store.notify_default_grant(
                actor_id, peerid, existing.trust_type or relationship
            )
            self.response.set_status(204, "Deleted")

        except DbError:
            raise
        except Exception as e:
            logger.error(f"Error deleting permissions for {actor_id}:{peerid}: {e}")
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
        # A peer this actor has not approved is granted nothing to list
        # (3.16; it got the same answer as an approved one). Only an explicit
        # False, as the grant snapshot reads it (a row from before the field
        # is approved there, and every other route admits it).
        if trust_rel.get("approved") is False:
            if self.response:
                self.response.set_status(403, "Forbidden")
                self.response.headers["Content-Type"] = "application/json"
                self.response.write(json.dumps({"error": "not_approved"}))
            return

        # Get permission evaluator (one that cannot be built is a 503)
        try:
            evaluator = (
                get_permission_evaluator(self.config)
                if PERMISSION_SYSTEM_AVAILABLE
                else None
            )
        except DbError:
            raise
        except Exception as e:
            logger.error(f"shared_properties: evaluator unavailable: {e}")
            evaluator = None
        if not evaluator:
            if self.response:
                self.response.set_status(503, "Permission system not available")
            return

        # Get all properties to check
        all_properties = myself.get_properties()
        property_names = list(all_properties.keys()) if all_properties else []

        # Also check property lists (distributed storage). list_all_with_rows()
        # pays for one whole-partition dump and returns it alongside the
        # names, so each list's item count below is served from that dump
        # instead of a second whole-list Query per list property -- and,
        # unlike the previous `getattr(..., prop_name, None)` probe, only
        # actual list names pay for a count at all: that probe silently
        # succeeded for every property name (list or not), because
        # PropertyListStore.__getattr__ hands back a wrapper for any name.
        actor_interface = None
        list_names: list[str] = []
        list_rows: dict[str, str] = {}
        try:
            from actingweb.interface.actor_interface import ActorInterface

            actor_interface = ActorInterface(myself, self.config)
            if hasattr(actor_interface, "property_lists"):
                list_names, list_rows = (
                    actor_interface.property_lists.list_all_with_rows()
                )
                property_names.extend(list_names)
        except DbError:
            raise
        except Exception as e:
            logger.debug(f"Could not get property lists: {e}")

        list_name_set = set(list_names)

        # Remove duplicates
        property_names = list(set(property_names))

        # The names the peer may read, decided as a read of each is (3.16:
        # the operation was "subscribe", which no rule grants, so nothing was
        # ever listed); one grant read for all.
        from ..access_decision import decide

        shared = []
        try:
            snapshot = evaluator.snapshot(actor_id, peerid)
        except DbError:
            raise
        except Exception as e:
            logger.error(f"shared_properties: grant for {peerid} unreadable: {e}")
            if self.response:
                self.response.set_status(503, "Permission system not available")
            return

        for prop_name in sorted(property_names):
            if decide(
                self.config,
                actor_id,
                peerid,
                "properties",
                prop_name,
                "read",
                evaluator=evaluator,
                snapshot=snapshot,
            ).allowed:
                # Get item count if it's a property list
                item_count = 0
                if prop_name in list_name_set and actor_interface is not None:
                    try:
                        prop_list = getattr(actor_interface.property_lists, prop_name)
                        prop_list.prime_from_rows(list_rows)
                        item_count = len(prop_list)
                    except DbError:
                        raise
                    except Exception as e:
                        logger.debug(
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

        # The names the peer may not read are not listed: naming them told
        # it what else the actor holds (3.16).
        response_data = {
            "actor_id": actor_id,
            "peer_id": peerid,
            "relationship": relationship,
            "shared_properties": shared,
        }

        if self.response:
            self.response.write(json.dumps(response_data))
            self.response.headers["Content-Type"] = "application/json"
            self.response.set_status(200)
