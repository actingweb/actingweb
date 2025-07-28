"""
FastAPI integration for ActingWeb applications.

Automatically generates FastAPI routes and handles request/response transformation
with async support.
"""

from typing import TYPE_CHECKING, Any, Dict, Optional, Union, List
from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials, HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
import asyncio
import concurrent.futures
import logging
import json
import base64

from ...aw_web_request import AWWebObj
from ...handlers import (
    callbacks,
    properties,
    meta,
    root,
    trust,
    devtest,
    subscription,
    resources,
    oauth,
    callback_oauth,
    bot,
    www,
    factory,
    methods,
    actions,
)

if TYPE_CHECKING:
    from ..app import ActingWebApp


# Pydantic Models for Type Safety


class ActorCreateRequest(BaseModel):
    """Request model for creating a new actor."""

    creator: str = Field(..., description="Email or identifier of the actor creator")
    passphrase: Optional[str] = Field(None, description="Optional passphrase for actor creation")
    type: Optional[str] = Field(None, description="Actor type, defaults to configured type")
    desc: Optional[str] = Field(None, description="Optional description for the actor")


class ActorResponse(BaseModel):
    """Response model for actor operations."""

    id: str = Field(..., description="Unique actor identifier")
    creator: str = Field(..., description="Email or identifier of the actor creator")
    url: str = Field(..., description="Full URL to the actor")
    type: str = Field(..., description="Actor type")
    desc: Optional[str] = Field(None, description="Actor description")


class PropertyRequest(BaseModel):
    """Request model for property operations."""

    value: Any = Field(..., description="Property value (can be any JSON type)")
    protected: Optional[bool] = Field(False, description="Whether this property is protected")


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
    desc: Optional[str] = Field(None, description="Optional description of the relationship")


class TrustResponse(BaseModel):
    """Response model for trust relationship operations."""

    type: str = Field(..., description="Type of trust relationship")
    peerid: str = Field(..., description="Peer actor identifier")
    baseuri: str = Field(..., description="Base URI of the peer actor")
    desc: Optional[str] = Field(None, description="Description of the relationship")


class SubscriptionRequest(BaseModel):
    """Request model for subscription operations."""

    peerid: str = Field(..., description="Peer actor identifier")
    hook: str = Field(..., description="Hook URL to be called")
    granularity: Optional[str] = Field("message", description="Subscription granularity")
    desc: Optional[str] = Field(None, description="Optional description")


class SubscriptionResponse(BaseModel):
    """Response model for subscription operations."""

    id: str = Field(..., description="Subscription identifier")
    peerid: str = Field(..., description="Peer actor identifier")
    hook: str = Field(..., description="Hook URL")
    granularity: str = Field(..., description="Subscription granularity")
    desc: Optional[str] = Field(None, description="Subscription description")


class CallbackRequest(BaseModel):
    """Request model for callback operations."""

    data: Dict[str, Any] = Field(default_factory=dict, description="Callback data")


class CallbackResponse(BaseModel):
    """Response model for callback operations."""

    result: Any = Field(..., description="Callback execution result")
    success: bool = Field(..., description="Whether callback executed successfully")


class MethodRequest(BaseModel):
    """Request model for method calls."""

    data: Dict[str, Any] = Field(default_factory=dict, description="Method parameters")


class MethodResponse(BaseModel):
    """Response model for method calls."""

    result: Any = Field(..., description="Method execution result")
    success: bool = Field(..., description="Whether method executed successfully")


class ActionRequest(BaseModel):
    """Request model for action triggers."""

    data: Dict[str, Any] = Field(default_factory=dict, description="Action parameters")


class ActionResponse(BaseModel):
    """Response model for action triggers."""

    result: Any = Field(..., description="Action execution result")
    success: bool = Field(..., description="Whether action executed successfully")


class ErrorResponse(BaseModel):
    """Standard error response model."""

    error: str = Field(..., description="Error message")
    status_code: int = Field(..., description="HTTP status code")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional error details")


# Dependency Injection Functions


async def get_actor_from_path(actor_id: str, request: Request) -> Optional[Dict[str, Any]]:
    """
    Dependency to extract and validate actor from path parameter.
    Returns actor data or None if not found.
    """
    # This would typically load the actor from database
    # For now, we'll return the actor_id for the handlers to process
    return {"id": actor_id, "request": request}


async def get_basic_auth(request: Request) -> Optional[Dict[str, str]]:
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


async def get_bearer_token(request: Request) -> Optional[str]:
    """
    Dependency to extract bearer token from Authorization header.
    Returns token string or None if not provided.
    """
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    return auth_header[7:]


async def validate_content_type(request: Request, expected: str = "application/json") -> bool:
    """
    Dependency to validate request content type.
    Returns True if content type matches expected type.
    """
    content_type = request.headers.get("content-type", "")
    return expected in content_type


async def get_json_body(request: Request) -> Dict[str, Any]:
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


class FastAPIIntegration:
    """
    FastAPI integration for ActingWeb applications.

    Automatically sets up all ActingWeb routes and handles request/response
    transformation between FastAPI and ActingWeb with async support.
    """

    def __init__(self, aw_app: "ActingWebApp", fastapi_app: FastAPI, templates_dir: Optional[str] = None):
        self.aw_app = aw_app
        self.fastapi_app = fastapi_app
        self.templates = Jinja2Templates(directory=templates_dir) if templates_dir else None
        self.logger = logging.getLogger(__name__)
        # Thread pool for running synchronous ActingWeb handlers
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=10, thread_name_prefix="aw-handler")
        
    def shutdown(self) -> None:
        """Shutdown the thread pool executor."""
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=True)

    def setup_routes(self) -> None:
        """Setup all ActingWeb routes in FastAPI."""

        # Root factory route
        @self.fastapi_app.get("/")
        @self.fastapi_app.post("/")
        async def app_root(request: Request) -> Response:
            return await self._handle_factory_request(request)

        # OAuth callback
        @self.fastapi_app.get("/oauth")
        async def app_oauth_callback(request: Request) -> Response:
            return await self._handle_oauth_callback(request)

        # Bot endpoint
        @self.fastapi_app.post("/bot")
        async def app_bot(request: Request) -> Response:
            return await self._handle_bot_request(request)

        # Actor root
        @self.fastapi_app.get("/{actor_id}")
        @self.fastapi_app.post("/{actor_id}")
        @self.fastapi_app.delete("/{actor_id}")
        async def app_actor_root(actor_id: str, request: Request) -> Response:
            return await self._handle_actor_request(request, actor_id, "root")

        # Actor meta
        @self.fastapi_app.get("/{actor_id}/meta")
        @self.fastapi_app.get("/{actor_id}/meta/{path:path}")
        async def app_meta(actor_id: str, request: Request, path: str = "") -> Response:
            return await self._handle_actor_request(request, actor_id, "meta", path=path)

        # Actor OAuth
        @self.fastapi_app.get("/{actor_id}/oauth")
        @self.fastapi_app.get("/{actor_id}/oauth/{path:path}")
        async def app_oauth(actor_id: str, request: Request, path: str = "") -> Response:
            return await self._handle_actor_request(request, actor_id, "oauth", path=path)

        # Actor www
        @self.fastapi_app.get("/{actor_id}/www")
        @self.fastapi_app.post("/{actor_id}/www")
        @self.fastapi_app.delete("/{actor_id}/www")
        @self.fastapi_app.get("/{actor_id}/www/{path:path}")
        @self.fastapi_app.post("/{actor_id}/www/{path:path}")
        @self.fastapi_app.delete("/{actor_id}/www/{path:path}")
        async def app_www(actor_id: str, request: Request, path: str = "") -> Response:
            return await self._handle_actor_request(request, actor_id, "www", path=path)

        # Actor properties
        @self.fastapi_app.get("/{actor_id}/properties")
        @self.fastapi_app.post("/{actor_id}/properties")
        @self.fastapi_app.put("/{actor_id}/properties")
        @self.fastapi_app.delete("/{actor_id}/properties")
        @self.fastapi_app.get("/{actor_id}/properties/{name:path}")
        @self.fastapi_app.post("/{actor_id}/properties/{name:path}")
        @self.fastapi_app.put("/{actor_id}/properties/{name:path}")
        @self.fastapi_app.delete("/{actor_id}/properties/{name:path}")
        async def app_properties(actor_id: str, request: Request, name: str = "") -> Response:
            return await self._handle_actor_request(request, actor_id, "properties", name=name)

        # Actor trust
        @self.fastapi_app.get("/{actor_id}/trust")
        @self.fastapi_app.post("/{actor_id}/trust")
        @self.fastapi_app.put("/{actor_id}/trust")
        @self.fastapi_app.delete("/{actor_id}/trust")
        @self.fastapi_app.get("/{actor_id}/trust/{relationship}")
        @self.fastapi_app.post("/{actor_id}/trust/{relationship}")
        @self.fastapi_app.put("/{actor_id}/trust/{relationship}")
        @self.fastapi_app.delete("/{actor_id}/trust/{relationship}")
        @self.fastapi_app.get("/{actor_id}/trust/{relationship}/{peerid}")
        @self.fastapi_app.post("/{actor_id}/trust/{relationship}/{peerid}")
        @self.fastapi_app.put("/{actor_id}/trust/{relationship}/{peerid}")
        @self.fastapi_app.delete("/{actor_id}/trust/{relationship}/{peerid}")
        async def app_trust(
            actor_id: str, request: Request, relationship: Optional[str] = None, peerid: Optional[str] = None
        ) -> Response:
            return await self._handle_actor_request(
                request, actor_id, "trust", relationship=relationship, peerid=peerid
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
        async def app_subscriptions(
            actor_id: str,
            request: Request,
            peerid: Optional[str] = None,
            subid: Optional[str] = None,
            seqnr: Optional[int] = None,
        ) -> Response:
            return await self._handle_actor_request(
                request, actor_id, "subscriptions", peerid=peerid, subid=subid, seqnr=seqnr
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
        async def app_resources(actor_id: str, request: Request, name: str = "") -> Response:
            return await self._handle_actor_request(request, actor_id, "resources", name=name)

        # Actor callbacks
        @self.fastapi_app.get("/{actor_id}/callbacks")
        @self.fastapi_app.post("/{actor_id}/callbacks")
        @self.fastapi_app.put("/{actor_id}/callbacks")
        @self.fastapi_app.delete("/{actor_id}/callbacks")
        @self.fastapi_app.get("/{actor_id}/callbacks/{name:path}")
        @self.fastapi_app.post("/{actor_id}/callbacks/{name:path}")
        @self.fastapi_app.put("/{actor_id}/callbacks/{name:path}")
        @self.fastapi_app.delete("/{actor_id}/callbacks/{name:path}")
        async def app_callbacks(actor_id: str, request: Request, name: str = "") -> Response:
            return await self._handle_actor_request(request, actor_id, "callbacks", name=name)

        # Actor devtest
        @self.fastapi_app.get("/{actor_id}/devtest")
        @self.fastapi_app.post("/{actor_id}/devtest")
        @self.fastapi_app.put("/{actor_id}/devtest")
        @self.fastapi_app.delete("/{actor_id}/devtest")
        @self.fastapi_app.get("/{actor_id}/devtest/{path:path}")
        @self.fastapi_app.post("/{actor_id}/devtest/{path:path}")
        @self.fastapi_app.put("/{actor_id}/devtest/{path:path}")
        @self.fastapi_app.delete("/{actor_id}/devtest/{path:path}")
        async def app_devtest(actor_id: str, request: Request, path: str = "") -> Response:
            return await self._handle_actor_request(request, actor_id, "devtest", path=path)

        # Actor methods
        @self.fastapi_app.get("/{actor_id}/methods")
        @self.fastapi_app.post("/{actor_id}/methods")
        @self.fastapi_app.put("/{actor_id}/methods")
        @self.fastapi_app.delete("/{actor_id}/methods")
        @self.fastapi_app.get("/{actor_id}/methods/{name:path}")
        @self.fastapi_app.post("/{actor_id}/methods/{name:path}")
        @self.fastapi_app.put("/{actor_id}/methods/{name:path}")
        @self.fastapi_app.delete("/{actor_id}/methods/{name:path}")
        async def app_methods(actor_id: str, request: Request, name: str = "") -> Response:
            return await self._handle_actor_request(request, actor_id, "methods", name=name)

        # Actor actions
        @self.fastapi_app.get("/{actor_id}/actions")
        @self.fastapi_app.post("/{actor_id}/actions")
        @self.fastapi_app.put("/{actor_id}/actions")
        @self.fastapi_app.delete("/{actor_id}/actions")
        @self.fastapi_app.get("/{actor_id}/actions/{name:path}")
        @self.fastapi_app.post("/{actor_id}/actions/{name:path}")
        @self.fastapi_app.put("/{actor_id}/actions/{name:path}")
        @self.fastapi_app.delete("/{actor_id}/actions/{name:path}")
        async def app_actions(actor_id: str, request: Request, name: str = "") -> Response:
            return await self._handle_actor_request(request, actor_id, "actions", name=name)

    async def _normalize_request(self, request: Request) -> Dict[str, Any]:
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
                # Debug logging for auth headers
                self.logger.debug(f"FastAPI: Found Authorization header: {v}")
            elif k.lower() == "content-type":
                headers["Content-Type"] = v  
            else:
                headers[k] = v

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
                body_str = body.decode("utf-8") if isinstance(body, bytes) else str(body)
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
            response: Response = RedirectResponse(url=webobj.response.redirect, status_code=302)
        else:
            # Create appropriate response based on content type
            content_type = webobj.response.headers.get("Content-Type", "")
            if "application/json" in content_type:
                try:
                    json_content = json.loads(webobj.response.body) if webobj.response.body else {}
                    response = JSONResponse(content=json_content, status_code=webobj.response.status_code)
                except (json.JSONDecodeError, TypeError):
                    response = Response(
                        content=webobj.response.body,
                        status_code=webobj.response.status_code,
                        headers=webobj.response.headers,
                    )
            elif "text/html" in content_type:
                response = HTMLResponse(content=webobj.response.body, status_code=webobj.response.status_code)
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

        # Check if we have a custom actor factory registered and this is a POST request
        if request.method == "POST" and self.aw_app.get_actor_factory():
            # Use the modern actor factory instead of the legacy handler
            await self._handle_custom_actor_creation(webobj, request)
        else:
            handler = factory.RootFactoryHandler(webobj, self.aw_app.get_config(), hooks=self.aw_app.hooks)

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
                        self.logger.debug(f"Handler set status code: {webobj.response.status_code}")
                    else:
                        # For network/SSL errors, set appropriate status codes
                        error_message = str(e).lower()
                        if "ssl" in error_message or "certificate" in error_message:
                            webobj.response.set_status(502, "Bad Gateway - SSL connection failed")
                        elif "connection" in error_message or "timeout" in error_message:
                            webobj.response.set_status(503, "Service Unavailable - Connection failed")
                        else:
                            webobj.response.set_status(500, "Internal server error")
            else:
                raise HTTPException(status_code=405, detail="Method not allowed")

        # Handle template rendering for factory
        if request.method == "GET" and webobj.response.status_code == 200:
            if self.templates:
                return self.templates.TemplateResponse(
                    "aw-root-factory.html", {"request": request, **webobj.response.template_values}
                )
        elif request.method == "POST":
            # Only render templates for form submissions, not JSON requests
            content_type = request.headers.get("content-type", "")
            is_json_request = "application/json" in content_type
            if not is_json_request and webobj.response.status_code in [200, 201] and self.templates:
                return self.templates.TemplateResponse(
                    "aw-root-created.html", {"request": request, **webobj.response.template_values}
                )
            elif not is_json_request and webobj.response.status_code == 400 and self.templates:
                return self.templates.TemplateResponse(
                    "aw-root-failed.html", {"request": request, **webobj.response.template_values}
                )

        return self._create_fastapi_response(webobj, request)

    async def _handle_custom_actor_creation(self, webobj: AWWebObj, request: Request) -> None:
        """Handle actor creation using registered actor factory function."""
        try:
            # Parse request data
            creator = None
            passphrase = None
            trustee_root = None
            
            if webobj.request.body:
                try:
                    data = json.loads(webobj.request.body)
                    creator = data.get("creator")
                    passphrase = data.get("passphrase", "")
                    trustee_root = data.get("trustee_root", "")
                except (json.JSONDecodeError, ValueError):
                    pass
            
            # Fallback to form data
            if not creator:
                creator = webobj.request.get("creator")
                passphrase = webobj.request.get("passphrase")
                trustee_root = webobj.request.get("trustee_root")
            
            if not creator:
                webobj.response.set_status(400, "Missing creator")
                return
            
            # Get the actor factory function
            factory_func = self.aw_app.get_actor_factory()
            if not factory_func:
                webobj.response.set_status(500, "No actor factory registered")
                return
            
            # Call the registered actor factory function
            # Use thread pool to avoid blocking the event loop
            loop = asyncio.get_running_loop()
            actor_interface = await loop.run_in_executor(
                self.executor, 
                lambda: factory_func(creator=creator, passphrase=passphrase)
            )
            
            if not actor_interface:
                webobj.response.set_status(400, "Actor creation failed")
                return
                
            # Set trustee_root if provided (mirroring the factory handler behavior)
            if trustee_root and len(trustee_root) > 0:
                # Get the underlying actor from the interface
                core_actor = actor_interface.core_actor
                if core_actor and core_actor.store:
                    core_actor.store.trustee_root = trustee_root
            
            # Set response data
            webobj.response.set_status(201, "Created")
            response_data = {
                "id": actor_interface.id,
                "creator": creator,
                "passphrase": actor_interface.passphrase or passphrase
            }
            
            # Add trustee_root to response if set (mirroring factory handler)
            if trustee_root and len(trustee_root) > 0:
                response_data["trustee_root"] = trustee_root
            
            self.logger.debug(f"FastAPI actor creation response: {response_data}")
                
            webobj.response.body = json.dumps(response_data)
            webobj.response.headers["Content-Type"] = "application/json"
            
            # Add Location header with the actor URL
            if actor_interface.url:
                webobj.response.headers["Location"] = actor_interface.url
            
        except Exception as e:
            self.logger.error(f"Error in custom actor creation: {e}")
            webobj.response.set_status(500, "Internal server error")

    async def _handle_oauth_callback(self, request: Request) -> Response:
        """Handle OAuth callback."""
        req_data = await self._normalize_request(request)
        webobj = AWWebObj(
            url=req_data["url"],
            params=req_data["values"],
            body=req_data["data"],
            headers=req_data["headers"],
            cookies=req_data["cookies"],
        )

        handler = callback_oauth.CallbackOauthHandler(webobj, self.aw_app.get_config(), hooks=self.aw_app.hooks)
        
        # Run the synchronous handler in a thread pool
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self.executor, handler.get)

        return self._create_fastapi_response(webobj, request)

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

        handler = bot.BotHandler(webobj=webobj, config=self.aw_app.get_config(), hooks=self.aw_app.hooks)
        
        # Run the synchronous handler in a thread pool
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self.executor, handler.post, "/bot")

        return self._create_fastapi_response(webobj, request)

    async def _handle_actor_request(self, request: Request, actor_id: str, endpoint: str, **kwargs: Any) -> Response:
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
            if endpoint == "meta":
                args.append(kwargs.get("path", ""))
            elif endpoint == "trust":
                # Only pass path parameters if they exist, let handler read query params from request
                if kwargs.get("relationship"):
                    args.append(kwargs["relationship"])
                    if kwargs.get("peerid"):
                        args.append(kwargs["peerid"])
                self.logger.debug(f"Trust handler args: {args}, kwargs: {kwargs}")
            elif endpoint == "subscriptions":
                if kwargs.get("peerid"):
                    args.append(kwargs["peerid"])
                if kwargs.get("subid"):
                    args.append(kwargs["subid"])
                if kwargs.get("seqnr"):
                    args.append(kwargs["seqnr"])
            elif endpoint in ["www", "properties", "callbacks", "resources", "devtest", "methods", "actions"]:
                # These endpoints take a path/name parameter
                param_name = "path" if endpoint in ["www", "devtest"] else "name"
                args.append(kwargs.get(param_name, ""))

            # Run the synchronous handler in a thread pool to avoid blocking the event loop
            try:
                loop = asyncio.get_running_loop()
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
                    self.logger.debug(f"Handler set status code: {webobj.response.status_code}")
                else:
                    # For network/SSL errors, set appropriate status codes
                    error_message = str(e).lower()
                    if "ssl" in error_message or "certificate" in error_message:
                        webobj.response.set_status(502, "Bad Gateway - SSL connection failed")
                    elif "connection" in error_message or "timeout" in error_message:
                        webobj.response.set_status(503, "Service Unavailable - Connection failed")
                    else:
                        webobj.response.set_status(500, "Internal server error")
        else:
            raise HTTPException(status_code=405, detail="Method not allowed")

        # Special handling for www endpoint templates
        if endpoint == "www" and request.method == "GET" and webobj.response.status_code == 200 and self.templates:
            path = kwargs.get("path", "")
            template_map = {
                "": "aw-actor-www-root.html",
                "init": "aw-actor-www-init.html",
                "properties": "aw-actor-www-properties.html",
                "property": "aw-actor-www-property.html",
                "trust": "aw-actor-www-trust.html",
            }
            template_name = template_map.get(path)
            if template_name:
                return self.templates.TemplateResponse(
                    template_name, {"request": request, **webobj.response.template_values}
                )

        return self._create_fastapi_response(webobj, request)

    def _get_handler(self, endpoint: str, webobj: AWWebObj, actor_id: str, **kwargs: Any) -> Optional[Any]:
        """Get the appropriate handler for an endpoint."""
        config = self.aw_app.get_config()

        handlers = {
            "root": lambda: root.RootHandler(webobj, config, hooks=self.aw_app.hooks),
            "meta": lambda: meta.MetaHandler(webobj, config, hooks=self.aw_app.hooks),
            "oauth": lambda: oauth.OauthHandler(webobj, config, hooks=self.aw_app.hooks),
            "www": lambda: www.WwwHandler(webobj, config, hooks=self.aw_app.hooks),
            "properties": lambda: properties.PropertiesHandler(webobj, config, hooks=self.aw_app.hooks),
            "resources": lambda: resources.ResourcesHandler(webobj, config, hooks=self.aw_app.hooks),
            "callbacks": lambda: callbacks.CallbacksHandler(webobj, config, hooks=self.aw_app.hooks),
            "devtest": lambda: devtest.DevtestHandler(webobj, config, hooks=self.aw_app.hooks),
            "methods": lambda: methods.MethodsHandler(webobj, config, hooks=self.aw_app.hooks),
            "actions": lambda: actions.ActionsHandler(webobj, config, hooks=self.aw_app.hooks),
        }

        # Special handling for trust endpoint
        if endpoint == "trust":
            relationship = kwargs.get("relationship")
            peerid = kwargs.get("peerid")
            
            self.logger.debug(f"Trust handler selection - relationship: {relationship!r}, peerid: {peerid!r}, kwargs: {kwargs}")
            
            # For trust endpoint, we need to distinguish between path parameters and query parameters
            # If peerid appears in query params but not as path param, it's a query-based request
            query_peerid = webobj.request.get("peerid")
            self.logger.debug(f"Query peerid: {query_peerid!r}")
            
            # Only count actual path parameters (non-None, non-empty)
            path_parts = []
            if relationship is not None and relationship != "":
                path_parts.append(relationship)
            # Only count peerid as path param if it's not a query param request
            if peerid is not None and peerid != "" and not query_peerid:
                path_parts.append(peerid)
            
            self.logger.debug(f"Trust handler selection - path_parts: {path_parts}, len: {len(path_parts)}")
            
            if len(path_parts) == 0:
                self.logger.debug("Selecting TrustHandler for query parameter request")
                return trust.TrustHandler(webobj, config, hooks=self.aw_app.hooks)
            elif len(path_parts) == 1:
                self.logger.debug("Selecting TrustRelationshipHandler for single path parameter")
                return trust.TrustRelationshipHandler(webobj, config, hooks=self.aw_app.hooks)
            else:
                self.logger.debug("Selecting TrustPeerHandler for two path parameters")
                return trust.TrustPeerHandler(webobj, config, hooks=self.aw_app.hooks)

        # Special handling for subscriptions endpoint
        if endpoint == "subscriptions":
            path_parts = [p for p in [kwargs.get("peerid"), kwargs.get("subid")] if p]
            seqnr = kwargs.get("seqnr")

            if len(path_parts) == 0:
                return subscription.SubscriptionRootHandler(webobj, config, hooks=self.aw_app.hooks)
            elif len(path_parts) == 1:
                return subscription.SubscriptionRelationshipHandler(webobj, config, hooks=self.aw_app.hooks)
            elif len(path_parts) == 2 and seqnr is None:
                return subscription.SubscriptionHandler(webobj, config, hooks=self.aw_app.hooks)
            else:
                return subscription.SubscriptionDiffHandler(webobj, config, hooks=self.aw_app.hooks)

        if endpoint in handlers:
            return handlers[endpoint]()

        return None
