# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is the ActingWeb Python library - a reference implementation of the ActingWeb REST protocol for distributed micro-services. It's designed for bot-to-bot communication and enables secure, granular sharing of user data across services.

## Architecture

The library follows a micro-services model where each user gets their own "actor" instance with a unique URL. The core components are:

### Core Classes
- **Actor** (`actingweb/actor.py`): Main class representing a user's instance/bot
- **Config** (`actingweb/config.py`): Configuration management with database, auth, and feature settings
- **Property** (`actingweb/property.py`): Key-value storage system for actor data
- **Trust** (`actingweb/trust.py`): Trust relationship management between actors
- **Subscription** (`actingweb/subscription.py`): Event subscription system between actors

### Database Abstraction
- **DynamoDB Implementation** (`actingweb/db_dynamodb/`): Production database backend using PynamoDB
- **Deprecated GAE Implementation** (`actingweb/deprecated_db_gae/`): Google App Engine datastore (legacy)

### HTTP Handlers
- **Base Handler** (`actingweb/handlers/base_handler.py`): Common handler functionality
- **Factory Handler** (`actingweb/handlers/factory.py`): Creates new actor instances
- **DevTest Handler** (`actingweb/handlers/devtest.py`): Development/testing endpoints (disable in production)
- **OAuth Handler** (`actingweb/handlers/oauth.py`): OAuth flow management
- **OAuth2 Callback Handler** (`actingweb/handlers/oauth2_callback.py`): OAuth2 callback processing with email validation
- **Properties/Trust/Subscription Handlers**: REST endpoints for core ActingWeb protocol

### Authentication System
- **Legacy OAuth** (`actingweb/oauth.py`): Original OAuth implementation
- **OAuth2 System** (`actingweb/oauth2.py`): Modern OAuth2 with Google/GitHub support
  - Email hint parameter support for improved UX
  - State parameter encryption with CSRF protection
  - Email validation to prevent identity confusion attacks
  - Provider auto-detection (Google/GitHub)

### Modern Interface
- **ActingWebApp** (`actingweb/interface/app.py`): Fluent API for application configuration
- **Flask Integration** (`actingweb/interface/integrations/flask_integration.py`): Auto Flask route generation
- **FastAPI Integration** (`actingweb/interface/integrations/fastapi_integration.py`): Async FastAPI support with OpenAPI docs
- **Actor Interface** (`actingweb/interface/actor_interface.py`): Modern actor management wrapper
- **Hook Registry** (`actingweb/interface/hook_registry.py`): Decorator-based event handling

### Key Design Patterns
- Each actor has a unique root URL: `https://domain.com/{actor_id}`
- REST endpoints follow ActingWeb specification: `/properties`, `/trust`, `/subscriptions`, `/meta`
- Database operations are abstracted through `db_*` modules
- Authentication supports basic auth, legacy OAuth, and modern OAuth2
- Configuration-driven feature enabling (UI, devtest, OAuth, MCP, etc.)
- Content negotiation: JSON for APIs, HTML templates for web browsers

## Development Commands

### Building and Distribution
```bash
# Build source and binary distributions
poetry build

# Upload to test server
poetry publish --repository pypitest

# Upload to production
poetry publish
```

### Development Environment
```bash
# Install dependencies and create virtual environment
poetry install

# Install with development dependencies
poetry install --with dev,docs

# Install git hooks (recommended for contributors)
bash scripts/install-git-hooks.sh

# Activate virtual environment
poetry shell

# Run commands in virtual environment
poetry run pytest
poetry run black .
poetry run mypy actingweb
```

### Git Hooks

The repository includes a pre-commit hook that automatically regenerates `docs/requirements.txt` when `pyproject.toml` is modified. This ensures ReadTheDocs can build documentation with the correct dependencies.

**Install the hook:**
```bash
bash scripts/install-git-hooks.sh
```

**What it does:**
- Detects when `pyproject.toml` is changed in a commit
- Runs `poetry export --with docs --without-hashes -o docs/requirements.txt`
- Automatically stages the updated `docs/requirements.txt`
- Fails the commit if export fails

**Manual regeneration:**
```bash
poetry export --with docs --without-hashes -o docs/requirements.txt
```

### Code Quality and Type Safety

This project maintains **zero errors and zero warnings** for both type checking and linting. The codebase uses comprehensive type annotations with pyright/pylance for static type checking and ruff for fast linting.

**Current Status:**
- ✅ Pyright: 0 errors, 0 warnings (across 13,000+ lines)
- ✅ Ruff: All checks passing
- ✅ Tests: 474/474 passing (100%)

#### Running Type Checks
```bash
# Pyright (primary type checker, used by VSCode Pylance)
poetry run pyright actingweb
poetry run pyright tests

# Check both at once
poetry run pyright actingweb tests

# Mypy (legacy, still supported)
poetry run mypy actingweb

# Ruff (linting and formatting)
poetry run ruff check actingweb tests
poetry run ruff format actingweb tests

# Auto-fix issues where possible
poetry run ruff check --fix actingweb tests
```

#### Type Annotation Guidelines

**Always use proper type annotations:**
```python
# Good - explicit types
def handle_method(actor: ActorInterface, method_name: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return {"result": "success"}

# Bad - missing types
def handle_method(actor, method_name, data):
    return {"result": "success"}
```

**For request body handling:**
```python
# Correct pattern for handling request.body
from typing import Union

body: Union[str, bytes, None] = self.request.body
if body is None:
    body_str = "{}"
elif isinstance(body, bytes):
    body_str = body.decode("utf-8", "ignore")
else:
    body_str = body
```

**For hook functions:**
```python
# Use Callable[..., Any] for flexible hook signatures
from typing import Callable, Any

def register_hook(self, func: Callable[..., Any]) -> None:
    # Implementation
    pass

def decorator_function(name: str) -> Callable[..., Any]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        # Implementation
        return func
    return decorator
```

#### Common Type Issues to Avoid

1. **Response Object Methods**
   - Use `response.write()` not `response.out.write()`
   - Use `response.headers["Content-Type"]` not `response.set_header()`

2. **OnAWBase Method Signatures**
   - All handler methods must exist in `on_aw.py`
   - Return types: `Optional[Dict[str, Any]]` for methods/actions, `bool` for delete operations

3. **Union Types**
   - Use `Union[str, bytes, None]` for request body types
   - Use `Optional[T]` instead of `T | None` for compatibility

4. **Missing Return Statements**
   - Always add `return` after error handling in try/except blocks
   - Avoid unreachable code after return statements

#### Pre-commit Quality Checks

Before committing changes, **always** run these checks to maintain zero-error status:
```bash
# Type checking (primary)
poetry run pyright actingweb tests

# Linting and auto-formatting
poetry run ruff check actingweb tests
poetry run ruff format actingweb tests

# Run tests
poetry run pytest tests/

# Optional: Legacy type checker
poetry run mypy actingweb
```

**Expected Result:** All commands should show zero errors and zero warnings.

#### Integration with IDEs

The repository includes VSCode configuration for optimal development:

**VS Code (Recommended):**
- Configuration provided in `.vscode/settings.json`
- Uses Pylance (pyright) for real-time type checking
- Uses Ruff for formatting and linting
- Auto-fixes on save enabled
- Type checking mode: "basic" (strict enough without being overly pedantic)

**PyCharm:**
- Enable Pyright external tool
- Configure Ruff as external formatter

**Vim/Neovim:**
- Use coc-pyright or ale for real-time type checking
- Configure ruff-lsp for linting

#### Configuration Files

The repository includes these configuration files:
- **`pyrightconfig.json`**: Pyright type checker configuration
- **`pyproject.toml`**: Ruff linting rules and Python package config
- **`.vscode/settings.json`**: VSCode editor settings

#### Type Checking in CI/CD

Add comprehensive checks to your CI pipeline:
```yaml
# Example GitHub Actions step
- name: Type check and lint
  run: |
    poetry run pyright actingweb tests
    poetry run ruff check actingweb tests
    poetry run pytest tests/
```

This ensures type safety is maintained across all contributions and prevents type-related runtime errors.

## Singleton Initialization

**CRITICAL:** ActingWeb's unified access control system requires explicit initialization of singletons at application startup to prevent performance issues during OAuth2 flows.

### Required at Application Startup

Add this to your application immediately after creating the ActingWeb app:

```python
from actingweb.interface import ActingWebApp
from actingweb.singleton_warmup import initialize_actingweb_singletons

# Create your ActingWeb app
app = ActingWebApp(...)

# CRITICAL: Initialize singletons at startup
try:
    initialize_actingweb_singletons(app.get_config())
    logger.info("ActingWeb singletons initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize ActingWeb singletons: {e}")
    # Continue anyway - the system will fall back gracefully
```

### What Gets Initialized

The singleton initialization sets up:

1. **Trust Type Registry** - Loads default and custom trust types
2. **Permission Evaluator** - Compiles patterns and sets up caches  
3. **Trust Permission Store** - Initializes attribute bucket access

### Performance Impact

**Without initialization:**
- OAuth2 flows take 4+ minutes (lazy loading blocks on first use)
- Permission checks cause delays during first MCP requests
- Database operations block request threads

**With initialization:**
- OAuth2 flows complete in <1 second
- Permission checks are fast from first use
- No blocking during request processing

### Debugging Initialization Issues

If initialization fails, check:

```bash
# Verify database connectivity
aws dynamodb list-tables

# Check environment variables
env | grep AWS

# Test basic ActingWeb functionality
python -c "from actingweb import actor; print('ActingWeb imports OK')"
```

Common issues:
- Missing AWS credentials or DynamoDB access
- Network connectivity problems
- Database table creation permissions

### Documentation
The project uses Sphinx for documentation:
```bash
# Generate documentation
make html

# Other Sphinx commands available via make
make help
```

## Configuration

### Modern Interface Configuration

The modern `ActingWebApp` interface uses fluent API for configuration:

```python
from actingweb.interface import ActingWebApp

app = (
    ActingWebApp(
        aw_type="urn:actingweb:example.com:myapp",
        database="dynamodb",
        fqdn="myapp.example.com",
        proto="https://"
    )
    .with_oauth(
        client_id="your-oauth-client-id",
        client_secret="your-oauth-client-secret",
        scope="openid email profile",
        auth_uri="https://accounts.google.com/o/oauth2/v2/auth",
        token_uri="https://oauth2.googleapis.com/token",
        redirect_uri="https://myapp.example.com/oauth/callback"
    )
    .with_web_ui(enable=True)
    .with_devtest(enable=False)  # MUST be False in production
    .with_mcp(enable=True)  # Enable/disable MCP functionality
    .with_unique_creator(enable=True)
    .with_email_as_creator(enable=True)
    .with_bot(
        token="bot-token",
        email="bot@example.com",
        secret="bot-secret"
    )
    .add_actor_type(
        name="myself",
        factory="https://myapp.example.com/",
        relationship="friend"
    )
)
```

### Configuration Options

**Core Settings:**
- `aw_type`: Unique identifier for your ActingWeb application type
- `database`: Backend database type ('dynamodb' recommended)
- `fqdn`: Fully qualified domain name where app is hosted
- `proto`: Protocol ('https://' for production, 'http://' for local dev)

**Feature Toggles:**
- `.with_web_ui(enable=bool)`: Enable/disable web UI at `/{actor_id}/www`
- `.with_devtest(enable=bool)`: Enable development/testing endpoints (MUST be False in production)
- `.with_mcp(enable=bool)`: Enable/disable MCP (Model Context Protocol) functionality
- `.with_unique_creator(enable=bool)`: Enforce unique creator field across actors
- `.with_email_as_creator(enable=bool)`: Force email property as creator

**Authentication Configuration:**
- `.with_oauth()`: Configure OAuth2 authentication with Google/GitHub/custom providers
- OAuth2 includes email validation, state encryption, and CSRF protection
- Legacy OAuth still supported for backward compatibility

**Bot Integration:**
- `.with_bot()`: Configure bot functionality for automated interactions
- Supports token-based authentication and admin room configuration

### Legacy Configuration

Key configuration options in `actingweb/config.py` (for legacy applications):
- `database`: Backend database type ('dynamodb' or 'gae')
- `ui`: Enable/disable web UI at `/www`
- `devtest`: Enable development/testing endpoints (MUST be False in production)
- `www_auth`: Authentication method ('basic' or 'oauth')
- `unique_creator`: Enforce unique creator field across actors
- `oauth2_provider`: OAuth2 provider name ('google' or 'github')
- `mcp`: Enable/disable MCP functionality
- `migrate_*`: Version migration flags

## Dependencies

Core dependencies (from setup.py):
- `pynamodb`: DynamoDB ORM
- `boto3`: AWS SDK
- `requests`: HTTP client library

## API Endpoints and Behavior

### Factory Endpoint (Actor Creation)

The factory endpoint (`POST /`) supports content negotiation:

**For API clients and test suites:**
- **Request**: `POST /` with `Content-Type: application/json` or `Accept: application/json`
- **Response**: `201 Created` with JSON body and proper headers:
  ```json
  {
    "id": "actor-id",
    "creator": "user@example.com", 
    "passphrase": "generated-passphrase"
  }
  ```
- **Headers**: `Content-Type: application/json`, `Location: https://domain.com/actor-id`

**For web browsers:**
- **GET** `/`: Shows HTML form for email input
- **POST** `/` from form: Returns HTML success/error page or redirects to OAuth2

### Testing Configuration

For running the standard ActingWeb test suite, use these settings:

```python
app = (
    ActingWebApp(...)
    .with_devtest(enable=True)  # Enable test endpoints
    .with_unique_creator(enable=False)  # Allow duplicate emails
    .with_mcp(enable=False)  # Disable MCP for cleaner testing
    # Comment out .with_oauth() to disable OAuth2
)
```

## Singleton Initialization

**CRITICAL**: For applications using the unified access control system, you MUST initialize ActingWeb singletons at application startup to avoid severe performance issues.

### Performance Impact

Without proper initialization:
- OAuth2 flows may hang for 4+ minutes
- First requests trigger expensive singleton initialization
- Database operations, system actor creation, and pattern compilation block request threads

### Required Initialization

Add this code at application startup, before serving requests:

```python
# CRITICAL: Initialize ActingWeb singletons at application startup
try:
    from actingweb.singleton_warmup import initialize_actingweb_singletons
    initialize_actingweb_singletons(app.get_config())
    logger.info("ActingWeb singletons initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize ActingWeb singletons: {e}")
    # Continue anyway - system will fall back gracefully with degraded performance
    logger.warning("Continuing with degraded performance - singletons will initialize lazily")
```

### What Gets Initialized

1. **Trust Type Registry**: Pre-compiles all trust types and their permissions
2. **Permission Evaluator**: Pre-loads system patterns and rule engine
3. **Trust Permission Store**: Initializes custom permission overrides system

### Debugging Singleton Issues

If you see these symptoms:
- OAuth2 callbacks hanging for minutes
- First requests extremely slow after startup
- Logs showing "Initializing trust type registry..." during requests

Then singleton initialization is happening during request processing instead of at startup.

**Check initialization logs:**
```
ActingWeb singletons initialized successfully
Trust type registry initialized with X types
Permission evaluator initialized successfully  
Trust permission store initialized
```

**Handle initialization failures:**
The system includes graceful fallbacks - if singleton initialization fails at startup, individual components will fall back to lazy loading with warnings.

## Security Notes

- Always set `devtest = False` in production
- Use HTTPS in production (`proto = "https://"`)
- OAuth2 includes email validation to prevent identity confusion attacks
- State parameter encryption provides CSRF protection
- OAuth tokens and credentials are stored securely in actor properties
- Trust relationships must be established before data sharing
- Each actor maintains its own security boundary
- Property storage automatically converts non-string values to JSON

## Code Quality Guidelines

To maintain code quality and avoid pylint/pylance issues, follow these guidelines when writing or modifying code:

### Type Safety
- **Always check for None values** before using objects that might be None:
  ```python
  # Good
  if obj is not None:
      result = obj.method()
  
  # Bad
  result = obj.method()  # obj might be None
  ```

- **Handle optional return values properly**:
  ```python
  # Good
  result = some_method()
  if result is None:
      return []
  return [item for item in result]
  
  # Bad
  return [item for item in some_method()]  # some_method() might return None
  ```

### Method Overrides
- **Match base class signatures exactly** when overriding methods:
  ```python
  # Good - parameter names and types match base class
  def method(self, param1: str, param2: Dict[str, Any]) -> bool:
  
  # Bad - parameter names don't match base class
  def method(self, param1: str, _param2: Dict[str, Any]) -> bool:
  ```

- **Return compatible types** when overriding methods:
  ```python
  # Good - returns same literal type as base class
  def get_callbacks(self, name):
      result = self.hook_registry.execute_callback_hooks(name, ...)
      return False  # Always return False like base class
  
  # Bad - returns generic bool instead of Literal[False]
  def get_callbacks(self, name):
      return bool(result)
  ```

### Import Management
- **Remove unused imports** immediately after editing:
  ```python
  # Good - only import what's used
  from typing import Dict, Optional
  
  # Bad - importing unused types
  from typing import Dict, Optional, List, Union  # List and Union not used
  ```

- **Use TYPE_CHECKING for forward references**:
  ```python
  from typing import TYPE_CHECKING
  if TYPE_CHECKING:
      from .some_module import SomeClass
  ```

### Function Attributes
- **Use setattr() for dynamic attribute assignment**:
  ```python
  # Good
  setattr(func, '_operations', operations)
  
  # Bad
  func._operations = operations  # Pylance error on function objects
  ```

### Response Type Handling
- **Be explicit about response types in web frameworks**:
  ```python
  # Good - wrap template responses
  return Response(render_template("template.html", **data))
  
  # Bad - return raw template string when Response expected
  return render_template("template.html", **data)
  ```

### Variable Binding
- **Initialize variables before conditional use**:
  ```python
  # Good
  import json
  data = {}
  if condition:
      data = json.loads(body)
  
  # Bad
  if condition:
      import json
      data = json.loads(body)
  # json might be unbound in exception handler
  ```

### Parameter Validation
- **Validate parameters early and fail fast**:
  ```python
  # Good
  if core_store is None:
      raise RuntimeError("Core store is required")
  self._store = CorePropertyStore(core_store)
  
  # Bad
  self._store = CorePropertyStore(core_store)  # core_store might be None
  ```

### Unused Parameters
- **Use `# pylint: disable=unused-argument` for interface compliance**:
  ```python
  def method(self, required_param, unused_param):  # pylint: disable=unused-argument
      """Method that must match interface but doesn't use all parameters."""
      return self.process(required_param)
  ```

### Callback Hook Types
- **Use `@app.callback_hook()` for actor-level callbacks** (e.g., `/<actor_id>/callbacks/<name>`):
  ```python
  @app.callback_hook("ping")
  def handle_ping(actor: ActorInterface, name: str, data: Dict[str, Any]) -> bool:
      return {"status": "pong", "actor_id": actor.id}
  ```

- **Use `@app.app_callback_hook()` for application-level callbacks** (e.g., `/bot`, `/oauth`):
  ```python
  @app.app_callback_hook("bot")
  def handle_bot(data: Dict[str, Any]) -> bool:
      # No actor context - this is application-level
      return True
  ```

## Runtime Context System

ActingWeb provides a runtime context system to solve the architectural constraint where hook functions have fixed signatures but need access to request-specific context.

### The Problem

**Hook Function Signatures Are Fixed:**
```python
def hook_function(actor, action_name, data) -> Any
```

**But Multiple Clients Access Same Actor:**
- MCP clients (ChatGPT, Claude, Cursor)
- Web browsers with different sessions
- OAuth2 API clients
- Each needs different behavior/formatting

### The Solution

**Runtime Context Attachment:**
```python
# During request authentication:
from actingweb.runtime_context import RuntimeContext

runtime_context = RuntimeContext(actor)
runtime_context.set_mcp_context(
    client_id="mcp_abc123",
    trust_relationship=trust_obj,
    peer_id="oauth2_client:user@example.com:mcp_abc123"
)

# In hook functions:
def handle_search(actor, action_name, data):
    from actingweb.runtime_context import RuntimeContext, get_client_info_from_context

    # Get client info for customization
    client_info = get_client_info_from_context(actor)
    if client_info:
        client_type = client_info["type"]  # "mcp", "oauth2", "web"
        client_name = client_info["name"]  # "Claude", "ChatGPT", etc.

        # Customize response based on client
        if client_type == "mcp" and "claude" in client_name.lower():
            # Use Claude-optimized formatting
            pass
```

### Context Types

**MCP Context** (for Model Context Protocol clients):
```python
runtime_context.set_mcp_context(
    client_id="mcp_abc123",
    trust_relationship=trust_record,  # Contains client_name, client_version
    peer_id="oauth2_client:user@example.com:mcp_abc123",
    token_data={"scope": "mcp", "expires_at": 1234567890}
)
```

**OAuth2 Context** (for API clients):
```python
runtime_context.set_oauth2_context(
    client_id="web_app_123",
    user_email="user@example.com",
    scopes=["read", "write"],
    token_data={"access_token": "...", "refresh_token": "..."}
)
```

**Web Context** (for browser sessions):
```python
runtime_context.set_web_context(
    session_id="sess_abc123",
    user_agent="Mozilla/5.0...",
    ip_address="192.168.1.1",
    authenticated_user="user@example.com"
)
```

### Helper Functions

**Unified Client Detection:**
```python
from actingweb.runtime_context import get_client_info_from_context

def detect_client_type(actor):
    client_info = get_client_info_from_context(actor)
    if client_info:
        return {
            "name": client_info["name"],      # "Claude", "ChatGPT", "Web Browser"
            "version": client_info["version"], # Client version if available
            "type": client_info["type"],      # "mcp", "oauth2", "web"
            "platform": client_info["platform"] # User agent or platform info
        }
    return None
```

### Request Type Detection

```python
def handle_action(actor, action_name, data):
    runtime_context = RuntimeContext(actor)
    request_type = runtime_context.get_request_type()

    if request_type == "mcp":
        # Handle MCP client request
        mcp_context = runtime_context.get_mcp_context()
        trust_relationship = mcp_context.trust_relationship

    elif request_type == "oauth2":
        # Handle API client request
        oauth2_context = runtime_context.get_oauth2_context()

    elif request_type == "web":
        # Handle web browser request
        web_context = runtime_context.get_web_context()
```

### Lifecycle Management

**Context is Request-Scoped:**
- Set during authentication/request processing
- Available throughout the request lifecycle
- Should be cleaned up after request completion
- Does not persist between requests

**Cleanup (Optional):**
```python
# Clean up after request processing (framework usually handles this)
runtime_context.clear_context()
```

### Extension for Custom Context

```python
# Add custom context types
runtime_context.set_custom_context("my_service", {
    "service_id": "svc_123",
    "api_version": "v2",
    "features": ["advanced_search", "export"]
})

# Access custom context
my_context = runtime_context.get_custom_context("my_service")
```

### Design Rationale

This approach was chosen because:

1. **Fixed Hook Signatures**: Can't modify `hook(actor, action_name, data)` without breaking compatibility
2. **Multi-Client Support**: Same actor serves multiple clients simultaneously
3. **No Framework Changes**: Works within existing ActingWeb architecture
4. **Type Safety**: Provides structured, documented context types
5. **Extensibility**: Can add new context types without breaking existing code

The runtime context is a pragmatic solution to the architectural constraint while maintaining clean, documented APIs.

### Before Committing
Always run these checks before committing code:
1. Ensure all pylance/mypy issues are resolved
2. Remove unused imports and variables
3. Test that method overrides maintain compatibility
4. Verify None checks are in place for optional values
5. Use correct hook types for application-level vs actor-level callbacks
6. Use RuntimeContext for request-specific context instead of ad-hoc attributes