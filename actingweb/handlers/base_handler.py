from typing import TYPE_CHECKING, Any, Optional

from actingweb import aw_web_request
from actingweb import config as config_class

if TYPE_CHECKING:
    from actingweb.interface.actor_interface import ActorInterface
    from actingweb.interface.authenticated_views import AuthenticatedActorView
    from actingweb.interface.hooks import HookRegistry


class BaseHandler:
    def __init__(
        self,
        webobj: aw_web_request.AWWebObj = aw_web_request.AWWebObj(),
        config: config_class.Config = config_class.Config(),
        hooks: Optional["HookRegistry"] = None,
    ) -> None:
        self.request = webobj.request
        self.response = webobj.response
        self.config = config
        self.hooks = hooks

    # --- Cross-site requests --------------------------------------------
    #
    # A browser sends session cookies (SameSite=Lax rides along on a
    # top-level GET from any site) and cached basic-auth credentials with a
    # request another site starts, and the integrations turn the
    # ``oauth_token`` cookie into a Bearer header. So a request that changes
    # state from a browser must show it came from this app's own origin.

    def _www_path(self, actor_id: str, suffix: str = "") -> str:
        """``/<base>/<actor_id>/www`` plus ``suffix``: the web UI's path,
        with the deployment's base path from ``config.root``, for redirects
        and back links."""
        from urllib.parse import urlsplit

        base = urlsplit(getattr(self.config, "root", "") or "").path.rstrip("/")
        return f"{base}/{actor_id}/www{suffix}"

    def _same_origin(self, url: str) -> bool:
        """Whether ``url``'s origin (scheme, host, port) is this app's own,
        from ``config.root``: case-insensitive host, default ports filled
        in, any base path ignored (an origin has none)."""
        from urllib.parse import urlsplit

        def origin(value: str) -> tuple[str, str, int | None]:
            parts = urlsplit(value)
            scheme = (parts.scheme or "").lower()
            try:
                port = parts.port
            except ValueError:
                port = -1
            if port is None:
                port = {"https": 443, "http": 80}.get(scheme)
            return scheme, (parts.hostname or "").lower(), port

        return origin(url) == origin(getattr(self.config, "root", "") or "")

    def _session_cookie_auth(self) -> bool:
        """Whether this request authenticates with the web UI's session
        cookie (the integrations copy ``oauth_token`` into a Bearer header
        when no Authorization header was sent)."""
        cookies = getattr(self.request, "cookies", None) or {}
        token = cookies.get("oauth_token")
        if not token:
            return False
        auth = self.request.get_header("Authorization")
        return not auth or auth == f"Bearer {token}"

    def _cross_site_refused(self, require_evidence: bool = False) -> bool:
        """True when a state-changing request comes from another site.

        ``Sec-Fetch-Site`` decides when the browser sends it (every current
        one): ``same-origin`` passes, and so does ``none`` (typed, or a
        bookmark) unless ``require_evidence``. Without it, an ``Origin``,
        then a ``Referer``, must be this app's origin (``config.root``; a
        base path does not matter), and ``Origin: null`` is refused. A
        request with none of the three passes (a script, ``curl``, a peer),
        except, with ``require_evidence``, one that authenticates with the
        session cookie: only a browser holds it.

        ``require_evidence`` is for a GET that changes state (a ``_method``
        override): a link opened from a mail client arrives as ``none``,
        and a no-referrer link from a browser without Fetch Metadata
        arrives with no headers at all.
        """
        fetch_site = (self.request.get_header("Sec-Fetch-Site") or "").lower()
        if fetch_site:
            allowed = ("same-origin",) if require_evidence else ("same-origin", "none")
            return fetch_site not in allowed
        origin = self.request.get_header("Origin")
        if origin:
            return origin == "null" or not self._same_origin(origin)
        referer = self.request.get_header("Referer")
        if referer:
            return not self._same_origin(referer)
        return require_evidence and self._session_cookie_auth()

    def _refuse_cross_site(self, require_evidence: bool = False) -> bool:
        """Answer 403 for a cross-site state-changing request; True when it
        did."""
        if not self._cross_site_refused(require_evidence):
            return False
        self.response.set_status(403, "Cross-site request refused")
        self.response.headers["Content-Type"] = "text/plain; charset=utf-8"
        self.response.write("Cross-site request refused")
        return True

    def _refuse_cross_site_override(self) -> bool:
        """For a GET handler: True (403 answered) when the request carries a
        ``_method`` override and does not show it came from this app's own
        pages. A GET that changes state must never be startable by a link
        on another site; a real PUT/POST/DELETE is not affected."""
        if not self.request.get("_method"):
            return False
        return self._refuse_cross_site(require_evidence=True)

    def _get_actor_interface(self, actor) -> Optional["ActorInterface"]:
        """Get ActorInterface wrapper for given actor."""
        if actor:
            from actingweb.interface.actor_interface import ActorInterface

            registry = getattr(self.config, "service_registry", None)
            return ActorInterface(actor, service_registry=registry, hooks=self.hooks)
        return None

    def _get_authenticated_view(
        self, actor, auth_result: "AuthResult"
    ) -> "AuthenticatedActorView | None":
        """Create an authenticated view of an actor with permission enforcement.

        This method wraps the actor in an AuthenticatedActorView that enforces
        permission checks based on the authentication context.

        Args:
            actor: The actor to wrap
            auth_result: The AuthResult from authentication

        Returns:
            AuthenticatedActorView with permission enforcement, or None if actor is None
        """
        if not actor:
            return None

        from actingweb.interface.actor_interface import ActorInterface
        from actingweb.interface.authenticated_views import (
            AuthContext,
            AuthenticatedActorView,
        )

        # Get peer/client info from auth object
        peer_id = ""
        client_id = ""
        trust_relationship: dict[str, Any] = {}

        if auth_result.auth_obj and hasattr(auth_result.auth_obj, "acl"):
            acl = auth_result.auth_obj.acl
            peer_id = acl.get("peerid", "") or ""
            # For OAuth2 clients, use the client_id from ACL
            if not peer_id and acl.get("oauth2_client"):
                client_id = acl.get("oauth2_client", "")

            # Extract trust relationship info if available
            if peer_id:
                trust_relationship = {
                    "peer_id": peer_id,
                    "relationship": acl.get("relationship", ""),
                    "approved": acl.get("approved", False),
                }

        # Create auth context
        auth_context = AuthContext(
            peer_id=peer_id,
            client_id=client_id,
            trust_relationship=trust_relationship,
        )

        # Get or create ActorInterface
        registry = getattr(self.config, "service_registry", None)
        actor_interface = ActorInterface(
            actor, service_registry=registry, hooks=self.hooks
        )

        return AuthenticatedActorView(actor_interface, auth_context, self.hooks)

    def _authenticate_dual_context(
        self,
        actor_id: str,
        api_path: str,
        web_subpath: str,
        name: str = "",
        add_response: bool = True,
    ) -> "AuthResult":
        """
        Authenticate supporting both web UI (OAuth) and API (basic) access.

        This method detects whether a request is coming from the web UI (by checking
        for oauth_token cookie) and chooses the appropriate authentication path:
        - Web UI requests: path="www", subpath=web_subpath (OAuth authentication)
        - API requests: path=api_path, subpath=name (basic authentication)

        Args:
            actor_id: The actor ID
            api_path: Path to use for API authentication (e.g., "properties", "methods")
            web_subpath: Subpath to use for web UI authentication (e.g., "properties", "methods")
            name: Name/subpath for API authentication (optional)
            add_response: Whether to automatically set HTTP response

        Returns:
            AuthResult object with actor, auth status, and authorization helper methods
        """
        # Detect web UI context by checking for OAuth cookie
        is_web_ui_request = False
        try:
            # Check for OAuth cookie indicating web UI context
            if hasattr(self.request, "cookies") and self.request.cookies:
                is_web_ui_request = "oauth_token" in self.request.cookies
            elif hasattr(self.request, "get"):
                # Alternative cookie access pattern for different frameworks
                try:
                    oauth_cookie = self.request.get("oauth_token", cookie=True)  # type: ignore
                    is_web_ui_request = oauth_cookie is not None
                except TypeError:
                    # Framework doesn't support cookie parameter
                    is_web_ui_request = False
        except Exception:  # folds DbError: cookie detection, no DB access
            # Fallback to basic auth if cookie detection fails
            is_web_ui_request = False

        if is_web_ui_request:
            # Web UI context - use OAuth authentication
            return self._authenticate_internal(
                actor_id, "www", web_subpath, add_response
            )
        else:
            # API context - use basic authentication
            return self._authenticate_internal(actor_id, api_path, name, add_response)

    def _authenticate_internal(
        self, actor_id: str, path: str, subpath: str = "", add_response: bool = True
    ) -> "AuthResult":
        """
        Internal authentication implementation that replaces auth.init_actingweb().

        Args:
            actor_id: The actor ID
            path: ActingWeb path for authentication
            subpath: Optional subpath
            add_response: Whether to automatically set HTTP response

        Returns:
            AuthResult object with actor, auth status, and authorization helper methods
        """
        from .. import auth

        # Determine auth type based on path
        if path == "www":
            auth_type = self.config.www_auth if self.config else "basic"
        else:
            auth_type = "basic"

        # Create Auth object and perform authentication
        fullpath = "/" + path + "/" + subpath
        auth_obj = auth.Auth(actor_id, auth_type=auth_type, config=self.config)

        # Perform authentication - this loads the actor and checks credentials
        auth_obj.check_authentication(appreq=self, path=fullpath)

        # Check if actor was found during authentication
        if not hasattr(auth_obj, "actor") or not auth_obj.actor:
            if add_response and self.response:
                self.response.set_status(404, "Actor not found")
            return AuthResult(None, auth_obj, self.response)

        # Set response if needed
        if add_response and self.response:
            auth.add_auth_response(appreq=self, auth_obj=auth_obj)

        return AuthResult(auth_obj.actor, auth_obj, self.response)

    def require_authenticated_actor(
        self, actor_id: str, path: str, method: str = "GET", subpath: str = ""
    ) -> Any | None:
        """
        Simplified actor authentication and authorization in one call.

        This method combines actor loading, authentication, and authorization into a single
        call that handles all the common error cases and sets appropriate HTTP responses.

        Args:
            actor_id: Actor ID to authenticate
            path: ActingWeb path for authorization (e.g., "properties", "trust")
            method: HTTP method for authorization check ("GET", "POST", etc.)
            subpath: Optional subpath for authorization

        Returns:
            Actor object if authentication and authorization successful, None otherwise.
            When None is returned, the HTTP response has already been set appropriately.
        """
        auth_result = self._authenticate_internal(actor_id, path, subpath)

        # Check if actor exists and authentication succeeded
        if not auth_result.success:
            return None

        # Check authorization
        if not auth_result.authorize(method.upper(), path, subpath):
            return None

        return auth_result.actor

    def authenticate_actor(
        self,
        actor_id: str,
        path: str = "",
        subpath: str = "",
        add_response: bool = True,
    ) -> "AuthResult":
        """
        Authenticate actor and return detailed auth result.

        This provides more control than require_authenticated_actor() by returning
        an AuthResult object that can be used for custom authorization logic.

        Args:
            actor_id: Actor ID to authenticate
            path: ActingWeb path for auth type selection
            subpath: Optional subpath
            add_response: Whether to automatically set HTTP response

        Returns:
            AuthResult object with actor, auth status, and authorization helper methods
        """
        return self._authenticate_internal(actor_id, path, subpath, add_response)

    def get_actor_allow_unauthenticated(
        self, actor_id: str, path: str = "", subpath: str = ""
    ) -> Any | None:
        """
        Get actor allowing unauthenticated access (for public endpoints like meta).

        This method loads an actor but doesn't require authentication. It's used for
        endpoints that should be publicly accessible but still need actor data.

        Args:
            actor_id: Actor ID to load
            path: Path for authorization context
            subpath: Subpath for authorization context

        Returns:
            Actor object if it exists, None otherwise. Sets 404 if actor doesn't exist.
        """
        auth_result = self._authenticate_internal(
            actor_id, path, subpath, add_response=False
        )

        if not auth_result.actor:
            if self.response:
                self.response.set_status(404, "Actor not found")
            return None

        # For public endpoints, still check authorization but allow unauthenticated access
        if auth_result.auth_obj and not auth_result.auth_obj.check_authorisation(
            path=path, subpath=subpath, method="GET", approved=False
        ):
            if self.response:
                self.response.set_status(403)
            return None

        return auth_result.actor


class AuthResult:
    """Result of actor authentication with helper methods for authorization."""

    def __init__(self, actor, auth_obj, response):
        self.actor = actor
        self.auth_obj = auth_obj
        self.response = response

    @property
    def success(self) -> bool:
        """True if actor exists and authentication succeeded."""
        return (
            self.actor is not None
            and self.auth_obj is not None
            and self.auth_obj.response["code"] == 200
        )

    @property
    def authenticated(self) -> bool:
        """True if authentication succeeded (regardless of authorization)."""
        return self.auth_obj is not None and self.auth_obj.acl["authenticated"]

    def authorize(self, method: str, path: str = "", subpath: str = "") -> bool:
        """
        Check authorization for the given method and path.

        Args:
            method: HTTP method ("GET", "POST", etc.)
            path: Path for authorization (defaults to path used in authentication)
            subpath: Subpath for authorization

        Returns:
            True if authorized, False otherwise. Sets 403 response if unauthorized.
        """
        if not self.success:
            return False

        if self.auth_obj.check_authorisation(
            path=path, subpath=subpath, method=method.upper()
        ):
            return True
        else:
            if self.response:
                self.response.set_status(403)
            return False
