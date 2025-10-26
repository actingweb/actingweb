import json
import logging
from builtins import str

from actingweb import actor
from actingweb.handlers import base_handler


class RootFactoryHandler(base_handler.BaseHandler):

    def get(self):
        if self.request.get("_method") == "POST":
            self.post()
            return
        if self.config.ui:
            # Provide OAuth login URLs for 3rd party apps to render "Login with Google/GitHub" buttons
            oauth_urls = {}
            oauth_providers = []

            # Check if OAuth is configured
            if self.config.oauth and self.config.oauth.get("client_id"):
                try:
                    from actingweb.oauth2 import create_google_authenticator, create_github_authenticator

                    # Determine which provider(s) to support based on configuration
                    oauth2_provider = getattr(self.config, 'oauth2_provider', 'google')

                    if oauth2_provider == 'google':
                        google_auth = create_google_authenticator(self.config)
                        if google_auth.is_enabled():
                            oauth_urls['google'] = google_auth.create_authorization_url()
                            oauth_providers.append({
                                'name': 'google',
                                'display_name': 'Google',
                                'url': oauth_urls['google']
                            })
                            logging.debug(f"Google OAuth URL generated: {oauth_urls['google'][:100]}...")

                    elif oauth2_provider == 'github':
                        github_auth = create_github_authenticator(self.config)
                        if github_auth.is_enabled():
                            oauth_urls['github'] = github_auth.create_authorization_url()
                            oauth_providers.append({
                                'name': 'github',
                                'display_name': 'GitHub',
                                'url': oauth_urls['github']
                            })
                            logging.debug(f"GitHub OAuth URL generated: {oauth_urls['github'][:100]}...")

                    # Support multiple providers if configured (future enhancement)
                    # Apps can extend this by checking additional config flags

                except Exception as e:
                    logging.warning(f"Failed to generate OAuth URLs: {e}")

            self.response.template_values = {
                'oauth_urls': oauth_urls,  # Dict: {'google': url, 'github': url}
                'oauth_providers': oauth_providers,  # List of dicts with name, display_name, url
                'oauth_enabled': bool(oauth_urls)
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
                    self.response.headers["Location"] = f"{self.config.root}{actor_id}/www"
                    self.response.set_status(302, "Found")
                return

        # Create actor using enhanced method with hooks and trustee_root
        myself = actor.Actor(config=self.config)
        if not myself.create(
            url=self.request.url or "",
            creator=creator,
            passphrase=passphrase,
            trustee_root=trustee_root,
            hooks=self.hooks
        ):
            # Check if this is a unique creator constraint violation
            if self.config and self.config.unique_creator and creator:
                # Check if creator already exists
                in_db = self.config.DbActor.DbActor()
                exists = in_db.get_by_creator(creator=creator)
                if exists:
                    self.response.set_status(403, "Creator already exists")
                    logging.warning(
                        "Creator already exists, cannot create new Actor("
                        + str(self.request.url)
                        + " "
                        + str(creator)
                        + ")"
                    )
                    return

            # Generic creation failure
            self.response.set_status(400, "Not created")
            logging.warning(
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
