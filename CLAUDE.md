# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is the ActingWeb Python library - a reference implementation of the ActingWeb REST protocol for distributed micro-services. It's designed for bot-to-bot communication and enables secure, granular sharing of user data across services.

## Project Documentation System

The project uses a structured documentation system in `thoughts/shared/` to track research, planning, patterns, and completed work. This system helps maintain institutional knowledge and provides context for development decisions.

### Directory Structure

```
thoughts/shared/
├── research/          # Research documents analyzing features and architecture
├── patterns/          # Reusable patterns and best practices
├── plans/            # Planning documents for upcoming work (dated YYYY-MM-DD)
├── completed/        # Completed work documentation (dated YYYY-MM-DD)
└── *.md              # General documentation (test requirements, etc.)
```

### Document Types and Usage

#### Research Documents (`research/`)

**Purpose**: Deep analysis of architectural decisions, feature designs, and technical investigations.

**Example**: `2025-12-12-unified-handler-architecture.md`
- Analyzes current architecture
- Identifies gaps and issues
- Proposes solutions and improvements
- Documents trade-offs and design rationale

**When to create**: When investigating a complex architectural question or evaluating multiple design approaches.

#### Pattern Documents (`patterns/`)

**Purpose**: Reusable patterns, best practices, and established conventions that should be followed across the codebase.

**Example**: `handler-refactoring-pattern.md`
- Step-by-step refactoring guide
- Code examples showing before/after
- Success metrics and verification steps
- Testing requirements (unit tests + integration tests)
- Anti-patterns to avoid

**When to create**: When you've successfully solved a problem that will need to be repeated (e.g., refactoring multiple similar files).

**Key characteristics**:
- Prescriptive (tells you HOW to do something)
- Includes concrete code examples
- Lists success criteria and verification steps
- Should be reusable across multiple similar tasks

#### Planning Documents (`plans/`)

**Purpose**: Track upcoming work, implementation plans, gap analysis, and progress on initiatives.

**Naming**: `YYYY-MM-DD-description.md` (e.g., `2025-12-13-unified-handler-gaps.md`)

**Structure**:
- Overview and objectives
- Gaps identified (what's missing)
- Phase-by-phase implementation plan
- Success criteria for each phase
- Progress tracking (checkboxes)
- Verification steps

**Example**: `2025-12-13-unified-handler-gaps.md`
- Lists all gaps between research and implementation
- Breaks work into 7 phases
- Tracks completion with checkboxes
- Documents dependencies between phases
- Includes risk mitigation strategies

**When to create**: Before starting a major initiative or when planning multi-phase work.

**When to update**: As phases complete, check off items and update status sections.

#### Completed Work (`completed/`)

**Purpose**: Document completed initiatives, refactorings, or feature implementations for future reference.

**Naming**: `YYYY-MM-DD-description.md` (e.g., `2025-12-14-trust-handler-refactoring.md`)

**Structure**:
- Executive summary
- What was changed and why
- Code metrics (lines added/changed/deleted)
- Test coverage added
- Files modified
- Verification results
- Lessons learned

**Example**: `2025-12-14-handler-refactoring-initiative-complete.md`
- Summarizes 6-handler refactoring initiative
- Provides before/after architecture diagrams
- Lists all files modified
- Documents test coverage (46 unit tests, 79+ integration tests)
- Tracks metrics (308 lines added to developer API)
- Key learnings and success factors

**When to create**: When completing a significant piece of work that others might need to reference later.

### Workflow Examples

#### Starting a New Initiative

1. **Research** (`research/`) - Analyze the problem
2. **Plan** (`plans/YYYY-MM-DD-*.md`) - Create implementation plan
3. **Pattern** (`patterns/*.md`) - Document reusable approaches (if applicable)
4. **Complete** (`completed/YYYY-MM-DD-*.md`) - Document results when done

#### Iterative Development

```
Day 1: Create plan document in plans/
Day 2-5: Implement Phase 1, update checkboxes in plan
Day 6: Complete Phase 1, update plan with ✅
Day 7-10: Implement Phase 2, update checkboxes
...
Final: Move plan summary to completed/, create completion doc
```

#### Reusing Patterns

When starting similar work:
1. Check `patterns/` for established approaches
2. Follow the pattern's step-by-step guide
3. Update pattern if improvements are discovered
4. Reference pattern in your completion doc

### Best Practices

**For Research Documents:**
- Start with clear problem statement
- Document current state thoroughly
- List alternatives considered
- Explain why chosen approach is best
- Include diagrams where helpful

**For Pattern Documents:**
- Make it step-by-step and prescriptive
- Include complete code examples
- List all success criteria
- Document both good and bad examples
- Keep it up-to-date as patterns evolve

**For Planning Documents:**
- Use checkboxes for tracking progress
- Break work into logical phases
- Document dependencies between phases
- Include verification steps for each phase
- Update regularly as work progresses
- Mark items with ✅ COMPLETE when done

**For Completion Documents:**
- Summarize what was accomplished
- Include metrics (lines changed, tests added)
- Document all files modified
- List lessons learned
- Provide verification evidence (test results)

### Example Documentation Flow

**Handler Refactoring Initiative:**

1. **Research**: `research/2025-12-12-unified-handler-architecture.md`
   - Analyzed all 6 handlers
   - Found 4 needed refactoring, 2 were clean
   - Proposed developer API extensions

2. **Pattern**: `patterns/handler-refactoring-pattern.md`
   - Established 5-step refactoring process
   - Documented testing requirements
   - Created reusable template

3. **Plan**: `plans/2025-12-13-unified-handler-gaps.md`
   - Listed 6 gap categories
   - Created 7-phase implementation plan
   - Tracked progress with checkboxes

4. **Individual Completions**:
   - `completed/2025-12-14-subscription-handler-refactoring.md`
   - `completed/2025-12-14-trust-handler-refactoring.md`
   - `completed/2025-12-14-properties-handler-refactoring.md`
   - `completed/2025-12-14-callbacks-handler-refactoring.md`

5. **Final Summary**: `completed/2025-12-14-handler-refactoring-initiative-complete.md`
   - Consolidated all results
   - Provided grand totals (382 lines added, 46 unit tests)
   - Documented architecture transformation
   - Listed key learnings

### Finding Relevant Documentation

**Before starting work:**
```bash
# Check for existing patterns
ls thoughts/shared/patterns/

# Check for related research
grep -r "your topic" thoughts/shared/research/

# Check active plans
ls thoughts/shared/plans/
```

**Looking for completed examples:**
```bash
# Find similar work
ls thoughts/shared/completed/ | grep handler

# Read completion doc for reference
cat thoughts/shared/completed/2025-12-14-trust-handler-refactoring.md
```

### When to Create Each Document Type

| Situation | Document Type | Example |
|-----------|---------------|---------|
| Investigating architecture | `research/` | "Should we use hooks or direct calls?" |
| Found reusable solution | `patterns/` | "Handler refactoring pattern" |
| Planning multi-phase work | `plans/` | "Gap implementation plan" |
| Finished significant work | `completed/` | "Trust handler refactoring complete" |
| General reference | Root level | "Test requirements from actingweb_mcp" |

### Integration with CLAUDE.md

This documentation system complements CLAUDE.md:
- **CLAUDE.md**: Guidance for Claude Code on how to work with the codebase
- **thoughts/shared/**: Historical context, design decisions, completed work

When working on the codebase:
1. Check CLAUDE.md for current architecture and patterns
2. Check `thoughts/shared/patterns/` for established practices
3. Check `thoughts/shared/research/` for design rationale
4. Check `thoughts/shared/plans/` for ongoing initiatives
5. Document completed work in `thoughts/shared/completed/`

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
- **Authenticated Views** (`actingweb/interface/authenticated_views.py`): Permission-enforced actor access

### Authenticated Views

The authenticated views system provides permission-enforced access to actor resources. Three access modes are supported:

**1. Owner Mode** (direct ActorInterface access - full access):
```python
actor = ActorInterface(core_actor)
actor.properties["any_property"] = value  # Full access, no permission checks
```

**2. Peer Mode** (actor-to-actor access):
```python
peer_view = actor.as_peer(peer_id="peer123", trust_relationship=trust_data)
peer_view.properties["shared_data"] = value  # Permission checks enforced
```

**3. Client Mode** (OAuth2/MCP client access):
```python
client_view = actor.as_client(client_id="mcp_client", trust_relationship=trust_data)
client_view.properties["user_data"] = value  # Permission checks enforced
```

**Handler Helper Method:**
```python
# In handler code
auth_view = self._get_authenticated_view(actor, auth_result)
if auth_view:
    # All operations now enforce permissions
    data = auth_view.properties.get("config")
```

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

### Version Bumping

When releasing a new version, update the version string in **three files**:

1. `pyproject.toml` - `version = "X.Y.Z"`
2. `actingweb/__init__.py` - `__version__ = "X.Y.Z"`
3. `CHANGELOG.rst` - Add new version entry at the top

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

### Testing

The project has two types of tests:
- **Unit tests** (`tests/test_*.py`): Run without external dependencies
- **Integration tests** (`tests/integration/`): Require DynamoDB (local or Docker)

#### Running Unit Tests

Unit tests that don't require DynamoDB can be run directly:

```bash
# Run all unit tests (excludes integration tests)
poetry run pytest tests/ -v --ignore=tests/integration

# Run specific test files
poetry run pytest tests/test_actor.py tests/test_config.py -v
```

#### Parallel Test Execution (Recommended)

For significantly faster test runs, use parallel execution with `pytest-xdist`:

```bash
# Run integration tests in parallel (3-4x faster)
make test-parallel

# Run all tests in parallel
make test-all-parallel

# Manual control over worker count
poetry run pytest tests/integration/ -n 4 -v --dist loadscope
```

Parallel testing features:
- Automatic worker isolation (unique DB tables, ports, actor emails)
- Test classes stay together on same worker (`--dist loadscope`)
- 3-4x speedup on multi-core systems
- No test code changes needed
- See `CONTRIBUTING.rst` for detailed documentation

#### Running Integration Tests with DynamoDB

Integration tests require a local DynamoDB instance. The project uses Docker Compose to manage this.

**Prerequisites:**
- Docker and Docker Compose installed
- Port 8001 available for DynamoDB

**Option 1: Use Makefile (recommended)**

```bash
# Run all integration tests (starts/stops DynamoDB automatically)
make test-integration

# Run integration tests excluding slow tests
make test-integration-fast
```

**Option 2: Manual Docker Management**

```bash
# Start DynamoDB in background
docker-compose -f docker-compose.test.yml up -d

# Wait a few seconds for DynamoDB to be ready
sleep 2

# Run integration tests
poetry run pytest tests/integration/ -v --tb=short

# Stop DynamoDB when done
docker-compose -f docker-compose.test.yml down -v
```

**Option 3: Keep DynamoDB Running**

For faster iteration during development:

```bash
# Start DynamoDB (keep running)
docker-compose -f docker-compose.test.yml up -d

# Run tests multiple times without restart
poetry run pytest tests/integration/ -v

# When completely done, stop DynamoDB
docker-compose -f docker-compose.test.yml down -v
```

#### Integration Test Fixtures

The integration tests use pytest fixtures defined in `tests/integration/conftest.py`:

- **`docker_services`**: Starts DynamoDB via Docker Compose (session-scoped)
- **`test_app`**: Starts a FastAPI test server on port 5555 (session-scoped)
- **`peer_app`**: Starts a second test server on port 5556 for peer testing (session-scoped)
- **`www_test_app`**: Test server without OAuth for www template testing on port 5557
- **`actor_factory`**: Creates test actors with automatic cleanup
- **`http_client`**: HTTP client with base URL configured
- **`oauth2_client`**: Authenticated OAuth2 client for testing protected endpoints
- **`trust_helper`**: Helper for establishing trust relationships

**Example usage:**

```python
def test_actor_creation(actor_factory):
    actor = actor_factory.create("test@example.com")
    assert actor["id"] is not None
    # Actor is automatically cleaned up after test

def test_trust_relationship(actor_factory, trust_helper):
    actor1 = actor_factory.create("user1@example.com")
    actor2 = actor_factory.create("user2@example.com")
    trust = trust_helper.establish(actor1, actor2, "friend")
    assert trust["secret"] is not None
```

#### Environment Variables for Testing

The integration tests configure these automatically, but for manual testing:

```bash
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DB_HOST=http://localhost:8001
export AWS_DB_PREFIX=test
```

#### Running All Tests

```bash
# Run everything (requires DynamoDB)
make test-integration

# Or manually:
docker-compose -f docker-compose.test.yml up -d
sleep 2
poetry run pytest tests/ -v --tb=short
docker-compose -f docker-compose.test.yml down -v
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

## Async AwProxy Methods

`AwProxy` provides async versions of resource methods using `httpx` for non-blocking operations in FastAPI routes:

- `get_resource_async()`, `create_resource_async()`, `change_resource_async()`, `delete_resource_async()`

```python
# In a FastAPI route - use async AwProxy for non-blocking HTTP to peers
from actingweb.aw_proxy import AwProxy

proxy = AwProxy(peer_target={"id": actor_id, "peerid": peerid}, config=config)
result = await proxy.get_resource_async(path="trust/friend/permissions")
```

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