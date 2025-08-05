# MCP Implementation Plan for ActingWeb - Revised Architecture

## Overview

This document outlines a clean, well-structured implementation for MCP (Model Context Protocol) support in ActingWeb, leveraging the official MCP Python SDK while implementing our own OAuth2 authorization server to handle the MCP client authentication flow.

### Key Insight: ActingWeb as OAuth2 Authorization Server

For MCP integration, ActingWeb must implement its own OAuth2 authorization server. This is because:

1. **MCP Clients Register Directly** - MCP clients (like ChatGPT) register their own client credentials with ActingWeb
2. **Dynamic Client Registration** - Each MCP client dynamically registers and receives unique credentials
3. **Token Issuance** - ActingWeb issues its own tokens to MCP clients, not Google/GitHub tokens
4. **Authentication Flow** - MCP clients authenticate with ActingWeb, which then proxies user authentication to Google

The flow preserves the existing user experience where users authenticate with Google, but wraps it in an OAuth2 server that MCP clients can interact with.

### Implementation Strategy

1. **Transport**: Focus on streamable HTTP with JSON only (no stdio, WebSocket, or SSE initially)
2. **Library Usage**: Use low-level MCP constructs rather than FastMCP to avoid confusion with existing FastAPI
3. **Token Validation**: `/mcp` endpoints validate ActingWeb-issued tokens, not Google tokens
4. **Client Storage**: Store MCP client credentials per-actor, but don't treat MCP clients as actors

### Endpoint Strategy: Implement OAuth2 Authorization Server

We need to implement standard OAuth2 server endpoints that MCP clients can use:

- `/oauth/register` - Dynamic client registration (RFC 7591) for MCP clients
- `/oauth/authorize` - Authorization endpoint that proxies to Google OAuth2
- `/oauth/token` - Token endpoint that issues ActingWeb tokens
- `/oauth/callback` - Callback from Google that completes the flow to MCP client
- `/.well-known/oauth-authorization-server` - OAuth2 discovery (RFC 8414)

## Key Architectural Decisions

### 1. Use Low-Level MCP Constructs
- Use low-level MCP protocol constructs from the official SDK
- Avoid FastMCP since we already have FastAPI integration
- Focus on protocol handling and message format compliance
- Implement streamable HTTP transport with JSON

### 2. Implement OAuth2 Authorization Server
- ActingWeb becomes an OAuth2 authorization server for MCP clients
- Dynamic client registration for each MCP client (e.g., ChatGPT)
- Issue ActingWeb tokens to MCP clients, not Google tokens
- Proxy user authentication to Google while maintaining MCP OAuth2 flow

### 3. Clean Separation of Concerns
- **MCP Protocol Layer**: HTTP transport with JSON streaming
- **OAuth2 Server Layer**: Full OAuth2 server implementation for MCP clients
- **Google OAuth2 Proxy**: Existing Google OAuth2 integration for user auth
- **Token Management**: Separate validation for ActingWeb vs Google tokens

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI/Flask App                         │
├─────────────────────────────────────────────────────────────┤
│                  Integration Layer                           │
│  ┌─────────────────────┐    ┌──────────────────────────┐   │
│  │   MCP Endpoints     │    │  OAuth2 Server Endpoints │   │
│  │  /mcp (HTTP+JSON)   │    │  /oauth/register         │   │
│  │  /mcp/tools         │    │  /oauth/authorize        │   │
│  │  /mcp/resources     │    │  /oauth/token            │   │
│  └─────────────────────┘    │  /oauth/callback         │   │
│                             └──────────────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│                     MCP Layer                                │
│  ┌─────────────────────┐    ┌──────────────────────────┐   │
│  │  MCP Protocol       │    │   Token Validation       │   │
│  │  - JSON Streaming   │    │  - ActingWeb tokens      │   │
│  │  - Tool Registry    │    │  - Per-endpoint auth     │   │
│  │  - HTTP Transport   │    └──────────────────────────┘   │
│  └─────────────────────┘                                    │
├─────────────────────────────────────────────────────────────┤
│              OAuth2 Authorization Server                     │
│  ┌─────────────────────┐    ┌──────────────────────────┐   │
│  │ Client Management   │    │  Token Management        │   │
│  │ - Dynamic reg.      │    │  - Issue ActingWeb tokens│   │
│  │ - Per-actor storage │    │  - Token validation      │   │
│  │ - Client secrets    │    │  - Refresh tokens        │   │
│  └─────────────────────┘    └──────────────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│                Google OAuth2 Integration                     │
│  - User authentication proxy                                 │
│  - Preserve existing GET / form → Google flow               │
│  - Exchange Google auth for ActingWeb tokens                │
├─────────────────────────────────────────────────────────────┤
│                  ActingWeb Core                              │
│  - Actors, Properties, Trust, Subscriptions                  │
└─────────────────────────────────────────────────────────────┘
```

## Implementation Structure

### 1. MCP HTTP Transport (`actingweb/mcp/`)

#### `http_transport.py` - HTTP+JSON Transport Implementation
```python
from mcp.types import Tool, Resource, ServerCapabilities
import json
from typing import Dict, Any, Optional

class ActingWebMCPTransport:
    """HTTP transport with JSON streaming for MCP."""
    
    def __init__(self, actor_id: str, hooks: HookRegistry):
        self.actor_id = actor_id
        self.hooks = hooks
        self.capabilities = self._build_capabilities()
        
    async def handle_request(self, method: str, params: Dict[str, Any], 
                           auth_token: str) -> Dict[str, Any]:
        """Handle MCP request over HTTP."""
        # Validate ActingWeb token (not Google token)
        if not await self._validate_actingweb_token(auth_token):
            raise ValueError("Invalid token")
            
        handlers = {
            "initialize": self._handle_initialize,
            "tools/list": self._handle_list_tools,
            "tools/call": self._handle_call_tool,
            "resources/list": self._handle_list_resources,
            "resources/read": self._handle_read_resource,
        }
        
        handler = handlers.get(method)
        if not handler:
            raise ValueError(f"Unknown method: {method}")
            
        return await handler(params)
    
    async def _validate_actingweb_token(self, token: str) -> bool:
        """Validate ActingWeb-issued token, not Google token."""
        # Token validation against ActingWeb's token store
        return await TokenManager.validate_token(token)
```

#### `auth_server.py` - OAuth2 Authorization Server
```python
import secrets
from datetime import datetime, timedelta

class ActingWebOAuth2Server:
    """OAuth2 authorization server for MCP clients."""
    
    async def register_client(self, registration_data: Dict[str, Any]) -> Dict[str, Any]:
        """Dynamic client registration for MCP clients."""
        client_id = f"mcp_{secrets.token_hex(16)}"
        client_secret = secrets.token_urlsafe(32)
        
        # Store per-actor, not as actor
        await self._store_client_credentials(
            client_id=client_id,
            client_secret=client_secret,
            client_name=registration_data.get("client_name"),
            redirect_uris=registration_data.get("redirect_uris", [])
        )
        
        return {
            "client_id": client_id,
            "client_secret": client_secret,
            "client_name": registration_data.get("client_name"),
            "token_endpoint": f"{self.base_url}/oauth/token",
            "authorization_endpoint": f"{self.base_url}/oauth/authorize"
        }
    
    async def authorize(self, client_id: str, redirect_uri: str, 
                       state: str, scope: str) -> str:
        """Handle authorization request - proxy to Google OAuth2."""
        # Validate client
        if not await self._validate_client(client_id, redirect_uri):
            raise ValueError("Invalid client or redirect URI")
        
        # Store MCP context and redirect to Google
        mcp_state = await self._create_mcp_state(client_id, state, redirect_uri)
        
        # Redirect to Google with our callback
        google_params = {
            "client_id": self.google_client_id,
            "redirect_uri": f"{self.base_url}/oauth/callback",
            "state": mcp_state,
            "scope": "openid email profile",
            "response_type": "code"
        }
        
        return self._build_google_auth_url(google_params)
```

### 2. OAuth2 Flow Implementation

#### OAuth2 Authorization Flow with Google Proxy
```python
class OAuth2FlowHandler:
    """Handles the complete OAuth2 flow for MCP clients."""
    
    async def handle_authorize(self, request: Request) -> Response:
        """
        Handle /oauth/authorize - Show same form as GET / then redirect to Google.
        """
        client_id = request.params.get("client_id")
        
        # For GET requests, show the email form (same as GET /)
        if request.method == "GET":
            return self._render_email_form(client_id=client_id, 
                                         state=request.params.get("state"),
                                         redirect_uri=request.params.get("redirect_uri"))
        
        # For POST, process email and redirect to Google
        email = request.form.get("email")
        if not email:
            return self._render_error("Email required")
        
        # Create state with MCP context
        mcp_state = self._encode_state({
            "client_id": client_id,
            "mcp_state": request.params.get("state"),
            "redirect_uri": request.params.get("redirect_uri"),
            "email_hint": email
        })
        
        # Redirect to Google OAuth2
        google_url = self._build_google_url(state=mcp_state, login_hint=email)
        return Response(redirect=google_url)
    
    async def handle_callback(self, request: Request) -> Response:
        """
        Handle /oauth/callback from Google - complete MCP client flow.
        """
        code = request.params.get("code")
        state = request.params.get("state")
        
        if not code:
            return self._handle_error(request.params.get("error"))
        
        # Decode MCP context from state
        mcp_context = self._decode_state(state)
        
        # Exchange code with Google
        google_token = await self._exchange_google_code(code)
        
        # Create ActingWeb token for MCP client
        actingweb_token = await self._create_actingweb_token(
            client_id=mcp_context["client_id"],
            user_email=google_token["email"],
            google_token=google_token
        )
        
        # Redirect back to MCP client with auth code
        auth_code = await self._create_auth_code(actingweb_token)
        
        redirect_uri = mcp_context["redirect_uri"]
        redirect_uri += f"?code={auth_code}&state={mcp_context['mcp_state']}"
        
        return Response(redirect=redirect_uri)
    
    async def handle_token(self, request: Request) -> Dict[str, Any]:
        """
        Handle /oauth/token - Exchange auth code for ActingWeb token.
        """
        grant_type = request.form.get("grant_type")
        
        if grant_type == "authorization_code":
            code = request.form.get("code")
            client_id = request.form.get("client_id")
            client_secret = request.form.get("client_secret")
            
            # Validate client
            if not self._validate_client(client_id, client_secret):
                raise ValueError("Invalid client credentials")
            
            # Exchange code for token
            token_data = await self._exchange_auth_code(code)
            
            return {
                "access_token": token_data["access_token"],
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token": token_data["refresh_token"]
            }
```

### 3. Token Management (`actingweb/mcp/token_manager.py`)

#### ActingWeb Token Management
```python
import secrets
import time
from typing import Dict, Any, Optional

class TokenManager:
    """Manages ActingWeb tokens for MCP clients."""
    
    def __init__(self, actor_interface):
        self.actor = actor_interface
        
    async def create_token(self, client_id: str, user_email: str, 
                          google_token: Dict[str, Any]) -> Dict[str, Any]:
        """Create ActingWeb token for MCP client."""
        token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(32)
        
        token_data = {
            "token": token,
            "refresh_token": refresh_token,
            "client_id": client_id,
            "user_email": user_email,
            "created_at": time.time(),
            "expires_at": time.time() + 3600,  # 1 hour
            "google_token": google_token  # Store for actor operations
        }
        
        # Store token data per-actor
        await self._store_token(token, token_data)
        
        return token_data
    
    async def validate_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Validate ActingWeb token (not Google token)."""
        token_data = await self._load_token(token)
        
        if not token_data:
            return None
            
        if time.time() > token_data["expires_at"]:
            return None
            
        return token_data
    
    async def refresh_token(self, refresh_token: str) -> Optional[Dict[str, Any]]:
        """Refresh ActingWeb token."""
        # Find token by refresh token
        token_data = await self._find_by_refresh_token(refresh_token)
        
        if not token_data:
            return None
            
        # Create new token
        new_token = secrets.token_urlsafe(32)
        token_data["token"] = new_token
        token_data["expires_at"] = time.time() + 3600
        
        await self._store_token(new_token, token_data)
        
        return token_data
```

### 4. Integration Layer Updates

#### Update Flask Integration (`actingweb/interface/integrations/flask_integration.py`)
```python
# Add MCP HTTP endpoints
@self.flask_app.route("/mcp", methods=["POST"])
def mcp_endpoint():
    """Handle MCP requests over HTTP with JSON."""
    return self._handle_mcp_request()

@self.flask_app.route("/mcp/tools", methods=["GET", "POST"])
def mcp_tools():
    """List or call MCP tools."""
    return self._handle_mcp_tools()

# OAuth2 server endpoints
@self.flask_app.route("/oauth/register", methods=["POST"])
def oauth_register():
    """Dynamic client registration for MCP clients."""
    return self._handle_oauth_register()

@self.flask_app.route("/oauth/authorize", methods=["GET", "POST"])
def oauth_authorize():
    """OAuth2 authorization - shows form then redirects to Google."""
    return self._handle_oauth_authorize()

@self.flask_app.route("/oauth/token", methods=["POST"])
def oauth_token():
    """Token endpoint - exchanges code for ActingWeb token."""
    return self._handle_oauth_token()

@self.flask_app.route("/oauth/callback")
def oauth_callback():
    """Callback from Google - completes MCP client flow."""
    return self._handle_oauth_callback()

@self.flask_app.route("/.well-known/oauth-authorization-server")
def oauth_discovery():
    """OAuth2 discovery endpoint."""
    return {
        "issuer": self.config.fqdn,
        "authorization_endpoint": f"{self.config.proto}{self.config.fqdn}/oauth/authorize",
        "token_endpoint": f"{self.config.proto}{self.config.fqdn}/oauth/token",
        "registration_endpoint": f"{self.config.proto}{self.config.fqdn}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["client_secret_post"]
    }
```

#### Update FastAPI Integration (`actingweb/interface/integrations/fastapi_integration.py`)
```python
# MCP HTTP endpoints
@self.fastapi_app.post("/mcp")
async def mcp_endpoint(request: Request):
    """Handle MCP requests over HTTP with JSON."""
    return await self._handle_mcp_request(request)

@self.fastapi_app.get("/mcp/tools")
@self.fastapi_app.post("/mcp/tools")
async def mcp_tools(request: Request):
    """List or call MCP tools."""
    return await self._handle_mcp_tools(request)

# OAuth2 server endpoints
@self.fastapi_app.post("/oauth/register")
async def oauth_register(request: Request):
    """Dynamic client registration for MCP clients."""
    return await self._handle_oauth_register(request)

@self.fastapi_app.get("/oauth/authorize")
@self.fastapi_app.post("/oauth/authorize")
async def oauth_authorize(request: Request):
    """OAuth2 authorization - shows form then redirects to Google."""
    return await self._handle_oauth_authorize(request)

@self.fastapi_app.post("/oauth/token")
async def oauth_token(request: Request):
    """Token endpoint - exchanges code for ActingWeb token."""
    return await self._handle_oauth_token(request)

@self.fastapi_app.get("/oauth/callback")
async def oauth_callback(request: Request):
    """Callback from Google - completes MCP client flow."""
    return await self._handle_oauth_callback(request)

@self.fastapi_app.get("/.well-known/oauth-authorization-server")
async def oauth_discovery():
    """OAuth2 discovery endpoint."""
    return {
        "issuer": self.config.fqdn,
        "authorization_endpoint": f"{self.config.proto}{self.config.fqdn}/oauth/authorize",
        "token_endpoint": f"{self.config.proto}{self.config.fqdn}/oauth/token",
        "registration_endpoint": f"{self.config.proto}{self.config.fqdn}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["client_secret_post"]
    }
```

### 5. Simplified Testing with fastapi_application.py

#### Add MCP test configuration
```python
# In fastapi_application.py
app = (
    ActingWebApp(
        aw_type="urn:actingweb:demo:fastapi",
        database="dynamodb",
        fqdn="localhost:5000"
    )
    .with_oauth(
        client_id=os.getenv("OAUTH_CLIENT_ID"),
        client_secret=os.getenv("OAUTH_CLIENT_SECRET")
    )
    .with_mcp(
        transport="websocket",  # or "sse"
        auth_required=True
    )
)

# Register MCP tools
@app.mcp_tool(name="search_notes", description="Search user notes")
async def search_notes(actor: ActorInterface, query: str) -> Dict[str, Any]:
    notes = actor.properties.get("notes", [])
    results = [n for n in notes if query.lower() in n.get("content", "").lower()]
    return {"results": results}
```

## OAuth2 Flow with ActingWeb as Authorization Server

The MCP authentication flow with ActingWeb as OAuth2 server:

```
MCP Client                ActingWeb              Google OAuth2
    |                         |                        |
    |--1. Register Client---->|                        |
    |<--client_id/secret------|                        |
    |                         |                        |
    |--2. GET /oauth/authorize->|                       |
    |<--3. Email form---------|                        |
    |                         |                        |
    |--4. POST email--------->|                        |
    |                         |--5. Redirect to------->|
    |                         |    Google with         |
    |                         |    ActingWeb context   |
    |                         |                        |
    |--6. User authorizes-----|----------------------->|
    |                         |<--7. Auth code---------|
    |                         |                        |
    |                         |--8. Exchange code----->|
    |                         |<--9. Google token------|
    |                         |                        |
    |<--10. Redirect with-----|                        |
    |      ActingWeb code     |                        |
    |                         |                        |
    |--11. Exchange code----->|                        |
    |<--12. ActingWeb token---|                        |
    |                         |                        |
    |--13. Call /mcp with---->|                        |
    |     Bearer token        |                        |
```

Key differences:
1. ActingWeb implements OAuth2 server endpoints
2. User still authenticates with Google
3. MCP client receives ActingWeb tokens, not Google tokens
4. /mcp endpoints validate ActingWeb tokens

## Testing Flow with mcp-inspector

### 1. Start Test Server
```bash
cd actingwebdemo
python fastapi_application.py
# Server runs at http://localhost:5000
```

### 2. OAuth2 Discovery
```bash
mcp-inspector discover http://localhost:5000/.well-known/oauth-authorization-server
```

### 3. Client Registration
```bash
mcp-inspector register http://localhost:5000/oauth/register \
    --client-name "MCP Inspector" \
    --client-type "mcp" \
    --oauth-provider "google" \
    --redirect-uri "http://localhost:8080/callback"
```

### 4. Authorization Flow
```bash
# Get authorization URL (redirects to Google/GitHub)
mcp-inspector authorize http://localhost:5000/oauth/authorize \
    --client-id <client_id> \
    --scope "openid email profile"

# User authorizes with Google/GitHub
# Callback returns to ActingWeb with auth code at /oauth/callback

# Exchange code for token
mcp-inspector token http://localhost:5000/oauth/token \
    --client-id <client_id> \
    --client-secret <client_secret> \
    --code <auth_code>
```

### 5. Connect via WebSocket
```bash
mcp-inspector connect ws://localhost:5000/mcp/websocket \
    --token <access_token>
```

## Key Design Decisions Explained

### 1. **ActingWeb as OAuth2 Authorization Server**
- MCP clients require OAuth2 server endpoints to register and authenticate
- ActingWeb must issue its own tokens that it can validate
- Google OAuth2 is used for user authentication, not client authentication
- This preserves the user experience while supporting MCP requirements

### 2. **HTTP+JSON Transport Only**
- Simplifies implementation by focusing on streamable HTTP
- Avoids complexity of WebSocket/SSE for initial implementation
- Compatible with existing FastAPI infrastructure
- Can add other transports later if needed

### 3. **Per-Actor Client Storage**
- MCP client credentials stored in actor properties
- Each actor can have multiple MCP clients authorized
- Clients are not treated as actors themselves
- Enables fine-grained access control

### 4. **Token Separation**
- ActingWeb tokens for MCP endpoints
- Google tokens for actor operations
- Clear security boundary between systems
- Prevents token confusion attacks

### 5. **Preserve Existing UX**
- GET /oauth/authorize shows familiar email form
- Users authenticate with Google as before
- Seamless experience for end users
- MCP complexity hidden from users

## Implementation Phases

### Phase 1: OAuth2 Authorization Server (1 week)
1. Implement OAuth2 server endpoints in handlers
2. Add dynamic client registration
3. Implement token management system
4. Add state encryption for CSRF protection
5. Test OAuth2 flow with standard clients

### Phase 2: MCP HTTP Transport (1 week)
1. Implement HTTP+JSON transport for MCP
2. Add tool discovery from hooks
3. Implement resource handling
4. Add per-endpoint token validation
5. Test with mcp-inspector

### Phase 3: Integration & Testing (3 days)
1. Complete Flask/FastAPI integration
2. Add comprehensive error handling
3. Full end-to-end testing
4. Documentation updates
5. Example MCP client implementation

## Configuration

```python
# config.py additions
class Config:
    # MCP Configuration
    mcp_enabled: bool = True
    mcp_transport: str = "http"  # Start with HTTP+JSON
    mcp_auth_required: bool = True
    
    # OAuth2 Server Configuration
    oauth2_server_enabled: bool = True
    oauth2_supported_grants: List[str] = ["authorization_code", "refresh_token"]
    oauth2_token_expires_in: int = 3600
    oauth2_refresh_token_expires_in: int = 2592000  # 30 days
    
    # Token Management
    actingweb_token_prefix: str = "aw_"  # Distinguish from Google tokens
    token_storage_property: str = "_mcp_tokens"  # Actor property for tokens
    client_storage_property: str = "_mcp_clients"  # Actor property for clients
```

## Security Considerations

### 1. **Token Security**
- ActingWeb tokens are distinct from Google tokens
- Short-lived access tokens (1 hour)
- Refresh token rotation on use
- Tokens stored encrypted in actor properties
- Token prefix prevents confusion attacks

### 2. **Client Authentication**
- Dynamic client registration with validation
- Client secrets stored per-actor
- Redirect URI whitelist enforcement
- PKCE support for public clients (future)

### 3. **State Parameter Protection**
- State encryption prevents CSRF attacks
- MCP context preserved through Google flow
- Time-limited state validity
- Replay attack prevention

### 4. **Transport Security**
- HTTPS required in production
- Bearer token validation on all MCP endpoints
- Rate limiting on OAuth2 endpoints
- Request signing for integrity (future)

## Summary

This revised architecture addresses all the key insights:

1. **OAuth2 Server Implementation** - ActingWeb implements full OAuth2 authorization server for MCP clients
2. **HTTP+JSON Transport** - Focus on streamable HTTP, avoiding WebSocket/SSE complexity initially
3. **Low-Level MCP Usage** - Use MCP protocol directly without FastMCP to avoid confusion
4. **Token Separation** - Clear distinction between ActingWeb and Google tokens
5. **Per-Actor Storage** - MCP clients stored per-actor without treating them as actors
6. **Preserved UX** - Users see the same email form and Google authentication flow

The implementation provides a secure, standards-compliant MCP server that integrates cleanly with ActingWeb's existing architecture while maintaining the familiar user experience.