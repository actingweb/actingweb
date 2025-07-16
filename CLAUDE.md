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
- **Properties/Trust/Subscription Handlers**: REST endpoints for core ActingWeb protocol

### Key Design Patterns
- Each actor has a unique root URL: `https://domain.com/{actor_id}`
- REST endpoints follow ActingWeb specification: `/properties`, `/trust`, `/subscriptions`, `/meta`
- Database operations are abstracted through `db_*` modules
- Authentication supports both basic auth and OAuth
- Configuration-driven feature enabling (UI, devtest, OAuth, etc.)

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

### Documentation
The project uses Sphinx for documentation:
```bash
# Generate documentation
make html

# Other Sphinx commands available via make
make help
```

## Configuration

Key configuration options in `actingweb/config.py`:
- `database`: Backend database type ('dynamodb' or 'gae')
- `ui`: Enable/disable web UI at `/www`
- `devtest`: Enable development/testing endpoints (MUST be False in production)
- `www_auth`: Authentication method ('basic' or 'oauth')
- `unique_creator`: Enforce unique creator field across actors
- `migrate_*`: Version migration flags

## Dependencies

Core dependencies (from setup.py):
- `pynamodb`: DynamoDB ORM
- `boto3`: AWS SDK
- `urlfetch`: HTTP client library

## Security Notes

- Always set `devtest = False` in production
- Use HTTPS in production (`proto = "https://"`)
- OAuth tokens and credentials are stored securely in actor properties
- Trust relationships must be established before data sharing
- Each actor maintains its own security boundary

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