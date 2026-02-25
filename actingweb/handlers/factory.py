import json
import logging

from actingweb import actor
from actingweb.db import get_actor
from actingweb.handlers import base_handler

logger = logging.getLogger(__name__)


class RootFactoryHandler(base_handler.BaseHandler):
    def _wants_json(self) -> bool:
        """Check if client prefers JSON response."""
        # Check Accept header
        if self.request.headers:
            accept = self.request.headers.get("Accept", "")
            if "application/json" in accept:
                return True

        # Check format query parameter
        if self.request.get("format") == "json":
            return True

        return False

    def _get_json_config(self):
        """
        Return JSON configuration for SPAs doing user login.

        GET /?format=json or with Accept: application/json

        Returns JSON with:
        - oauth_enabled: Whether OAuth is configured
        - oauth_providers: List of available OAuth providers with URLs
        - spa_mode_supported: Always true
        - endpoints: OAuth endpoint URLs

        Note: Trust types are NOT included here because this endpoint is for
        user login/actor creation, not for MCP client authorization.
        For MCP authorization trust types, use /oauth/authorize which handles
        MCP client authorization flows.
        """
        base_url = f"{self.config.proto}{self.config.fqdn}"

        # Build OAuth provider list
        oauth_urls = {}
        oauth_providers = []
        oauth_enabled = False

        try:
            from actingweb.oauth2 import create_oauth2_authenticator

            providers_cfg = getattr(self.config, "oauth_providers", {})
            provider_names: list[str] = []
            if providers_cfg:
                provider_names = list(providers_cfg.keys())
            elif self.config.oauth and self.config.oauth.get("client_id"):
                provider_names = [getattr(self.config, "oauth2_provider", "google")]

            for prov_name in provider_names:
                auth = create_oauth2_authenticator(self.config, prov_name)
                if auth.is_enabled():
                    auth_url = auth.create_authorization_url()
                    oauth_urls[prov_name] = auth_url
                    oauth_providers.append(
                        {
                            "name": prov_name,
                            "display_name": prov_name.capitalize()
                            if prov_name != "github"
                            else "GitHub",
                            "authorization_url": auth_url,
                            "authorization_endpoint": auth.provider.auth_uri,
                        }
                    )
                    oauth_enabled = True

        except Exception as e:
            logger.warning(f"Failed to generate OAuth URLs for JSON config: {e}")

        # Build response
        response_data = {
            "oauth_enabled": oauth_enabled,
            "oauth_providers": oauth_providers,
            "spa_mode_supported": True,
            "pkce_supported": True,
            "token_delivery_modes": ["json", "cookie", "hybrid"],
            "refresh_token_rotation": True,
            "endpoints": {
                # Unified OAuth endpoints (JSON API)
                "config": f"{base_url}/oauth/config",
                "callback": f"{base_url}/oauth/callback",
                "revoke": f"{base_url}/oauth/revoke",
                "session": f"{base_url}/oauth/session",
                "logout": f"{base_url}/oauth/logout",
                # SPA-specific (different purpose than MCP OAuth2)
                "spa_authorize": f"{base_url}/oauth/spa/authorize",
                "spa_token": f"{base_url}/oauth/spa/token",
                # MCP OAuth2 server endpoints
                "mcp_authorize": f"{base_url}/oauth/authorize",
                "mcp_token": f"{base_url}/oauth/token",
                # Email form endpoint
                "email_form": f"{base_url}/oauth/email",
            },
            "discovery": {
                "authorization_server": f"{base_url}/.well-known/oauth-authorization-server",
                "protected_resource": f"{base_url}/.well-known/oauth-protected-resource",
            },
            "web_ui_enabled": bool(self.config.ui),
        }

        # Write JSON response
        self.response.write(json.dumps(response_data))
        self.response.headers["Content-Type"] = "application/json"
        self.response.set_status(200)

        # Set CORS headers for SPA access
        if self.request.headers:
            origin = self.request.headers.get("Origin", "*")
            self.response.headers["Access-Control-Allow-Origin"] = origin
        self.response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        self.response.headers["Access-Control-Allow-Headers"] = (
            "Authorization, Content-Type, Accept"
        )
        self.response.headers["Access-Control-Allow-Credentials"] = "true"

        return response_data

    def get(self):
        if self.request.get("_method") == "POST":
            self.post()
            return

        # Check if JSON response is requested (for SPAs)
        if self._wants_json():
            return self._get_json_config()

        if self.config.ui:
            # Provide OAuth login URLs for 3rd party apps to render "Login with Google/GitHub" buttons
            oauth_urls = {}
            oauth_providers = []

            try:
                from actingweb.oauth2 import create_oauth2_authenticator

                providers_cfg = getattr(self.config, "oauth_providers", {})
                provider_names: list[str] = []
                if providers_cfg:
                    provider_names = list(providers_cfg.keys())
                elif self.config.oauth and self.config.oauth.get("client_id"):
                    provider_names = [getattr(self.config, "oauth2_provider", "google")]

                for prov_name in provider_names:
                    auth = create_oauth2_authenticator(self.config, prov_name)
                    if auth.is_enabled():
                        auth_url = auth.create_authorization_url()
                        oauth_urls[prov_name] = auth_url
                        oauth_providers.append(
                            {
                                "name": prov_name,
                                "display_name": prov_name.capitalize()
                                if prov_name != "github"
                                else "GitHub",
                                "url": auth_url,
                            }
                        )
                        logger.debug(
                            f"{prov_name} OAuth URL generated: {auth_url[:100]}..."
                        )

            except Exception as e:
                logger.warning(f"Failed to generate OAuth URLs: {e}")

            self.response.template_values = {
                "oauth_urls": oauth_urls,  # Dict: {'google': url, 'github': url}
                "oauth_providers": oauth_providers,  # List of dicts with name, display_name, url
                "oauth_enabled": bool(oauth_urls),
            }
        else:
            self.response.set_status(404)

    def post(self):
        try:
            body = self.request.body
            if isinstance(body, bytes):
                body = body.decode("utf-8", "ignore")
            elif body is None:
                body = "{}"
            params = json.loads(body)
            is_json = True
            if "creator" in params:
                creator = params["creator"]
            else:
                creator = ""
            if "trustee_root" in params:
                trustee_root = params["trustee_root"]
            else:
                trustee_root = ""
            if "passphrase" in params:
                passphrase = params["passphrase"]
            else:
                passphrase = ""
        except ValueError:
            is_json = False
            creator = self.request.get("creator")
            trustee_root = self.request.get("trustee_root")
            passphrase = self.request.get("passphrase")

        # Normalise creator when using email login flow
        if isinstance(creator, str):
            creator = creator.strip()
            if "@" in creator:
                creator = creator.lower()

        if not is_json and creator:
            existing_actor = actor.Actor(config=self.config)
            if existing_actor.get_from_creator(creator):
                actor_id = existing_actor.id or ""
                redirect_target = f"/{actor_id}/www"
                if self.response:
                    self.response.set_redirect(redirect_target)
                    self.response.headers["Location"] = (
                        f"{self.config.root}{actor_id}/www"
                    )
                    self.response.set_status(302, "Found")
                return

        # Create actor using enhanced method with hooks and trustee_root
        myself = actor.Actor(config=self.config)
        if not myself.create(
            url=self.request.url or "",
            creator=creator,
            passphrase=passphrase,
            trustee_root=trustee_root,
            hooks=self.hooks,
        ):
            # Check if this is a unique creator constraint violation
            if self.config and self.config.unique_creator and creator:
                # Check if creator already exists
                in_db = get_actor(self.config)
                exists = in_db.get_by_creator(creator=creator)
                if exists:
                    self.response.set_status(403, "Creator already exists")
                    logger.warning(
                        "Creator already exists, cannot create new Actor("
                        + str(self.request.url)
                        + " "
                        + str(creator)
                        + ")"
                    )
                    return

            # Generic creation failure
            self.response.set_status(400, "Not created")
            logger.warning(
                "Was not able to create new Actor("
                + str(self.request.url)
                + " "
                + str(creator)
                + ")"
            )
            return
        self.response.headers["Location"] = str(self.config.root + (myself.id or ""))
        if self.config.www_auth == "oauth" and not is_json:
            self.response.set_redirect(self.config.root + (myself.id or "") + "/www")
            return
        pair = {
            "id": myself.id,
            "creator": myself.creator,
            "passphrase": str(myself.passphrase),
        }
        if trustee_root and isinstance(trustee_root, str) and len(trustee_root) > 0:
            pair["trustee_root"] = trustee_root
        if self.config.ui and not is_json:
            self.response.template_values = pair
            return
        out = json.dumps(pair)
        self.response.write(out)
        self.response.headers["Content-Type"] = "application/json"
        self.response.set_status(201, "Created")
