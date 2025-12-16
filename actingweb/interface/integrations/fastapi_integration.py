"""
FastAPI integration for ActingWeb applications.

Automatically generates FastAPI routes and handles request/response transformation
with async support.
"""

import asyncio
import base64
import concurrent.futures
import json
import logging
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from ...aw_web_request import AWWebObj
from ...handlers import bot, factory, mcp, services
from .base_integration import BaseActingWebIntegration

if TYPE_CHECKING:
    from ..app import ActingWebApp


# Pydantic Models for Type Safety


class ActorCreateRequest(BaseModel):
    """Request model for creating a new actor."""

    creator: str = Field(..., description="Email or identifier of the actor creator")
    passphrase: str | None = Field(
        None, description="Optional passphrase for actor creation"
    )
    type: str | None = Field(
        None, description="Actor type, defaults to configured type"
    )
    desc: str | None = Field(None, description="Optional description for the actor")


class ActorResponse(BaseModel):
    """Response model for actor operations."""

    id: str = Field(..., description="Unique actor identifier")
    creator: str = Field(..., description="Email or identifier of the actor creator")
    url: str = Field(..., description="Full URL to the actor")
    type: str = Field(..., description="Actor type")
    desc: str | None = Field(None, description="Actor description")


class PropertyRequest(BaseModel):
    """Request model for property operations."""

    value: Any = Field(..., description="Property value (can be any JSON type)")
    protected: bool | None = Field(
        False, description="Whether this property is protected"
    )


class PropertyResponse(BaseModel):
    """Response model for property operations."""

    name: str = Field(..., description="Property name")
    value: Any = Field(..., description="Property value")
    protected: bool = Field(..., description="Whether this property is protected")


class TrustRequest(BaseModel):
    """Request model for trust relationship operations."""

    type: str = Field(..., description="Type of trust relationship")
    peerid: str = Field(..., description="Peer actor identifier")
    baseuri: str = Field(..., description="Base URI of the peer actor")
    desc: str | None = Field(
        None, description="Optional description of the relationship"
    )


class TrustResponse(BaseModel):
    """Response model for trust relationship operations."""

    type: str = Field(..., description="Type of trust relationship")
    peerid: str = Field(..., description="Peer actor identifier")
    baseuri: str = Field(..., description="Base URI of the peer actor")
    desc: str | None = Field(None, description="Description of the relationship")


class SubscriptionRequest(BaseModel):
    """Request model for subscription operations."""

    peerid: str = Field(..., description="Peer actor identifier")
    hook: str = Field(..., description="Hook URL to be called")
    granularity: str | None = Field("message", description="Subscription granularity")
    desc: str | None = Field(None, description="Optional description")


class SubscriptionResponse(BaseModel):
    """Response model for subscription operations."""

    id: str = Field(..., description="Subscription identifier")
    peerid: str = Field(..., description="Peer actor identifier")
    hook: str = Field(..., description="Hook URL")
    granularity: str = Field(..., description="Subscription granularity")
    desc: str | None = Field(None, description="Subscription description")


class CallbackRequest(BaseModel):
    """Request model for callback operations."""

    data: dict[str, Any] = Field(default_factory=dict, description="Callback data")


class CallbackResponse(BaseModel):
    """Response model for callback operations."""

    result: Any = Field(..., description="Callback execution result")
    success: bool = Field(..., description="Whether callback executed successfully")


class MethodRequest(BaseModel):
    """Request model for method calls."""

    data: dict[str, Any] = Field(default_factory=dict, description="Method parameters")


class MethodResponse(BaseModel):
    """Response model for method calls."""

    result: Any = Field(..., description="Method execution result")
    success: bool = Field(..., description="Whether method executed successfully")


class ActionRequest(BaseModel):
    """Request model for action triggers."""

    data: dict[str, Any] = Field(default_factory=dict, description="Action parameters")


class ActionResponse(BaseModel):
    """Response model for action triggers."""

    result: Any = Field(..., description="Action execution result")
    success: bool = Field(..., description="Whether action executed successfully")


class ErrorResponse(BaseModel):
    """Standard error response model."""

    error: str = Field(..., description="Error message")
    status_code: int = Field(..., description="HTTP status code")
    details: dict[str, Any] | None = Field(None, description="Additional error details")


# Dependency Injection Functions


async def get_actor_from_path(actor_id: str, request: Request) -> dict[str, Any] | None:
    """
    Dependency to extract and validate actor from path parameter.
    Returns actor data or None if not found.
    """
    # This would typically load the actor from database
    # For now, we'll return the actor_id for the handlers to process
    return {"id": actor_id, "request": request}


async def get_basic_auth(request: Request) -> dict[str, str] | None:
    """
    Dependency to extract basic authentication credentials.
    Returns auth data or None if not provided.
    """
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Basic "):
        return None

    try:
        # Decode base64 auth string
        auth_data = base64.b64decode(auth_header[6:]).decode("utf-8")
        username, password = auth_data.split(":", 1)
        return {"username": username, "password": password}
    except (ValueError, UnicodeDecodeError):
        return None


async def get_bearer_token(request: Request) -> str | None:
    """
    Dependency to extract bearer token from Authorization header.
    Returns token string or None if not provided.
    """
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    return auth_header[7:]


async def authenticate_google_oauth(
    request: Request, config: Any
) -> tuple[Any, str] | None:
    """
    Authenticate Google OAuth2 Bearer token and return actor.

    Returns:
        Tuple of (actor, email) or None if authentication failed
    """
    bearer_token = await get_bearer_token(request)
    if not bearer_token:
        return None

    try:
        from ...oauth2 import create_oauth2_authenticator

        authenticator = create_oauth2_authenticator(config)
        result = authenticator.authenticate_bearer_token(bearer_token)
        if (
            result
            and len(result) == 2
            and result[0] is not None
            and result[1] is not None
        ):
            return result  # type: ignore
        return None
    except Exception as e:
        logging.error(f"OAuth2 authentication error: {e}")
        return None


def create_oauth_redirect_response(
    config: Any, redirect_after_auth: str = "", clear_cookie: bool = False
) -> RedirectResponse | Response:
    """
    Create OAuth2 redirect response to configured OAuth2 provider.

    Args:
        config: ActingWeb configuration
        redirect_after_auth: URL to redirect to after successful auth
        clear_cookie: Whether to clear expired oauth_token cookie

    Returns:
        RedirectResponse to configured OAuth2 provider
    """
    try:
        from ...oauth2 import create_oauth2_authenticator

        authenticator = create_oauth2_authenticator(config)
        if authenticator.is_enabled():
            auth_url = authenticator.create_authorization_url(
                redirect_after_auth=redirect_after_auth
            )
            if auth_url:
                redirect_response = RedirectResponse(url=auth_url, status_code=302)
                if clear_cookie:
                    # Clear the expired oauth_token cookie
                    redirect_response.delete_cookie("oauth_token", path="/")
                    logging.debug("Cleared expired oauth_token cookie")
                return redirect_response
    except Exception as e:
        logging.error(f"Error creating OAuth2 redirect: {e}")

    # Fallback to 401 if OAuth2 not configured
    response = Response(content="Authentication required", status_code=401)
    # Prefer dynamic header based on configured OAuth2 provider if available
    add_www_authenticate_header(response, config)
    return response


def add_www_authenticate_header(response: Response, config: Any) -> None:
    """
    Add WWW-Authenticate header for OAuth2 authentication.
    """
    try:
        from ...oauth2 import create_oauth2_authenticator

        authenticator = create_oauth2_authenticator(config)
        if authenticator.is_enabled():
            www_auth = authenticator.create_www_authenticate_header()
            response.headers["WWW-Authenticate"] = www_auth
    except Exception as e:
        logging.error(f"Error adding WWW-Authenticate header: {e}")
        response.headers["WWW-Authenticate"] = 'Bearer realm="ActingWeb"'


async def check_authentication_and_redirect(
    request: Request, config: Any
) -> RedirectResponse | None:
    """
    Check if request is authenticated, if not return OAuth2 redirect.

    Returns:
        RedirectResponse to Google OAuth2 if not authenticated, None if authenticated
    """
    # Check for Basic auth
    basic_auth = await get_basic_auth(request)
    if basic_auth:
        return None  # Has basic auth, let normal flow handle it

    # Check for Bearer token
    bearer_token = await get_bearer_token(request)
    if bearer_token:
        # If a Bearer token is present, let the underlying handlers verify it.
        # This supports both OAuth2 tokens and ActingWeb trust secret tokens
        # without forcing an OAuth2 redirect here.
        return None

    # Check for OAuth token cookie (for session-based authentication)
    oauth_cookie = request.cookies.get("oauth_token")
    if oauth_cookie:
        logging.debug(f"Found oauth_token cookie with length {len(oauth_cookie)}")

        # First, check if this is an ActingWeb session token (SPA or /www)
        try:
            from ...oauth_session import get_oauth2_session_manager

            session_manager = get_oauth2_session_manager(config)
            token_data = session_manager.validate_access_token(oauth_cookie)
            if token_data:
                actor_id = token_data.get("actor_id")
                logging.debug(
                    f"ActingWeb session token validation successful for actor {actor_id}"
                )
                return None  # Valid ActingWeb token
        except Exception as e:
            logging.debug(f"ActingWeb token validation failed: {e}")

        # Fall back to validating as OAuth provider token (legacy support)
        try:
            from ...oauth2 import create_oauth2_authenticator

            authenticator = create_oauth2_authenticator(config)
            if authenticator.is_enabled():
                user_info = authenticator.validate_token_and_get_user_info(oauth_cookie)
                if user_info:
                    email = authenticator.get_email_from_user_info(
                        user_info, oauth_cookie
                    )
                    if email:
                        logging.debug(f"OAuth cookie validation successful for {email}")
                        return None  # Valid OAuth cookie
                logging.debug(
                    "OAuth cookie token is expired or invalid - will redirect to fresh OAuth"
                )
                # Token expired/invalid - fall through to create redirect response with cookie cleanup
        except Exception as e:
            logging.debug(
                f"OAuth cookie validation error: {e} - will redirect to fresh OAuth"
            )
            # Validation failed - fall through to redirect

    # No valid authentication - redirect to OAuth2 provider
    original_url = str(request.url)
    # Clear cookie if we had an expired token
    clear_cookie = bool(oauth_cookie)
    result = create_oauth_redirect_response(
        config, redirect_after_auth=original_url, clear_cookie=clear_cookie
    )
    if isinstance(result, RedirectResponse):
        return result
    return None


async def validate_content_type(
    request: Request, expected: str = "application/json"
) -> bool:
    """
    Dependency to validate request content type.
    Returns True if content type matches expected type.
    """
    content_type = request.headers.get("content-type", "")
    return expected in content_type


async def get_json_body(request: Request) -> dict[str, Any]:
    """
    Dependency to parse JSON request body.
    Returns parsed JSON data or empty dict.
    """
    try:
        body = await request.body()
        if not body:
            return {}
        parsed_json = json.loads(body.decode("utf-8"))
        return parsed_json if isinstance(parsed_json, dict) else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


class FastAPIIntegration(BaseActingWebIntegration):
    """
    FastAPI integration for ActingWeb applications.

    Automatically sets up all ActingWeb routes and handles request/response
    transformation between FastAPI and ActingWeb with async support.
    """

    def __init__(
        self,
        aw_app: "ActingWebApp",
        fastapi_app: FastAPI,
        templates_dir: str | None = None,
    ):
        super().__init__(aw_app)
        self.fastapi_app = fastapi_app
        self.templates = (
            Jinja2Templates(directory=templates_dir) if templates_dir else None
        )
        self.logger = logging.getLogger(__name__)
        # Thread pool for running synchronous ActingWeb handlers
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=10, thread_name_prefix="aw-handler"
        )

    def shutdown(self) -> None:
        """Shutdown the thread pool executor."""
        if hasattr(self, "executor"):
            self.executor.shutdown(wait=True)

    async def _check_auth_or_redirect(
        self, request: Request
    ) -> RedirectResponse | None:
        """Helper to check authentication and return redirect if needed."""
        return await check_authentication_and_redirect(
            request, self.aw_app.get_config()
        )

    def setup_routes(self) -> None:
        """Setup all ActingWeb routes in FastAPI."""

        # Root factory route
        @self.fastapi_app.get("/")
        async def app_root_get(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
            # GET requests don't require authentication - show email form
            return await self._handle_factory_get_request(request)

        @self.fastapi_app.post("/")
        async def app_root_post(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
            # Check if this is a JSON API request or web form request
            content_type = request.headers.get("content-type", "")
            accepts_json = (
                request.headers.get("accept", "").find("application/json") >= 0
            )
            is_json_request = "application/json" in content_type

            if is_json_request or accepts_json:
                # Handle JSON API requests with the standard factory handler
                return await self._handle_factory_request(request)
            else:
                # For web form requests, extract email and redirect to OAuth2 with email hint
                return await self._handle_factory_post_with_oauth_redirect(request)

        # Google OAuth callback
        @self.fastapi_app.get("/oauth/callback")
        async def oauth_callback_handler(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
            # Handle both Google OAuth2 callback (for ActingWeb) and MCP OAuth2 callback
            # Determine which flow based on state parameter
            state = request.query_params.get("state", "")
            code = request.query_params.get("code", "")
            error = request.query_params.get("error", "")

            # Check if this is an MCP OAuth2 callback (encrypted state)
            self.logger.debug(
                f"OAuth callback received - code: {bool(code)}, error: {error}, state: {state[:100]}..."
            )  # Log first 100 chars

            # Debug: Check if MCP is enabled
            config = self.aw_app.get_config()
            mcp_enabled = getattr(config, "mcp", False)
            self.logger.debug(f"MCP enabled in config: {mcp_enabled}")

            try:
                from ...oauth2_server.state_manager import get_oauth2_state_manager

                state_manager = get_oauth2_state_manager(self.aw_app.get_config())
                self.logger.debug("State manager created successfully")

                mcp_context = state_manager.extract_mcp_context(state)
                self.logger.debug(
                    f"MCP context extraction result: {mcp_context is not None}"
                )

                if mcp_context:
                    self.logger.debug(
                        f"Using MCP OAuth2 callback handler with context: {mcp_context}"
                    )
                    # This is an MCP OAuth2 callback
                    return await self._handle_oauth2_endpoint(request, "callback")
                else:
                    self.logger.debug(
                        "No MCP context found, using standard OAuth2 callback"
                    )
            except Exception:
                # Not an MCP callback or state manager not available
                self.logger.error("Error checking MCP context", exc_info=True)

            # Default to Google OAuth2 callback for ActingWeb
            self.logger.debug("Using standard Google OAuth2 callback handler")
            return await self._handle_google_oauth_callback(request)

        # OAuth2 email input - handles email collection when OAuth provider doesn't provide one
        @self.fastapi_app.get("/oauth/email")
        async def oauth_email_get(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
            return await self._handle_oauth2_email(request)

        @self.fastapi_app.post("/oauth/email")
        async def oauth_email_post(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
            return await self._handle_oauth2_email(request)

        # Email verification endpoint - verifies email addresses for OAuth2 actors
        @self.fastapi_app.get("/{actor_id}/www/verify_email")
        async def email_verification_get(request: Request, actor_id: str) -> Response:  # pyright: ignore[reportUnusedFunction]
            return await self._handle_email_verification(request, actor_id)

        @self.fastapi_app.post("/{actor_id}/www/verify_email")
        async def email_verification_post(request: Request, actor_id: str) -> Response:  # pyright: ignore[reportUnusedFunction]
            return await self._handle_email_verification(request, actor_id)

        # OAuth2 server endpoints for MCP clients
        @self.fastapi_app.post("/oauth/register")
        @self.fastapi_app.options("/oauth/register")
        async def oauth2_register(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
            return await self._handle_oauth2_endpoint(request, "register")

        @self.fastapi_app.get("/oauth/authorize")
        @self.fastapi_app.options("/oauth/authorize")
        async def oauth2_authorize_get(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
            return await self._handle_oauth2_endpoint(request, "authorize")

        @self.fastapi_app.post("/oauth/authorize")
        async def oauth2_authorize_post(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
            return await self._handle_oauth2_endpoint(request, "authorize")

        @self.fastapi_app.post("/oauth/token")
        @self.fastapi_app.options("/oauth/token")
        async def oauth2_token(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
            return await self._handle_oauth2_endpoint(request, "token")

        @self.fastapi_app.get("/oauth/logout")
        @self.fastapi_app.post("/oauth/logout")
        @self.fastapi_app.options("/oauth/logout")
        async def oauth2_logout(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
            """
            Unified logout endpoint that handles both:
            1. MCP OAuth2 client token revocation (if Authorization header present)
            2. Web UI session logout (if oauth_token cookie present)
            """
            # Handle OPTIONS (CORS preflight) immediately
            if request.method == "OPTIONS":
                cors_headers = {
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Authorization, Content-Type, mcp-protocol-version",
                    "Access-Control-Max-Age": "86400",
                }
                return JSONResponse(
                    {"message": "CORS preflight"}, status_code=200, headers=cors_headers
                )

            # Check if this is an AJAX request (expects JSON response)
            content_type = request.headers.get("content-type", "")
            is_ajax = (
                "application/json" in content_type
                or request.headers.get("x-requested-with") == "XMLHttpRequest"
            )

            # First, handle MCP OAuth2 token revocation if Authorization header present
            auth_header = request.headers.get("authorization", "")
            if auth_header.startswith("Bearer "):
                self.logger.info("Logout: Revoking MCP OAuth2 token")
                await self._handle_oauth2_endpoint(request, "logout")

            # Check if this is a web UI logout (oauth_token cookie present)
            oauth_cookie = request.cookies.get("oauth_token")
            if oauth_cookie:
                self.logger.info("Logout: Clearing web UI session (oauth_token cookie)")

                if is_ajax:
                    # Return JSON response for AJAX requests
                    response = JSONResponse(
                        {
                            "success": True,
                            "message": "Logged out successfully",
                            "redirect_url": "/",
                        }
                    )
                    response.delete_cookie("oauth_token", path="/")
                    return response
                else:
                    # Return redirect for direct navigation
                    response = RedirectResponse(url="/", status_code=302)
                    response.delete_cookie("oauth_token", path="/")
                    return response

            # If neither token nor cookie, just return success
            if not auth_header and not oauth_cookie:
                self.logger.info("Logout: No active session found")
                return JSONResponse(
                    {"message": "No active session to logout"}, status_code=200
                )

            # MCP client logout without web UI redirect
            return await self._handle_oauth2_endpoint(request, "logout")

        # Unified OAuth endpoints (JSON API, accessible at /oauth/*)
        @self.fastapi_app.get("/oauth/config")
        @self.fastapi_app.options("/oauth/config")
        async def oauth2_config(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
            """Get OAuth configuration."""
            return await self._handle_oauth2_spa_endpoint(request, "config")

        @self.fastapi_app.post("/oauth/revoke")
        @self.fastapi_app.options("/oauth/revoke")
        async def oauth2_revoke(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
            """Revoke access and/or refresh tokens."""
            return await self._handle_oauth2_spa_endpoint(request, "revoke")

        @self.fastapi_app.get("/oauth/session")
        @self.fastapi_app.options("/oauth/session")
        async def oauth2_session(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
            """Check session status."""
            return await self._handle_oauth2_spa_endpoint(request, "session")

        # SPA-specific OAuth endpoints (different purpose than MCP OAuth2)
        @self.fastapi_app.post("/oauth/spa/authorize")
        @self.fastapi_app.options("/oauth/spa/authorize")
        async def oauth2_spa_authorize(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
            """Initiate external OAuth flow (ActingWeb as OAuth client)."""
            return await self._handle_oauth2_spa_endpoint(request, "authorize")

        @self.fastapi_app.post("/oauth/spa/token")
        @self.fastapi_app.options("/oauth/spa/token")
        async def oauth2_spa_token(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
            """Token refresh with rotation for external provider tokens."""
            return await self._handle_oauth2_spa_endpoint(request, "token")

        # Backward compatibility routes
        @self.fastapi_app.get("/oauth/spa/config")
        @self.fastapi_app.options("/oauth/spa/config")
        async def oauth2_spa_config_compat(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
            """Get OAuth configuration (deprecated, use /oauth/config)."""
            return await self._handle_oauth2_spa_endpoint(request, "config")

        @self.fastapi_app.get("/oauth/spa/callback")
        @self.fastapi_app.options("/oauth/spa/callback")
        async def oauth2_spa_callback(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
            """Deprecated: Use /oauth/callback instead."""
            return await self._handle_oauth2_spa_endpoint(request, "callback")

        @self.fastapi_app.post("/oauth/spa/revoke")
        @self.fastapi_app.options("/oauth/spa/revoke")
        async def oauth2_spa_revoke_compat(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
            """Revoke tokens (deprecated, use /oauth/revoke)."""
            return await self._handle_oauth2_spa_endpoint(request, "revoke")

        @self.fastapi_app.get("/oauth/spa/session")
        @self.fastapi_app.options("/oauth/spa/session")
        async def oauth2_spa_session_compat(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
            """Check session (deprecated, use /oauth/session)."""
            return await self._handle_oauth2_spa_endpoint(request, "session")

        @self.fastapi_app.get("/oauth/spa/session/{session_id}")
        async def oauth2_spa_session_retrieve(request: Request, session_id: str) -> Response:  # pyright: ignore[reportUnusedFunction]
            """Retrieve pending SPA session data after OAuth callback."""
            return await self._handle_spa_session_retrieve(request, session_id)

        @self.fastapi_app.post("/oauth/spa/logout")
        @self.fastapi_app.options("/oauth/spa/logout")
        async def oauth2_spa_logout(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
            """Logout (deprecated, use /oauth/logout with Accept: application/json)."""
            return await self._handle_oauth2_spa_endpoint(request, "logout")

        # OAuth2 discovery endpoint - removed duplicate, handled by OAuth2EndpointsHandler below

        # Bot endpoint
        @self.fastapi_app.post("/bot")
        async def app_bot(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
            return await self._handle_bot_request(request)

        # MCP endpoint
        @self.fastapi_app.get("/mcp")
        @self.fastapi_app.post("/mcp")
        async def app_mcp(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
            # For MCP, allow initial handshake without authentication
            # Authentication will be handled within the MCP protocol
            return await self._handle_mcp_request(request)

        # OAuth2 Discovery endpoints using OAuth2EndpointsHandler
        @self.fastapi_app.get("/.well-known/oauth-authorization-server")
        @self.fastapi_app.options("/.well-known/oauth-authorization-server")
        async def oauth_discovery(request: Request) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
            """OAuth2 Authorization Server Discovery endpoint (RFC 8414)."""
            return await self._handle_oauth2_discovery_endpoint(
                request, ".well-known/oauth-authorization-server"
            )

        @self.fastapi_app.get("/.well-known/oauth-protected-resource")
        @self.fastapi_app.options("/.well-known/oauth-protected-resource")
        async def oauth_protected_resource_discovery(request: Request) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
            """OAuth2 Protected Resource discovery endpoint."""
            return await self._handle_oauth2_discovery_endpoint(
                request, ".well-known/oauth-protected-resource"
            )

        @self.fastapi_app.get("/.well-known/oauth-protected-resource/mcp")
        @self.fastapi_app.options("/.well-known/oauth-protected-resource/mcp")
        async def oauth_protected_resource_mcp_discovery(
            request: Request,
        ) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
            """OAuth2 Protected Resource discovery endpoint for MCP."""
            return await self._handle_oauth2_discovery_endpoint(
                request, ".well-known/oauth-protected-resource/mcp"
            )

        # MCP information endpoint
        @self.fastapi_app.get("/mcp/info")
        async def mcp_info() -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
            """MCP information endpoint."""
            return self._create_mcp_info_response()

        # Actor root
        @self.fastapi_app.get("/{actor_id}")
        @self.fastapi_app.post("/{actor_id}")
        @self.fastapi_app.delete("/{actor_id}")
        async def app_actor_root(actor_id: str, request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
            # Check authentication and redirect to Google OAuth2 if needed
            auth_redirect = await check_authentication_and_redirect(
                request, self.aw_app.get_config()
            )
            if auth_redirect:
                return auth_redirect
            return await self._handle_actor_request(request, actor_id, "root")

        # Actor meta
        @self.fastapi_app.get("/{actor_id}/meta")
        @self.fastapi_app.get("/{actor_id}/meta/{path:path}")
        async def app_meta(actor_id: str, request: Request, path: str = "") -> Response:  # pyright: ignore[reportUnusedFunction]
            # Meta endpoint should be public for peer discovery - no authentication required
            return await self._handle_actor_request(
                request, actor_id, "meta", path=path
            )

        # Actor www
        @self.fastapi_app.get("/{actor_id}/www")
        @self.fastapi_app.post("/{actor_id}/www")
        @self.fastapi_app.delete("/{actor_id}/www")
        @self.fastapi_app.get("/{actor_id}/www/{path:path}")
        @self.fastapi_app.post("/{actor_id}/www/{path:path}")
        @self.fastapi_app.delete("/{actor_id}/www/{path:path}")
        async def app_www(actor_id: str, request: Request, path: str = "") -> Response:  # pyright: ignore[reportUnusedFunction]
            # Check authentication and redirect to Google OAuth2 if needed
            auth_redirect = await self._check_auth_or_redirect(request)
            if auth_redirect:
                return auth_redirect
            return await self._handle_actor_request(request, actor_id, "www", path=path)

        # Actor properties
        @self.fastapi_app.get("/{actor_id}/properties")
        @self.fastapi_app.post("/{actor_id}/properties")
        @self.fastapi_app.put("/{actor_id}/properties")
        @self.fastapi_app.delete("/{actor_id}/properties")
        async def app_properties_root(actor_id: str, request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
            # Check authentication and redirect to Google OAuth2 if needed
            auth_redirect = await self._check_auth_or_redirect(request)
            if auth_redirect:
                return auth_redirect
            return await self._handle_actor_request(
                request, actor_id, "properties", name=""
            )

        # Property metadata endpoint (must come before catch-all {name:path})
        @self.fastapi_app.get("/{actor_id}/properties/{name}/metadata")
        @self.fastapi_app.put("/{actor_id}/properties/{name}/metadata")
        async def app_property_metadata(
            actor_id: str, request: Request, name: str
        ) -> Response:  # pyright: ignore[reportUnusedFunction]
            auth_redirect = await self._check_auth_or_redirect(request)
            if auth_redirect:
                return auth_redirect
            return await self._handle_actor_request(
                request, actor_id, "properties", name=name, metadata=True
            )

        # Property list items endpoint (must come before catch-all {name:path})
        @self.fastapi_app.get("/{actor_id}/properties/{name}/items")
        @self.fastapi_app.post("/{actor_id}/properties/{name}/items")
        async def app_property_items(
            actor_id: str, request: Request, name: str
        ) -> Response:  # pyright: ignore[reportUnusedFunction]
            auth_redirect = await self._check_auth_or_redirect(request)
            if auth_redirect:
                return auth_redirect
            return await self._handle_actor_request(
                request, actor_id, "properties", name=name, items=True
            )

        @self.fastapi_app.get("/{actor_id}/properties/{name:path}")
        @self.fastapi_app.post("/{actor_id}/properties/{name:path}")
        @self.fastapi_app.put("/{actor_id}/properties/{name:path}")
        @self.fastapi_app.delete("/{actor_id}/properties/{name:path}")
        async def app_properties(
            actor_id: str, request: Request, name: str = ""
        ) -> Response:  # pyright: ignore[reportUnusedFunction]
            # Check authentication and redirect to Google OAuth2 if needed
            auth_redirect = await self._check_auth_or_redirect(request)
            if auth_redirect:
                return auth_redirect
            return await self._handle_actor_request(
                request, actor_id, "properties", name=name
            )

        # Actor trust - path-based endpoints (more specific routes first)
        # Shared properties endpoint (most specific, must be before general trust peer routes)
        @self.fastapi_app.get(
            "/{actor_id}/trust/{relationship}/{peerid}/shared_properties",
            summary="Get shared properties available for subscription",
            description=(
                "Returns properties that the authenticated peer has permission to subscribe to. "
                "Requires an active trust relationship. Response includes property names, "
                "display names, item counts (for property lists), and permitted operations. "
                "Authentication: Bearer token (OAuth2) or ActingWeb trust secret."
            ),
            tags=["Trust"],
            responses={
                200: {
                    "description": "List of shared and excluded properties",
                    "content": {
                        "application/json": {
                            "example": {
                                "actor_id": "actor-123",
                                "peer_id": "peer-456",
                                "relationship": "mcp_client",
                                "shared_properties": [
                                    {
                                        "name": "memory_personal",
                                        "display_name": "Memory Personal",
                                        "item_count": 42,
                                        "operations": ["read", "subscribe"]
                                    }
                                ],
                                "excluded_properties": ["memory_private"]
                            }
                        }
                    }
                },
                403: {"description": "Permission denied or wrong peer"},
                404: {"description": "Trust relationship not found"},
                503: {"description": "Permission system not available"}
            }
        )
        async def app_trust_shared_properties(  # pyright: ignore[reportUnusedFunction]
            actor_id: str,
            relationship: str,
            peerid: str,
            request: Request,
        ) -> Response:
            return await self._handle_actor_request(
                request,
                actor_id,
                "trust",
                relationship=relationship,
                peerid=peerid,
                shared_properties=True,
            )

        @self.fastapi_app.get("/{actor_id}/trust/{relationship}/{peerid}")
        @self.fastapi_app.post("/{actor_id}/trust/{relationship}/{peerid}")
        @self.fastapi_app.put("/{actor_id}/trust/{relationship}/{peerid}")
        @self.fastapi_app.delete("/{actor_id}/trust/{relationship}/{peerid}")
        async def app_trust_peer(  # pyright: ignore[reportUnusedFunction]
            actor_id: str,
            request: Request,
            relationship: str,
            peerid: str,
        ) -> Response:
            return await self._handle_actor_request(
                request, actor_id, "trust", relationship=relationship, peerid=peerid
            )

        @self.fastapi_app.get("/{actor_id}/trust/{relationship}")
        @self.fastapi_app.post("/{actor_id}/trust/{relationship}")
        @self.fastapi_app.put("/{actor_id}/trust/{relationship}")
        @self.fastapi_app.delete("/{actor_id}/trust/{relationship}")
        async def app_trust_relationship(  # pyright: ignore[reportUnusedFunction]
            actor_id: str,
            request: Request,
            relationship: str,
        ) -> Response:
            return await self._handle_actor_request(
                request, actor_id, "trust", relationship=relationship, peerid=None
            )

        # Actor trust - root endpoint (least specific, defined last)
        @self.fastapi_app.get("/{actor_id}/trust")
        @self.fastapi_app.post("/{actor_id}/trust")
        @self.fastapi_app.put("/{actor_id}/trust")
        @self.fastapi_app.delete("/{actor_id}/trust")
        async def app_trust_root(  # pyright: ignore[reportUnusedFunction]
            actor_id: str,
            request: Request,
        ) -> Response:
            return await self._handle_actor_request(
                request, actor_id, "trust", relationship=None, peerid=None
            )

        # Trust permission management endpoints
        @self.fastapi_app.get("/{actor_id}/trust/{relationship}/{peerid}/permissions")
        @self.fastapi_app.put("/{actor_id}/trust/{relationship}/{peerid}/permissions")
        @self.fastapi_app.delete(
            "/{actor_id}/trust/{relationship}/{peerid}/permissions"
        )
        async def app_trust_permissions(
            actor_id: str, request: Request, relationship: str, peerid: str
        ) -> Response:  # pyright: ignore[reportUnusedFunction]
            return await self._handle_actor_request(
                request,
                actor_id,
                "trust",
                relationship=relationship,
                peerid=peerid,
                permissions=True,
            )

        # Actor subscriptions
        @self.fastapi_app.get("/{actor_id}/subscriptions")
        @self.fastapi_app.post("/{actor_id}/subscriptions")
        @self.fastapi_app.put("/{actor_id}/subscriptions")
        @self.fastapi_app.delete("/{actor_id}/subscriptions")
        @self.fastapi_app.get("/{actor_id}/subscriptions/{peerid}")
        @self.fastapi_app.post("/{actor_id}/subscriptions/{peerid}")
        @self.fastapi_app.put("/{actor_id}/subscriptions/{peerid}")
        @self.fastapi_app.delete("/{actor_id}/subscriptions/{peerid}")
        @self.fastapi_app.get("/{actor_id}/subscriptions/{peerid}/{subid}")
        @self.fastapi_app.post("/{actor_id}/subscriptions/{peerid}/{subid}")
        @self.fastapi_app.put("/{actor_id}/subscriptions/{peerid}/{subid}")
        @self.fastapi_app.delete("/{actor_id}/subscriptions/{peerid}/{subid}")
        @self.fastapi_app.get("/{actor_id}/subscriptions/{peerid}/{subid}/{seqnr:int}")
        async def app_subscriptions(  # pyright: ignore[reportUnusedFunction]
            actor_id: str,
            request: Request,
            peerid: str | None = None,
            subid: str | None = None,
            seqnr: int | None = None,
        ) -> Response:
            return await self._handle_actor_request(
                request,
                actor_id,
                "subscriptions",
                peerid=peerid,
                subid=subid,
                seqnr=seqnr,
            )

        # Actor resources
        @self.fastapi_app.get("/{actor_id}/resources")
        @self.fastapi_app.post("/{actor_id}/resources")
        @self.fastapi_app.put("/{actor_id}/resources")
        @self.fastapi_app.delete("/{actor_id}/resources")
        @self.fastapi_app.get("/{actor_id}/resources/{name:path}")
        @self.fastapi_app.post("/{actor_id}/resources/{name:path}")
        @self.fastapi_app.put("/{actor_id}/resources/{name:path}")
        @self.fastapi_app.delete("/{actor_id}/resources/{name:path}")
        async def app_resources(
            actor_id: str, request: Request, name: str = ""
        ) -> Response:  # pyright: ignore[reportUnusedFunction]
            return await self._handle_actor_request(
                request, actor_id, "resources", name=name
            )

        # Actor callbacks
        @self.fastapi_app.get("/{actor_id}/callbacks")
        @self.fastapi_app.post("/{actor_id}/callbacks")
        @self.fastapi_app.put("/{actor_id}/callbacks")
        @self.fastapi_app.delete("/{actor_id}/callbacks")
        @self.fastapi_app.get("/{actor_id}/callbacks/{name:path}")
        @self.fastapi_app.post("/{actor_id}/callbacks/{name:path}")
        @self.fastapi_app.put("/{actor_id}/callbacks/{name:path}")
        @self.fastapi_app.delete("/{actor_id}/callbacks/{name:path}")
        async def app_callbacks(
            actor_id: str, request: Request, name: str = ""
        ) -> Response:  # pyright: ignore[reportUnusedFunction]
            return await self._handle_actor_request(
                request, actor_id, "callbacks", name=name
            )

        # Actor devtest
        @self.fastapi_app.get("/{actor_id}/devtest")
        @self.fastapi_app.post("/{actor_id}/devtest")
        @self.fastapi_app.put("/{actor_id}/devtest")
        @self.fastapi_app.delete("/{actor_id}/devtest")
        @self.fastapi_app.get("/{actor_id}/devtest/{path:path}")
        @self.fastapi_app.post("/{actor_id}/devtest/{path:path}")
        @self.fastapi_app.put("/{actor_id}/devtest/{path:path}")
        @self.fastapi_app.delete("/{actor_id}/devtest/{path:path}")
        async def app_devtest(
            actor_id: str, request: Request, path: str = ""
        ) -> Response:  # pyright: ignore[reportUnusedFunction]
            return await self._handle_actor_request(
                request, actor_id, "devtest", path=path
            )

        # Actor methods
        @self.fastapi_app.get("/{actor_id}/methods")
        @self.fastapi_app.post("/{actor_id}/methods")
        @self.fastapi_app.put("/{actor_id}/methods")
        @self.fastapi_app.delete("/{actor_id}/methods")
        @self.fastapi_app.get("/{actor_id}/methods/{name:path}")
        @self.fastapi_app.post("/{actor_id}/methods/{name:path}")
        @self.fastapi_app.put("/{actor_id}/methods/{name:path}")
        @self.fastapi_app.delete("/{actor_id}/methods/{name:path}")
        async def app_methods(
            actor_id: str, request: Request, name: str = ""
        ) -> Response:  # pyright: ignore[reportUnusedFunction]
            return await self._handle_actor_request(
                request, actor_id, "methods", name=name
            )

        # Actor actions
        @self.fastapi_app.get("/{actor_id}/actions")
        @self.fastapi_app.post("/{actor_id}/actions")
        @self.fastapi_app.put("/{actor_id}/actions")
        @self.fastapi_app.delete("/{actor_id}/actions")
        @self.fastapi_app.get("/{actor_id}/actions/{name:path}")
        @self.fastapi_app.post("/{actor_id}/actions/{name:path}")
        @self.fastapi_app.put("/{actor_id}/actions/{name:path}")
        @self.fastapi_app.delete("/{actor_id}/actions/{name:path}")
        async def app_actions(
            actor_id: str, request: Request, name: str = ""
        ) -> Response:  # pyright: ignore[reportUnusedFunction]
            return await self._handle_actor_request(
                request, actor_id, "actions", name=name
            )

        # Third-party service OAuth2 callbacks and management
        @self.fastapi_app.get("/{actor_id}/services/{service_name}/callback")
        async def app_services_callback(  # pyright: ignore[reportUnusedFunction]
            actor_id: str,
            service_name: str,
            request: Request,
            code: str | None = None,
            state: str | None = None,
            error: str | None = None,
        ) -> Response:
            return await self._handle_actor_request(
                request,
                actor_id,
                "services",
                name=service_name,
                code=code,
                state=state,
                error=error,
            )

        @self.fastapi_app.delete("/{actor_id}/services/{service_name}")
        async def app_services_revoke(
            actor_id: str, service_name: str, request: Request
        ) -> Response:  # pyright: ignore[reportUnusedFunction]
            return await self._handle_actor_request(
                request, actor_id, "services", name=service_name
            )

    async def _normalize_request(self, request: Request) -> dict[str, Any]:
        """Convert FastAPI request to ActingWeb format."""
        # Read body asynchronously
        body = await request.body()

        # Parse cookies
        cookies = {}
        raw_cookies = request.headers.get("cookie")
        if raw_cookies:
            for cookie in raw_cookies.split("; "):
                if "=" in cookie:
                    name, value = cookie.split("=", 1)
                    cookies[name] = value

        # Convert headers (preserve case-sensitive header names)
        headers = {}
        for k, v in request.headers.items():
            # FastAPI normalizes header names to lowercase, but we need to preserve case
            # for compatibility with ActingWeb's auth system
            if k.lower() == "authorization":
                headers["Authorization"] = v
                # Authorization header found (no logging needed for routine operation)
            elif k.lower() == "content-type":
                headers["Content-Type"] = v
            else:
                headers[k] = v

        # If no Authorization header but we have an oauth_token cookie (web UI session),
        # provide it as a Bearer token so core auth can validate OAuth2 and authorize creator actions.
        if "Authorization" not in headers and "oauth_token" in cookies:
            headers["Authorization"] = f"Bearer {cookies['oauth_token']}"
            self.logger.debug(
                "FastAPI: Injected Authorization Bearer from oauth_token cookie for web UI request"
            )

        # Get query parameters and form data (similar to Flask's request.values)
        params = {}
        # Start with query parameters
        for k, v in request.query_params.items():
            params[k] = v

        # Parse form data if content type is form-encoded
        content_type = headers.get("Content-Type", "")
        if "application/x-www-form-urlencoded" in content_type and body:
            try:
                from urllib.parse import parse_qs

                body_str = (
                    body.decode("utf-8") if isinstance(body, bytes) else str(body)
                )
                form_data = parse_qs(body_str, keep_blank_values=True)
                # parse_qs returns lists, but we want single values like Flask
                for k, v_list in form_data.items():
                    if v_list:
                        params[k] = v_list[0]  # Take first value, like Flask
            except (UnicodeDecodeError, ValueError) as e:
                self.logger.warning(f"Failed to parse form data: {e}")

        # Debug logging for trust endpoint
        if "/trust" in str(request.url.path) and params:
            self.logger.debug(f"Trust query params: {params}")

        return {
            "method": request.method,
            "path": str(request.url.path),
            "data": body,
            "headers": headers,
            "cookies": cookies,
            "values": params,
            "url": str(request.url),
        }

    def _create_fastapi_response(self, webobj: AWWebObj, request: Request) -> Response:
        """Convert ActingWeb response to FastAPI response."""
        if webobj.response.redirect:
            logging.debug(
                f"_create_fastapi_response: Creating redirect response to {webobj.response.redirect}"
            )
            response: Response = RedirectResponse(
                url=webobj.response.redirect, status_code=302
            )
        else:
            # Create appropriate response based on content type
            content_type = webobj.response.headers.get("Content-Type", "")
            if "application/json" in content_type:
                try:
                    json_content = (
                        json.loads(webobj.response.body) if webobj.response.body else {}
                    )
                    response = JSONResponse(
                        content=json_content, status_code=webobj.response.status_code
                    )
                except (json.JSONDecodeError, TypeError):
                    response = Response(
                        content=webobj.response.body,
                        status_code=webobj.response.status_code,
                        headers=webobj.response.headers,
                    )
            elif "text/html" in content_type:
                response = HTMLResponse(
                    content=webobj.response.body,
                    status_code=webobj.response.status_code,
                )
            else:
                response = Response(
                    content=webobj.response.body,
                    status_code=webobj.response.status_code,
                    headers=webobj.response.headers,
                )

        # Set additional headers
        for key, value in webobj.response.headers.items():
            if key.lower() not in ["content-type", "content-length"]:
                response.headers[key] = value

        # Set cookies
        for cookie in webobj.response.cookies:
            response.set_cookie(
                key=cookie["name"],
                value=cookie["value"],
                max_age=cookie.get("max_age"),
                secure=cookie.get("secure", False),
                httponly=cookie.get("httponly", False),
            )

        return response

    async def _handle_factory_request(self, request: Request) -> Response:
        """Handle factory requests (actor creation)."""
        req_data = await self._normalize_request(request)
        webobj = AWWebObj(
            url=req_data["url"],
            params=req_data["values"],
            body=req_data["data"],
            headers=req_data["headers"],
            cookies=req_data["cookies"],
        )

        # Check if user is already authenticated and redirect to their actor
        oauth_cookie = request.cookies.get("oauth_token")
        self.logger.debug(
            f"Factory request: method={request.method}, has_oauth_cookie={bool(oauth_cookie)}"
        )
        if oauth_cookie and request.method == "GET":
            self.logger.debug(
                f"Processing GET request with OAuth cookie (length {len(oauth_cookie)})"
            )

            # First, check if this is an ActingWeb session token
            try:
                from ...oauth_session import get_oauth2_session_manager

                session_manager = get_oauth2_session_manager(self.aw_app.get_config())
                token_data = session_manager.validate_access_token(oauth_cookie)
                if token_data:
                    actor_id = token_data.get("actor_id")
                    if actor_id:
                        # Valid ActingWeb token - redirect to actor's www page
                        redirect_url = f"/{actor_id}/www"
                        self.logger.debug(
                            f"ActingWeb token valid - redirecting to {redirect_url}"
                        )
                        return RedirectResponse(url=redirect_url, status_code=302)
            except Exception as e:
                self.logger.debug(f"ActingWeb token validation failed: {e}")

            # Fall back to Google/GitHub OAuth token validation (legacy support)
            try:
                from ...oauth2 import create_oauth2_authenticator

                authenticator = create_oauth2_authenticator(self.aw_app.get_config())
                if authenticator.is_enabled():
                    self.logger.debug("OAuth2 is enabled, validating token...")
                    # Validate the token and get user info
                    user_info = authenticator.validate_token_and_get_user_info(
                        oauth_cookie
                    )
                    if user_info:
                        email = authenticator.get_email_from_user_info(
                            user_info, oauth_cookie
                        )
                        if email:
                            self.logger.debug(
                                f"Token validation successful for {email}"
                            )
                            # Look up actor by email
                            actor_instance = (
                                authenticator.lookup_or_create_actor_by_email(email)
                            )
                            if actor_instance and actor_instance.id:
                                # Redirect to actor's www page
                                redirect_url = f"/{actor_instance.id}/www"
                                self.logger.debug(
                                    f"Redirecting authenticated user {email} to {redirect_url}"
                                )
                                return RedirectResponse(
                                    url=redirect_url, status_code=302
                                )
                    # Token is invalid/expired - clear the cookie and redirect to new OAuth flow
                    self.logger.debug(
                        "OAuth token expired or invalid - clearing cookie and redirecting to OAuth"
                    )
                    original_url = str(request.url)
                    oauth_redirect = create_oauth_redirect_response(
                        self.aw_app.get_config(), redirect_after_auth=original_url
                    )
                    # Clear the expired cookie
                    oauth_redirect.delete_cookie("oauth_token", path="/")
                    return oauth_redirect
                else:
                    self.logger.warning("OAuth2 not enabled in config")
            except Exception as e:
                self.logger.error(f"OAuth token validation failed in factory: {e}")
                # Token validation failed - clear cookie and redirect to fresh OAuth
                self.logger.debug(
                    "OAuth token validation error - clearing cookie and redirecting to OAuth"
                )
                original_url = str(request.url)
                oauth_redirect = create_oauth_redirect_response(
                    self.aw_app.get_config(), redirect_after_auth=original_url
                )
                # Clear the invalid cookie
                oauth_redirect.delete_cookie("oauth_token", path="/")
                return oauth_redirect

        # Always use the standard factory handler
        handler = factory.RootFactoryHandler(
            webobj, self.aw_app.get_config(), hooks=self.aw_app.hooks
        )

        method_name = request.method.lower()
        handler_method = getattr(handler, method_name, None)
        if handler_method and callable(handler_method):
            # Run the synchronous handler in a thread pool to avoid blocking the event loop
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(self.executor, handler_method)
            except (KeyboardInterrupt, SystemExit):
                # Don't catch system signals
                raise
            except Exception as e:
                # Log the error but let ActingWeb handlers set their own response codes
                self.logger.error(f"Error in factory handler: {e}")

                # Check if the handler already set an appropriate response code
                if webobj.response.status_code != 200:
                    # Handler already set a status code, respect it
                    self.logger.debug(
                        f"Handler set status code: {webobj.response.status_code}"
                    )
                else:
                    # For network/SSL errors, set appropriate status codes
                    error_message = str(e).lower()
                    if "ssl" in error_message or "certificate" in error_message:
                        webobj.response.set_status(
                            502, "Bad Gateway - SSL connection failed"
                        )
                    elif "connection" in error_message or "timeout" in error_message:
                        webobj.response.set_status(
                            503, "Service Unavailable - Connection failed"
                        )
                    else:
                        webobj.response.set_status(500, "Internal server error")
        else:
            raise HTTPException(status_code=405, detail="Method not allowed")

        # Handle template rendering for factory
        if request.method == "GET" and webobj.response.status_code == 200:
            if self.templates:
                return self.templates.TemplateResponse(
                    "aw-root-factory.html",
                    {"request": request, **webobj.response.template_values},
                )
        elif request.method == "POST":
            # Only render templates for form submissions, not JSON requests
            content_type = request.headers.get("content-type", "")
            is_json_request = "application/json" in content_type
            if (
                not is_json_request
                and webobj.response.status_code in [200, 201]
                and self.templates
            ):
                return self.templates.TemplateResponse(
                    "aw-root-created.html",
                    {"request": request, **webobj.response.template_values},
                )
            elif (
                not is_json_request
                and webobj.response.status_code == 400
                and self.templates
            ):
                return self.templates.TemplateResponse(
                    "aw-root-failed.html",
                    {"request": request, **webobj.response.template_values},
                )

        return self._create_fastapi_response(webobj, request)

    async def _handle_factory_get_request(self, request: Request) -> Response:
        """Handle GET requests to factory route - call factory handler to populate OAuth vars."""
        # Create webobj using the same pattern as _handle_factory_request
        req_data = await self._normalize_request(request)
        webobj = AWWebObj(
            url=req_data["url"],
            params=req_data["values"],
            body=req_data["data"],
            headers=req_data["headers"],
            cookies=req_data["cookies"],
        )

        # Call the factory handler's get() method to populate OAuth template variables
        handler = factory.RootFactoryHandler(
            webobj, self.aw_app.get_config(), hooks=self.aw_app.hooks
        )

        # Run handler in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self.executor, handler.get)

        # Render template with populated values (including oauth_enabled, oauth_providers, etc.)
        if self.templates and webobj.response.template_values:
            return self.templates.TemplateResponse(
                "aw-root-factory.html",
                {"request": request, **webobj.response.template_values},
            )
        elif self.templates:
            return self.templates.TemplateResponse(
                "aw-root-factory.html", {"request": request}
            )
        else:
            # Fallback for when templates are not available
            return Response(
                """
                <html>
                <head><title>ActingWeb Demo</title></head>
                <body>
                    <h1>Welcome to ActingWeb Demo</h1>
                    <form action="/" method="post">
                        <label>Your Email: <input type="email" name="creator" required /></label>
                        <input type="submit" value="Create Actor" />
                    </form>
                </body>
                </html>
            """,
                media_type="text/html",
            )

    async def _handle_factory_post_with_oauth_redirect(
        self, request: Request
    ) -> Response:
        """Handle POST to factory route with OAuth2 redirect including email hint."""
        try:
            # Parse the form data to extract email
            req_data = await self._normalize_request(request)
            email = None

            # Try to get email from JSON body first
            if req_data["data"]:
                try:
                    data = json.loads(req_data["data"])
                    email = data.get("creator") or data.get("email")
                except (json.JSONDecodeError, ValueError):
                    pass

            # Fallback to form data
            if not email:
                email = req_data["values"].get("creator") or req_data["values"].get(
                    "email"
                )

            if not email:
                # No email provided - return error or redirect back to form
                if self.templates:
                    return self.templates.TemplateResponse(
                        "aw-root-factory.html",
                        {"request": request, "error": "Email is required"},
                    )
                else:
                    raise HTTPException(status_code=400, detail="Email is required")

            self.logger.debug(f"Factory POST with email: {email}")

            # Create OAuth2 redirect with email hint
            try:
                from ...oauth2 import create_oauth2_authenticator

                authenticator = create_oauth2_authenticator(self.aw_app.get_config())
                if authenticator.is_enabled():
                    # Create authorization URL with email hint and User-Agent
                    redirect_after_auth = str(
                        request.url
                    )  # Redirect back to factory after auth
                    user_agent = request.headers.get("user-agent", "")
                    auth_url = authenticator.create_authorization_url(
                        redirect_after_auth=redirect_after_auth,
                        email_hint=email,
                        user_agent=user_agent,
                    )

                    self.logger.debug(f"Redirecting to OAuth2 with email hint: {email}")
                    return RedirectResponse(url=auth_url, status_code=302)
                else:
                    self.logger.warning(
                        "OAuth2 not configured - falling back to standard actor creation"
                    )
                    # Fall back to standard actor creation without OAuth
                    return await self._handle_factory_post_without_oauth(request, email)

            except Exception as e:
                self.logger.error(f"Error creating OAuth2 redirect: {e}")
                # Fall back to standard actor creation if OAuth2 setup fails
                self.logger.debug(
                    "OAuth2 setup failed - falling back to standard actor creation"
                )
                return await self._handle_factory_post_without_oauth(request, email)

        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error in factory POST handler: {e}")
            raise HTTPException(status_code=500, detail="Internal server error") from e

    async def _handle_factory_post_without_oauth(
        self, request: Request, email: str
    ) -> Response:
        """Handle POST to factory route without OAuth2 - standard actor creation."""
        try:
            # Always use the standard factory handler
            req_data = await self._normalize_request(request)
            webobj = AWWebObj(
                url=req_data["url"],
                params=req_data["values"],
                body=req_data["data"],
                headers=req_data["headers"],
                cookies=req_data["cookies"],
            )

            # Use the standard factory handler
            handler = factory.RootFactoryHandler(
                webobj, self.aw_app.get_config(), hooks=self.aw_app.hooks
            )

            # Run the synchronous handler in a thread pool
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(self.executor, handler.post)

            # Handle template rendering for factory
            if webobj.response.status_code in [200, 201]:
                if self.templates:
                    return self.templates.TemplateResponse(
                        "aw-root-created.html",
                        {"request": request, **webobj.response.template_values},
                    )
            elif webobj.response.status_code == 400:
                if self.templates:
                    return self.templates.TemplateResponse(
                        "aw-root-failed.html",
                        {"request": request, **webobj.response.template_values},
                    )

            return self._create_fastapi_response(webobj, request)

        except Exception as e:
            self.logger.error(f"Error in standard actor creation: {e}")
            if self.templates:
                return self.templates.TemplateResponse(
                    "aw-root-failed.html",
                    {"request": request, "error": "Actor creation failed"},
                )
            else:
                raise HTTPException(
                    status_code=500, detail="Actor creation failed"
                ) from e

    async def _handle_google_oauth_callback(self, request: Request) -> Response:
        """Handle Google OAuth2 callback."""
        req_data = await self._normalize_request(request)
        webobj = AWWebObj(
            url=req_data["url"],
            params=req_data["values"],
            body=req_data["data"],
            headers=req_data["headers"],
            cookies=req_data["cookies"],
        )

        from ...handlers.oauth2_callback import OAuth2CallbackHandler

        handler = OAuth2CallbackHandler(
            webobj, self.aw_app.get_config(), hooks=self.aw_app.hooks
        )

        # Run the synchronous handler in a thread pool
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(self.executor, handler.get)

        # Handle redirect if needed
        if isinstance(result, dict) and result.get("redirect_required"):
            redirect_url = result.get("redirect_url")
            if redirect_url:
                webobj.response.set_redirect(redirect_url)
            else:
                # Convert result to JSON response
                webobj.response.body = json.dumps(result).encode("utf-8")
                webobj.response.headers["Content-Type"] = "application/json"

        # Handle OAuth2 errors with template rendering for better UX
        elif (
            isinstance(result, dict)
            and result.get("error")
            and webobj.response.status_code >= 400
        ):
            if self.templates and webobj.response.template_values:
                return self.templates.TemplateResponse(
                    "aw-root-failed.html",
                    {"request": request, **webobj.response.template_values},
                )

        return self._create_fastapi_response(webobj, request)

    async def _handle_oauth2_email(self, request: Request) -> Response:
        """Handle OAuth2 email input requests."""
        req_data = await self._normalize_request(request)
        webobj = AWWebObj(
            url=req_data["url"],
            params=req_data["values"],
            body=req_data["data"],
            headers=req_data["headers"],
            cookies=req_data["cookies"],
        )

        from ...handlers.oauth_email import OAuth2EmailHandler

        handler = OAuth2EmailHandler(
            webobj, self.aw_app.get_config(), hooks=self.aw_app.hooks
        )

        # Run the synchronous handler in a thread pool
        loop = asyncio.get_running_loop()
        if request.method == "POST":
            await loop.run_in_executor(self.executor, handler.post)
        else:
            await loop.run_in_executor(self.executor, handler.get)

        # Handle template rendering for email form
        if (
            hasattr(webobj.response, "template_values")
            and webobj.response.template_values
        ):
            if self.templates:
                try:
                    # App provides aw-oauth-email.html template
                    return self.templates.TemplateResponse(
                        "aw-oauth-email.html",
                        {"request": request, **webobj.response.template_values},
                    )
                except Exception as e:
                    # Template not found - provide basic HTML form as fallback
                    self.logger.warning(f"Template aw-oauth-email.html not found: {e}")
                    session_id = webobj.response.template_values.get("session_id", "")
                    error = webobj.response.template_values.get("error", "")
                    provider = webobj.response.template_values.get(
                        "provider_display", "OAuth provider"
                    )
                    message = webobj.response.template_values.get(
                        "message",
                        f"Your {provider} account does not have a public email. Please enter your email address to continue.",
                    )

                    fallback_html = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>Enter Email - ActingWeb</title>
                        <style>
                            body {{ font-family: Arial, sans-serif; max-width: 500px; margin: 50px auto; padding: 20px; }}
                            .error {{ color: red; margin-bottom: 15px; }}
                            .message {{ margin-bottom: 20px; color: #666; }}
                            input[type="email"] {{ width: 100%; padding: 10px; margin: 10px 0; }}
                            button {{ padding: 10px 20px; background: #4285f4; color: white; border: none; cursor: pointer; }}
                            button:hover {{ background: #357ae8; }}
                        </style>
                    </head>
                    <body>
                        <h1>Email Required</h1>
                        <p class="message">{message}</p>
                        {f'<p class="error">{error}</p>' if error else ""}
                        <form action="/oauth/email" method="POST">
                            <input type="hidden" name="session" value="{session_id}" />
                            <label>Email Address:
                                <input type="email" name="email" required placeholder="your@email.com" />
                            </label>
                            <button type="submit">Continue</button>
                        </form>
                    </body>
                    </html>
                    """
                    return HTMLResponse(content=fallback_html)

        return self._create_fastapi_response(webobj, request)

    async def _handle_email_verification(
        self, request: Request, actor_id: str
    ) -> Response:
        """Handle email verification requests."""
        req_data = await self._normalize_request(request)
        webobj = AWWebObj(
            url=req_data["url"],
            params=req_data["values"],
            body=req_data["data"],
            headers=req_data["headers"],
            cookies=req_data["cookies"],
        )

        from ...handlers.email_verification import EmailVerificationHandler

        handler = EmailVerificationHandler(
            webobj, self.aw_app.get_config(), hooks=self.aw_app.hooks
        )

        # Run the synchronous handler in a thread pool
        loop = asyncio.get_running_loop()
        if request.method == "POST":
            await loop.run_in_executor(self.executor, handler.post)
        else:
            await loop.run_in_executor(self.executor, handler.get)

        # Handle template rendering for email verification
        if (
            hasattr(webobj.response, "template_values")
            and webobj.response.template_values
        ):
            if self.templates:
                try:
                    # App provides aw-verify-email.html template
                    return self.templates.TemplateResponse(
                        "aw-verify-email.html",
                        {"request": request, **webobj.response.template_values},
                    )
                except Exception as e:
                    # Template not found - provide basic HTML as fallback
                    self.logger.warning(f"Template aw-verify-email.html not found: {e}")
                    status = webobj.response.template_values.get("status", "")
                    webobj.response.template_values.get("message", "")
                    email = webobj.response.template_values.get("email", "")
                    error = webobj.response.template_values.get("error", "")

                    if status == "success":
                        fallback_html = f"""
                        <!DOCTYPE html>
                        <html>
                        <head><title>Email Verified</title></head>
                        <body>
                            <h1>✓ Email Verified!</h1>
                            <p>Your email address <strong>{email}</strong> has been verified.</p>
                            <p><a href="/{actor_id}/www">Continue to Dashboard</a></p>
                        </body>
                        </html>
                        """
                    elif status == "error":
                        fallback_html = f"""
                        <!DOCTYPE html>
                        <html>
                        <head><title>Verification Failed</title></head>
                        <body>
                            <h1>Verification Failed</h1>
                            <p>{error}</p>
                            <p><a href="/{actor_id}/www">Return to Dashboard</a></p>
                        </body>
                        </html>
                        """
                    else:
                        fallback_html = """
                        <!DOCTYPE html>
                        <html>
                        <head><title>Email Verification</title></head>
                        <body>
                            <h1>Email Verification</h1>
                            <p>Please check your email for a verification link.</p>
                        </body>
                        </html>
                        """
                    return HTMLResponse(content=fallback_html)

        return self._create_fastapi_response(webobj, request)

    async def _handle_oauth2_endpoint(
        self, request: Request, endpoint: str
    ) -> Response:
        """Handle OAuth2 endpoints (register, authorize, token)."""
        req_data = await self._normalize_request(request)
        webobj = AWWebObj(
            url=req_data["url"],
            params=req_data["values"],
            body=req_data["data"],
            headers=req_data["headers"],
            cookies=req_data["cookies"],
        )

        from ...handlers.oauth2_endpoints import OAuth2EndpointsHandler

        handler = OAuth2EndpointsHandler(
            webobj, self.aw_app.get_config(), hooks=self.aw_app.hooks
        )

        # Run the synchronous handler in a thread pool
        loop = asyncio.get_running_loop()
        if request.method == "POST":
            result = await loop.run_in_executor(self.executor, handler.post, endpoint)
        elif request.method == "OPTIONS":
            result = await loop.run_in_executor(
                self.executor, handler.options, endpoint
            )
        else:
            result = await loop.run_in_executor(self.executor, handler.get, endpoint)

        # Check if handler set template values (for HTML response)
        if (
            hasattr(webobj.response, "template_values")
            and webobj.response.template_values
        ):
            self.logger.debug(
                f"OAuth2 template values found: {webobj.response.template_values}"
            )
            if self.templates:
                # This is an HTML template response
                template_name = (
                    "aw-oauth-authorization-form.html"  # Default OAuth2 template
                )
                try:
                    self.logger.debug(f"Attempting to render template: {template_name}")
                    return self.templates.TemplateResponse(
                        template_name,
                        {"request": request, **webobj.response.template_values},
                    )
                except Exception as e:
                    # Template not found or rendering error - fall back to JSON
                    self.logger.error(f"Template rendering failed: {e}")
                    from fastapi.responses import JSONResponse

                    return JSONResponse(
                        content={
                            "error": "template_error",
                            "error_description": f"Failed to render template: {str(e)}",
                            "template_values": webobj.response.template_values,
                        }
                    )
            else:
                self.logger.warning(
                    "Template values found but templates not initialized"
                )

        # Handle redirect responses (e.g., OAuth2 callbacks)
        if isinstance(result, dict) and result.get("status") == "redirect":
            redirect_url = result.get("location")
            if redirect_url:
                from fastapi.responses import RedirectResponse

                # Add CORS headers for OAuth2 redirect responses
                cors_headers = {
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Authorization, Content-Type, mcp-protocol-version",
                }

                return RedirectResponse(
                    url=redirect_url, status_code=302, headers=cors_headers
                )

        # Return the OAuth2 result as JSON with CORS headers
        from fastapi.responses import JSONResponse

        # Add CORS headers for OAuth2 endpoints
        cors_headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Authorization, Content-Type, mcp-protocol-version",
            "Access-Control-Max-Age": "86400",
        }

        # Merge handler headers (e.g., WWW-Authenticate) with CORS headers
        response_headers = dict(cors_headers)
        if hasattr(webobj.response, "headers"):
            for key, value in webobj.response.headers.items():
                response_headers[key] = value

        # Use status code from handler if set (e.g., 201 for client registration)
        status_code = (
            webobj.response.status_code
            if hasattr(webobj.response, "status_code")
            else 200
        )
        return JSONResponse(
            content=result, headers=response_headers, status_code=status_code
        )

    async def _handle_oauth2_spa_endpoint(
        self, request: Request, endpoint: str
    ) -> Response:
        """Handle SPA OAuth2 endpoints (config, authorize, token, revoke, session, logout)."""
        req_data = await self._normalize_request(request)
        webobj = AWWebObj(
            url=req_data["url"],
            params=req_data["values"],
            body=req_data["data"],
            headers=req_data["headers"],
            cookies=req_data["cookies"],
        )

        from ...handlers.oauth2_spa import OAuth2SPAHandler

        handler = OAuth2SPAHandler(
            webobj, self.aw_app.get_config(), hooks=self.aw_app.hooks
        )

        # Run the synchronous handler in a thread pool
        loop = asyncio.get_running_loop()
        if request.method == "POST":
            result = await loop.run_in_executor(self.executor, handler.post, endpoint)
        elif request.method == "OPTIONS":
            result = await loop.run_in_executor(
                self.executor, handler.options, endpoint
            )
        else:
            result = await loop.run_in_executor(self.executor, handler.get, endpoint)

        # SPA endpoints always return JSON
        from fastapi.responses import JSONResponse

        # Get origin for CORS
        origin = req_data["headers"].get("origin", "*")

        # Add CORS headers for SPA endpoints
        cors_headers = {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Authorization, Content-Type, Accept",
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Max-Age": "86400",
        }

        # Use status code from handler if set
        status_code = (
            webobj.response.status_code
            if hasattr(webobj.response, "status_code") and webobj.response.status_code
            else 200
        )

        response = JSONResponse(
            content=result, headers=cors_headers, status_code=status_code
        )

        # Copy cookies from handler response
        if hasattr(webobj.response, "cookies"):
            for cookie_data in webobj.response.cookies:
                # FastAPI uses 'key' instead of 'name' for cookie name
                response.set_cookie(
                    key=cookie_data["name"],
                    value=cookie_data["value"],
                    max_age=cookie_data.get("max_age"),
                    secure=cookie_data.get("secure", False),
                    httponly=cookie_data.get("httponly", False),
                    path=cookie_data.get("path", "/"),
                    samesite=cookie_data.get("samesite", "lax"),
                )

        return response

    async def _handle_spa_session_retrieve(
        self, request: Request, session_id: str
    ) -> Response:
        """
        Handle retrieval of pending SPA session data after OAuth callback.

        The OAuth callback handler processes the authorization code and stores
        the resulting tokens in a pending session. The SPA then retrieves this
        data using the session_id passed in the redirect URL.
        """
        from fastapi.responses import JSONResponse

        from ...oauth_session import get_oauth2_session_manager

        # Get origin for CORS
        req_data = await self._normalize_request(request)
        origin = req_data["headers"].get("origin", "*")

        cors_headers = {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Authorization, Content-Type, Accept",
            "Access-Control-Allow-Credentials": "true",
        }

        try:
            session_manager = get_oauth2_session_manager(self.aw_app.get_config())

            # Look up the pending session
            # The session was stored with pending_session_id as part of token_data
            session_data = session_manager.get_session(session_id)

            if not session_data:
                return JSONResponse(
                    content={"error": True, "message": "Session not found or expired"},
                    status_code=404,
                    headers=cors_headers,
                )

            # Extract the token data that was stored
            token_data = session_data.get("token_data", {})

            if not token_data or "access_token" not in token_data:
                return JSONResponse(
                    content={"error": True, "message": "Invalid session data"},
                    status_code=400,
                    headers=cors_headers,
                )

            # Pending session will expire naturally (short TTL)
            # This is one-time use by design - second retrieval will fail after expiry

            # Return the session data
            response_data = {
                "success": True,
                "access_token": token_data.get("access_token"),
                "actor_id": token_data.get("actor_id"),
                "email": token_data.get("email"),
                "expires_at": token_data.get("expires_at"),
                "redirect_url": token_data.get("redirect_url"),
            }

            return JSONResponse(
                content=response_data,
                status_code=200,
                headers=cors_headers,
            )

        except Exception as e:
            self.logger.error(f"Error retrieving SPA session: {e}")
            return JSONResponse(
                content={"error": True, "message": "Failed to retrieve session"},
                status_code=500,
                headers=cors_headers,
            )

    async def _handle_bot_request(self, request: Request) -> Response:
        """Handle bot requests."""
        req_data = await self._normalize_request(request)
        webobj = AWWebObj(
            url=req_data["url"],
            params=req_data["values"],
            body=req_data["data"],
            headers=req_data["headers"],
            cookies=req_data["cookies"],
        )

        handler = bot.BotHandler(
            webobj=webobj, config=self.aw_app.get_config(), hooks=self.aw_app.hooks
        )

        # Run the synchronous handler in a thread pool
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self.executor, handler.post, "/bot")

        return self._create_fastapi_response(webobj, request)

    async def _handle_mcp_request(self, request: Request) -> Response:
        """Handle MCP requests."""
        req_data = await self._normalize_request(request)
        webobj = AWWebObj(
            url=req_data["url"],
            params=req_data["values"],
            body=req_data["data"],
            headers=req_data["headers"],
            cookies=req_data["cookies"],
        )

        handler = mcp.MCPHandler(
            webobj, self.aw_app.get_config(), hooks=self.aw_app.hooks
        )

        # Execute appropriate method based on request method
        if request.method == "GET":
            # Run the synchronous handler in a thread pool
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(self.executor, handler.get)
        elif request.method == "POST":
            # Parse JSON body for POST requests
            try:
                if webobj.request.body:
                    data = json.loads(webobj.request.body)
                else:
                    data = {}
            except (json.JSONDecodeError, ValueError):
                data = {}

            # Run the synchronous handler in a thread pool
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(self.executor, handler.post, data)
        else:
            raise HTTPException(status_code=405, detail="Method not allowed")

        # Create JSON response - check if handler set a different status code (e.g., 401 for auth)
        status_code = 200
        headers = {}

        # Check if the handler set a custom status code in the response object
        if hasattr(webobj, "response") and hasattr(webobj.response, "status_code"):
            status_code = webobj.response.status_code

        # Check if the handler set custom headers (e.g., WWW-Authenticate for OAuth2)
        if hasattr(webobj, "response") and hasattr(webobj.response, "headers"):
            headers = dict(webobj.response.headers)

        return JSONResponse(content=result, status_code=status_code, headers=headers)

    async def _handle_oauth2_discovery_endpoint(
        self, request: Request, endpoint: str
    ) -> JSONResponse:
        """Handle OAuth2 discovery endpoints that return JSON directly."""
        req_data = await self._normalize_request(request)
        webobj = AWWebObj(
            url=req_data["url"],
            params=req_data["values"],
            body=req_data["data"],
            headers=req_data["headers"],
            cookies=req_data["cookies"],
        )

        from ...handlers.oauth2_endpoints import OAuth2EndpointsHandler

        handler = OAuth2EndpointsHandler(
            webobj, self.aw_app.get_config(), hooks=self.aw_app.hooks
        )

        # Run the synchronous handler in a thread pool
        loop = asyncio.get_running_loop()

        if request.method == "OPTIONS":
            result = await loop.run_in_executor(
                self.executor, handler.options, endpoint
            )
        else:
            result = await loop.run_in_executor(self.executor, handler.get, endpoint)

        # Add CORS headers directly for OAuth2 discovery endpoints
        cors_headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Authorization, Content-Type, mcp-protocol-version",
            "Access-Control-Max-Age": "86400",
        }

        return JSONResponse(content=result, headers=cors_headers)

    async def _handle_actor_request(
        self, request: Request, actor_id: str, endpoint: str, **kwargs: Any
    ) -> Response:
        """Handle actor-specific requests."""
        req_data = await self._normalize_request(request)
        webobj = AWWebObj(
            url=req_data["url"],
            params=req_data["values"],
            body=req_data["data"],
            headers=req_data["headers"],
            cookies=req_data["cookies"],
        )

        # Get appropriate handler
        handler = self._get_handler(endpoint, webobj, actor_id, **kwargs)
        if not handler:
            raise HTTPException(status_code=404, detail="Handler not found")

        # Execute handler method
        method_name = request.method.lower()
        handler_method = getattr(handler, method_name, None)
        if handler_method and callable(handler_method):
            # Build positional arguments based on endpoint and kwargs
            args = [actor_id]
            extra_kwargs = {}  # Initialize extra_kwargs for all endpoints

            if endpoint == "meta":
                args.append(kwargs.get("path", ""))
            elif endpoint == "trust":
                # Only pass path parameters if they exist, let handler read query params from request
                relationship = kwargs.get("relationship")
                peerid = kwargs.get("peerid")

                # Support UI forms that send GET /trust/<peerid>?_method=DELETE|PUT
                # by interpreting the single path segment as a peer ID.
                # We detect this when:
                #  - there is only one path param provided
                #  - a method override is present requesting DELETE or PUT
                #  - no explicit peerid path param is provided
                method_override = (webobj.request.get("_method") or "").upper()
                if relationship and not peerid and method_override in ("DELETE", "PUT"):
                    # Heuristic: treat the "relationship" path part as a peer ID.
                    # Pass empty relationship (type) and the detected peer ID.
                    args.append("")
                    args.append(relationship)
                    self.logger.debug(
                        f"Trust handler args adjusted for method override: {args} (peerid assumed from single segment)"
                    )
                else:
                    if relationship:
                        args.append(relationship)
                        if peerid:
                            args.append(peerid)
                    self.logger.debug(f"Trust handler args: {args}, kwargs: {kwargs}")
            elif endpoint == "subscriptions":
                if kwargs.get("peerid"):
                    args.append(kwargs["peerid"])
                if kwargs.get("subid"):
                    args.append(kwargs["subid"])
                if kwargs.get("seqnr"):
                    args.append(kwargs["seqnr"])
            elif endpoint in [
                "www",
                "properties",
                "callbacks",
                "resources",
                "devtest",
                "methods",
                "actions",
                "services",
            ]:
                # These endpoints take a path/name parameter
                param_name = "path" if endpoint in ["www", "devtest"] else "name"
                args.append(kwargs.get(param_name, ""))

                # Services need additional kwargs for OAuth callback parameters
                if endpoint == "services":
                    # Pass code, state, error as kwargs to the handler
                    extra_kwargs = {
                        k: v
                        for k, v in kwargs.items()
                        if k in ["code", "state", "error"] and v is not None
                    }

            # Run the synchronous handler in a thread pool to avoid blocking the event loop
            try:
                loop = asyncio.get_running_loop()
                if extra_kwargs:
                    # For services endpoint, pass extra kwargs
                    await loop.run_in_executor(
                        self.executor, lambda: handler_method(*args, **extra_kwargs)
                    )
                else:
                    await loop.run_in_executor(self.executor, handler_method, *args)
            except (KeyboardInterrupt, SystemExit):
                # Don't catch system signals
                raise
            except Exception as e:
                # Log the error but let ActingWeb handlers set their own response codes
                self.logger.error(f"Error in {endpoint} handler: {e}")

                # Check if the handler already set an appropriate response code
                if webobj.response.status_code != 200:
                    # Handler already set a status code, respect it
                    self.logger.debug(
                        f"Handler set status code: {webobj.response.status_code}"
                    )
                else:
                    # For network/SSL errors, set appropriate status codes
                    error_message = str(e).lower()
                    if "ssl" in error_message or "certificate" in error_message:
                        webobj.response.set_status(
                            502, "Bad Gateway - SSL connection failed"
                        )
                    elif "connection" in error_message or "timeout" in error_message:
                        webobj.response.set_status(
                            503, "Service Unavailable - Connection failed"
                        )
                    else:
                        webobj.response.set_status(500, "Internal server error")
        else:
            raise HTTPException(status_code=405, detail="Method not allowed")

        # Special handling for www endpoint templates
        if (
            endpoint == "www"
            and request.method == "GET"
            and webobj.response.status_code == 200
            and self.templates
        ):
            path = kwargs.get("path", "")
            template_map = {
                "": "aw-actor-www-root.html",
                "init": "aw-actor-www-init.html",
                "properties": "aw-actor-www-properties.html",
                "property": "aw-actor-www-property.html",
                "trust": "aw-actor-www-trust.html",
                "trust/new": "aw-actor-www-trust-new.html",
            }
            template_name = template_map.get(path)

            # Handle individual property pages like "properties/notes", "properties/demo_version"
            if not template_name and path.startswith("properties/"):
                # This is an individual property page
                template_name = "aw-actor-www-property.html"

            if template_name:
                return self.templates.TemplateResponse(
                    template_name,
                    {"request": request, **webobj.response.template_values},
                )

        return self._create_fastapi_response(webobj, request)

    def _get_handler(
        self, endpoint: str, webobj: AWWebObj, actor_id: str, **kwargs: Any
    ) -> Any | None:
        """Get the appropriate handler for an endpoint."""
        config = self.aw_app.get_config()

        # Special handling for services endpoint (not in base class)
        if endpoint == "services":
            return self._create_services_handler(webobj, config)

        # Use base class handler selection for all other endpoints
        return self.get_handler_class(endpoint, webobj, config, **kwargs)

    def _create_oauth_discovery_response(self) -> dict[str, Any]:
        """Create OAuth2 Authorization Server Discovery response (RFC 8414)."""
        config = self.aw_app.get_config()
        base_url = f"{config.proto}{config.fqdn}"
        oauth_provider = getattr(config, "oauth2_provider", "google")

        if oauth_provider == "google":
            return {
                "issuer": base_url,
                "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
                "token_endpoint": "https://oauth2.googleapis.com/token",
                "userinfo_endpoint": "https://www.googleapis.com/oauth2/v2/userinfo",
                "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
                "scopes_supported": ["openid", "email", "profile"],
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "subject_types_supported": ["public"],
                "id_token_signing_alg_values_supported": ["RS256"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": [
                    "client_secret_post",
                    "client_secret_basic",
                ],
            }
        elif oauth_provider == "github":
            return {
                "issuer": base_url,
                "authorization_endpoint": "https://github.com/login/oauth/authorize",
                "token_endpoint": "https://github.com/login/oauth/access_token",
                "userinfo_endpoint": "https://api.github.com/user",
                "scopes_supported": ["user:email"],
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code"],
                "subject_types_supported": ["public"],
                "token_endpoint_auth_methods_supported": [
                    "client_secret_post",
                    "client_secret_basic",
                ],
            }
        else:
            return {"error": "Unknown OAuth provider"}

    def _create_mcp_info_response(self) -> dict[str, Any]:
        """Create MCP information response."""
        config = self.aw_app.get_config()
        base_url = f"{config.proto}{config.fqdn}"
        oauth_provider = getattr(config, "oauth2_provider", "google")

        return {
            "mcp_enabled": True,
            "mcp_endpoint": "/mcp",
            "authentication": {
                "type": "oauth2",
                "provider": "actingweb",
                "required_scopes": ["mcp"],
                "flow": "authorization_code",
                "auth_url": f"{base_url}/oauth/authorize",
                "token_url": f"{base_url}/oauth/token",
                "callback_url": f"{base_url}/oauth/callback",
                "registration_endpoint": f"{base_url}/oauth/register",
                "authorization_endpoint": f"{base_url}/oauth/authorize",
                "token_endpoint": f"{base_url}/oauth/token",
                "discovery_url": f"{base_url}/.well-known/oauth-authorization-server",
                "resource_discovery_url": f"{base_url}/.well-known/oauth-protected-resource",
                "enabled": True,
            },
            "supported_features": ["tools", "prompts"],
            "tools_count": 4,  # search, fetch, create_note, create_reminder
            "prompts_count": 3,  # analyze_notes, create_learning_prompt, create_meeting_prep
            "actor_lookup": "email_based",
            "description": f"ActingWeb MCP Demo - AI can interact with actors through MCP protocol using {oauth_provider.title()} OAuth2",
        }

    def _create_services_handler(self, webobj: AWWebObj, config) -> Any:
        """Create services handler with service registry injection."""
        handler = services.ServicesHandler(webobj, config, hooks=self.aw_app.hooks)
        # Inject service registry into the handler so it can access it
        handler._service_registry = self.aw_app.get_service_registry()
        return handler
