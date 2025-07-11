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
python setup.py sdist bdist_wheel --universal

# Upload to test server
twine upload --repository pypitest dist/actingweb-a.b.c.*

# Upload to production
twine upload dist/actingweb-a.b.c.*
```

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