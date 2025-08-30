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

# Activate virtual environment
poetry shell

# Run commands in virtual environment
poetry run pytest
poetry run black .
poetry run mypy actingweb
```

### Code Quality and Type Safety

This project uses comprehensive type annotations and mypy for static type checking. When making changes:

#### Running Type Checks
```bash
# Check all core modules
poetry run mypy actingweb

# Check specific files
poetry run mypy actingweb/handlers/methods.py actingweb/handlers/actions.py

# Check with error codes for better debugging
poetry run mypy actingweb --show-error-codes

# Check demo application
poetry run mypy application.py
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

Before committing changes, always run:
```bash
# Type checking
poetry run mypy actingweb

# Code formatting
poetry run black .

# Import sorting (if available)
poetry run isort .

# Syntax check
poetry run python -m py_compile actingweb/path/to/file.py
```

#### Integration with IDEs

For optimal development experience:
- **VS Code**: Install Python extension with mypy support
- **PyCharm**: Enable mypy inspection in settings
- **Vim/Neovim**: Use ale or coc-pyright for real-time type checking

#### Type Checking in CI/CD

Add type checking to your CI pipeline:
```yaml
# Example GitHub Actions step
- name: Type check with mypy
  run: |
    poetry run mypy actingweb
    poetry run mypy application.py
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
- `urlfetch`: HTTP client library

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

### Before Committing
Always run these checks before committing code:
1. Ensure all pylance/mypy issues are resolved
2. Remove unused imports and variables
3. Test that method overrides maintain compatibility
4. Verify None checks are in place for optional values
5. Use correct hook types for application-level vs actor-level callbacks