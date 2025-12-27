import json

from actingweb.handlers import base_handler


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
        # Execute actor deletion lifecycle hook
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                self.hooks.execute_lifecycle_hooks("actor_deleted", actor_interface)

        myself.delete()
        self.response.set_status(204)
        return
