import json
import logging

from actingweb import deletion
from actingweb.handlers import base_handler

logger = logging.getLogger(__name__)


class RootHandler(base_handler.BaseHandler):
    def _wants_html(self) -> bool:
        """Check if client prefers HTML response (browser)."""
        # Check Accept header - browsers typically send text/html
        # Use get_header() for case-insensitive lookup (FastAPI normalizes to lowercase)
        accept = self.request.get_header("Accept") or ""
        if "text/html" in accept:
            return True

        return False

    def get(self, actor_id):
        if self.request.get("_method") == "DELETE":
            self.delete(actor_id)
            return
        # Authenticate and authorize separately like DELETE method
        auth_result = self.authenticate_actor(actor_id, "")
        if not auth_result.success:
            # For browser requests, redirect to /login instead of returning auth error
            # This provides better UX than throwing users directly into OAuth flow
            if self._wants_html():
                # Build full URL for redirect - config.root includes protocol, host, and any base path
                full_login_url = f"{self.config.root.rstrip('/')}/login"
                self.response.set_redirect(full_login_url)
                self.response.headers["Location"] = full_login_url
                self.response.set_status(302, "Found")
            return  # Response already set (either our redirect or auth error)
        if not auth_result.authorize("GET", "/"):
            return  # Response already set
        myself = auth_result.actor

        # Content negotiation: redirect for browsers, JSON for API clients
        if self._wants_html():
            # Browser request - redirect based on config
            actor_id_str = myself.id or ""
            if self.config.ui:
                # Web UI enabled - redirect to /www
                redirect_path = f"/{actor_id_str}/www"
            else:
                # Web UI disabled - redirect to /app (for SPAs)
                redirect_path = f"/{actor_id_str}/app"

            if self.response:
                # Build full URL for redirect - config.root includes protocol, host, and any base path
                # The integration uses response.redirect directly for RedirectResponse
                full_redirect_url = f"{self.config.root.rstrip('/')}{redirect_path}"
                self.response.set_redirect(full_redirect_url)
                self.response.headers["Location"] = full_redirect_url
                self.response.set_status(302, "Found")
            return

        # API client - return JSON
        pair = {
            "id": myself.id,
            "creator": myself.creator,
            "passphrase": myself.passphrase,
        }
        trustee_root = myself.store.trustee_root if myself.store else None
        if trustee_root and len(trustee_root) > 0:
            pair["trustee_root"] = trustee_root
        out = json.dumps(pair)
        if self.response:
            self.response.write(out)
        self.response.headers["Content-Type"] = "application/json"
        self.response.set_status(200)

    def delete(self, actor_id):
        # Alternative: more control with AuthResult
        auth_result = self.authenticate_actor(actor_id, "")
        if not auth_result.success:
            return  # Response already set
        if not auth_result.authorize("DELETE", "/"):
            return  # Response already set
        myself = auth_result.actor
        deleted_actor_id = myself.id

        # Tombstone BEFORE the pre-delete hook, not just before the wipe.
        # actor_deleted is where an application calls an external API to cancel
        # a subscription, and that provider's callback can arrive while the
        # call is still in flight — i.e. before Actor.delete() has run its own
        # mark_actor_deleted(). That is not a corner case: it is the exact
        # sequence that produced the orphan rows this feature exists to stop.
        # Actor.delete() still writes its own tombstone, which covers
        # programmatic deletion; the two are idempotent (a plain overwrite).
        #
        # AuthResult.success guarantees a non-None actor but not a non-None id,
        # and mark_actor_deleted() treats a falsy id as "nothing to do" — which
        # would put us back to the un-tombstoned behaviour with no signal. This
        # release is about not having silent no-ops in this area, so say so.
        if deleted_actor_id:
            deletion.mark_actor_deleted(deleted_actor_id, self.config)
        else:
            logger.error(
                "Authorized DELETE for an actor with no id; no deletion "
                "tombstone written. Late writes for it cannot be suppressed."
            )

        # actor_deleted runs BEFORE any data is removed — it is the only place
        # the actor's own data is still readable, so it is where an application
        # reads what it needs (e.g. a stored external subscription id).
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                self.hooks.execute_lifecycle_hooks("actor_deleted", actor_interface)

        myself.delete()

        # actor_deleted_complete runs AFTER the wipe. External side effects
        # belong here, not in actor_deleted: an API call made there triggers a
        # provider callback that races the wipe and lands while the actor still
        # resolves, writing rows that outlive the actor. There is deliberately
        # no ActorInterface to hand over — the actor is gone.
        if self.hooks and deleted_actor_id:
            self.hooks.execute_lifecycle_hooks(
                "actor_deleted_complete", None, actor_id=deleted_actor_id
            )

        self.response.set_status(204)
        return
