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

# Testing
make test-integration             # Run all tests (starts DynamoDB automatically)
poetry run pytest tests/ -v       # Run tests (requires DynamoDB running)

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
├── db_dynamodb/        # DynamoDB backend (PynamoDB models)
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

## Critical Configuration

```python
from actingweb.interface import ActingWebApp

app = (
    ActingWebApp(
        aw_type="urn:actingweb:example.com:myapp",
        database="dynamodb",
        fqdn="myapp.example.com",
        proto="https://"
    )
    .with_oauth(client_id="...", client_secret="...")
    .with_web_ui(enable=True)   # False for SPAs
    .with_devtest(enable=False) # MUST be False in production
    .with_mcp(enable=True)
)
```

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

## Quality Standards

**Zero-tolerance policy**: All code must pass with 0 errors, 0 warnings.

- **Type hints required** on all functions
- **Pyright** for type checking (primary)
- **Ruff** for linting and formatting
- **Tests**: 474+ tests, 100% passing required

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

## Security Notes

- `with_devtest(enable=False)` - **MUST** be False in production
- Use HTTPS in production (`proto="https://"`)
- Never commit secrets - use environment variables
- See `docs/reference/security.rst` for full checklist
