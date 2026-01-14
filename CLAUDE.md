# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Project Overview

**ActingWeb** is a Python library implementing the ActingWeb REST protocol for distributed micro-services. Each user gets their own "actor" instance with a unique URL, enabling secure bot-to-bot communication and granular data sharing.

## Quick Reference

### Essential Commands

```bash
# Development
poetry install                    # Install dependencies
poetry shell                      # Activate virtual environment

# Quality Checks (run before committing)
poetry run pyright actingweb tests   # Type checking - must be 0 errors
poetry run ruff check actingweb tests # Linting - must pass
poetry run ruff format actingweb tests # Auto-format

# Testing (Sequential)
make test-integration             # Integration tests only (sequential, ~5 min)
make test-integration-fast        # Skip slow tests (sequential, ~3 min)
poetry run pytest tests/ -v       # All tests (requires DynamoDB running)

# Testing (Parallel) - FASTER but may have isolation issues
make test-parallel                # Integration tests (parallel, ~2 min)
make test-parallel-fast           # Skip slow tests (parallel, ~1 min)
make test-all-parallel            # ALL tests inc. unit tests (parallel, ~4 min)

# Final Validation Before Committing
make test-all-parallel            # Run ALL tests (unit + integration)

# Build
poetry build                      # Build package
```

### Version Bumping

Update version in **three files**:
1. `pyproject.toml` - `version = "X.Y.Z"`
2. `actingweb/__init__.py` - `__version__ = "X.Y.Z"`
3. `CHANGELOG.rst` - Add new version entry

## Documentation

Comprehensive documentation is in `docs/`. Key references:

| Topic | Location |
|-------|----------|
| **Getting Started** | `docs/quickstart/` |
| **Configuration** | `docs/quickstart/configuration.rst` |
| **Authentication & OAuth2** | `docs/guides/authentication.rst`, `docs/guides/spa-authentication.rst` |
| **Routing & Redirects** | `docs/reference/routing-overview.rst` |
| **Web UI & SPA Mode** | `docs/guides/web-ui.rst` |
| **Hooks Reference** | `docs/reference/hooks-reference.rst` |
| **API Reference** | `docs/reference/` |
| **SDK & Developer API** | `docs/sdk/` |
| **Testing Guide** | `CONTRIBUTING.rst`, `docs/contributing/testing.rst` |

## Architecture Overview

```text
actingweb/
├── interface/           # Modern fluent API (ActingWebApp, ActorInterface)
│   ├── app.py          # ActingWebApp - main configuration entry point
│   ├── actor_interface.py  # ActorInterface - actor operations
│   ├── hook_registry.py    # Decorator-based event handling
│   └── integrations/   # Flask & FastAPI integrations
├── handlers/           # HTTP request handlers
├── db/                 # Database backends (pluggable)
│   ├── dynamodb/      # DynamoDB backend (PynamoDB models)
│   ├── postgresql/    # PostgreSQL backend (psycopg3 + Alembic)
│   └── protocols.py   # Database interface protocols
├── actor.py           # Core actor implementation
├── config.py          # Configuration management
├── oauth2.py          # OAuth2 authentication
└── auth.py            # Authentication logic
```

**Key Concepts:**
- **Actor**: User instance with unique URL (`/{actor_id}`)
- **Properties**: Key-value storage per actor
- **Trust**: Relationships between actors with permissions
- **Subscriptions**: Event notifications between actors
- **Hooks**: Application callbacks for lifecycle events

See `docs/sdk/handler-architecture.rst` for detailed architecture.

## Database Backends

ActingWeb supports two database backends:

### DynamoDB (Default)
- **Production-ready**: AWS-managed NoSQL database
- **Auto-scaling**: Automatic read/write capacity management
- **Requirements**: DynamoDB Local for testing (`docker compose -f docker-compose.test.yml up dynamodb-test`)
- **Installation**: No extra dependencies needed

### PostgreSQL
- **Production-ready**: Open-source relational database
- **Schema management**: Alembic migrations
- **Requirements**: PostgreSQL 12+ server
- **Installation**: `poetry install --extras postgresql`

### PostgreSQL Setup

**Installation**:
```bash
poetry install --extras postgresql
```

**Environment Configuration**:
```bash
DATABASE_BACKEND=postgresql    # Select PostgreSQL backend
PG_DB_HOST=localhost          # Database host
PG_DB_PORT=5432               # Database port (5433 for test)
PG_DB_NAME=actingweb          # Database name
PG_DB_USER=actingweb          # Database user
PG_DB_PASSWORD=yourpassword   # Database password
PG_DB_PREFIX=                 # Optional: prefix for schema names (used in tests)
PG_DB_SCHEMA=public           # Schema name (default: public)
```

**Run Migrations**:
```bash
cd actingweb/db/postgresql/migrations
alembic upgrade head
```

**Testing with PostgreSQL**:
```bash
# Start PostgreSQL test container
docker compose -f docker-compose.test.yml up postgres-test -d

# Run tests with PostgreSQL backend
DATABASE_BACKEND=postgresql \
PG_DB_HOST=localhost \
PG_DB_PORT=5433 \
PG_DB_NAME=actingweb_test \
PG_DB_USER=actingweb \
PG_DB_PASSWORD=testpassword \
make test-integration

# Stop container when done
docker compose -f docker-compose.test.yml down
```

**Migration Management**:
```bash
cd actingweb/db/postgresql/migrations

# Create a new migration
alembic revision --autogenerate -m "Description of changes"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# Show current migration version
alembic current
```

## Critical Configuration

```python
from actingweb.interface import ActingWebApp

app = (
    ActingWebApp(
        aw_type="urn:actingweb:example.com:myapp",
        database="dynamodb",    # or "postgresql" - can also use DATABASE_BACKEND env var
        fqdn="myapp.example.com",
        proto="https://"
    )
    .with_oauth(client_id="...", client_secret="...")
    .with_web_ui(enable=True)   # False for SPAs
    .with_devtest(enable=False) # MUST be False in production
    .with_mcp(enable=True)
)
```

**Database Backend Selection**:
- Set `database="postgresql"` in ActingWebApp, OR
- Set `DATABASE_BACKEND=postgresql` environment variable (takes precedence)
- Default is `"dynamodb"` if not specified

See `docs/quickstart/configuration.rst` for all options.

## Browser Redirect Behavior

The `with_web_ui()` setting controls browser redirects:

| Scenario | `with_web_ui()` | Redirect |
|----------|-----------------|----------|
| Unauthenticated browser → `/<actor_id>` | Any | `/login` |
| Authenticated browser → `/<actor_id>` | `True` | `/<actor_id>/www` |
| Authenticated browser → `/<actor_id>` | `False` | `/<actor_id>/app` |
| After OAuth login | `True` | `/<actor_id>/www` |
| After OAuth login | `False` | `/<actor_id>/app` |

API clients always receive JSON. See `docs/reference/routing-overview.rst`.

## Property Reverse Lookup

ActingWeb supports reverse lookups (find actor by property value) via lookup tables:

```python
app.with_indexed_properties(["oauthId", "email", "externalUserId"])
app.with_legacy_property_index(enable=False)  # Recommended for new deployments
```

**Key Points:**
- **Default**: Lookup table mode disabled (`USE_PROPERTY_LOOKUP_TABLE=false`) for backward compatibility
- **Legacy mode**: Uses DynamoDB GSI (2048-byte limit) or PostgreSQL index
- **Lookup table mode**: No size limits, better performance for indexed properties
- **Migration**: Dual-mode support for gradual transition
- **Cleanup**: Automatic when properties/actors deleted

**Environment Variables:**
```bash
export USE_PROPERTY_LOOKUP_TABLE=true                    # Enable lookup tables
export INDEXED_PROPERTIES=oauthId,email,externalUserId  # Configure indexed properties
```

See `docs/quickstart/configuration.rst` for full migration guide and best practices.

## Quality Standards

**Zero-tolerance policy**: All code must pass with 0 errors, 0 warnings.

- **Type hints required** on all functions
- **Pyright** for type checking (primary)
- **Ruff** for linting and formatting
- **Tests**: 900+ tests, 100% passing required

## Testing

**Before committing**: Always run `make test-all-parallel` (all 900+ tests)

**Test Modes**:
- **Parallel** (recommended for development): `make test-all-parallel` (~4 min)
- **Sequential** (recommended for CI): `make test-integration` (~5 min)

Parallel tests are 2-3x faster but may have occasional isolation issues. If parallel tests fail, re-run sequentially to verify.

**Full testing guide**: See `docs/contributing/testing.rst` for:
- Test execution modes and tradeoffs
- Test isolation troubleshooting
- Running specific tests
- Known parallel execution issues

## Project Documentation System

The `thoughts/shared/` directory tracks development work:

```text
thoughts/shared/
├── research/    # Architecture analysis and design investigations
├── patterns/    # Reusable patterns and best practices
├── plans/       # Implementation plans (YYYY-MM-DD-*.md)
└── completed/   # Completed work documentation
```

Check these before starting significant work to find existing patterns and context.

## Logging

ActingWeb uses hierarchical logging with named loggers (`__name__`).

**Quick setup**:
```python
from actingweb.logging_config import configure_actingweb_logging
import logging

configure_actingweb_logging(logging.DEBUG)  # Development
configure_actingweb_logging(logging.WARNING, db_level=logging.ERROR)  # Production
```

**Convenience functions**: `configure_production_logging()`, `configure_development_logging()`, `configure_testing_logging()`

**Performance-critical loggers** (use WARNING+ in production):
- `actingweb.db.dynamodb`, `actingweb.auth`, `actingweb.handlers.properties`, `actingweb.aw_proxy`

**See also**: `actingweb/logging_config.py` module docstrings for detailed configuration options.

## Security Notes

- `with_devtest(enable=False)` - **MUST** be False in production
- Use HTTPS in production (`proto="https://"`)
- Never commit secrets - use environment variables
- See `docs/reference/security.rst` for full checklist
