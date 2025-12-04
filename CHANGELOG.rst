=========
CHANGELOG
=========

v3.5.6: Dec 4, 2025
-------------------

FIXED
~~~~~

- **SECURITY**: Fixed token revocation searching wrong actor bucket during trust deletion - tokens were stored in user's actor but revocation looked in system actor (``_actingweb_oauth2``), leaving tokens valid after trust deletion

v3.5.5: Dec 3, 2025
-------------------

FIXED
~~~~~

- Fixed Flask and FastAPI integrations not propagating handler headers (e.g., WWW-Authenticate) to OAuth2 endpoint responses

v3.5.4: Dec 3, 2025
-------------------

FIXED
~~~~~

- **SECURITY**: Trust relationship deletion now properly deletes the associated OAuth2 client and revokes all tokens - prevents deleted MCP clients from being reused after trust relationship is removed

v3.5.3: Dec 3, 2025
-------------------

FIXED
~~~~~

- **SECURITY**: MCP client deletion now immediately revokes all access and refresh tokens - prevents deleted clients from continuing to access resources using cached tokens

v3.5.2: Dec 3, 2025
-------------------

FIXED
~~~~~

- **SECURITY**: Fixed missing WWW-Authenticate header for 401 responses in OAuth2 token endpoint - RFC 6749 Section 5.2 requires WWW-Authenticate header for invalid_client errors

v3.5.1: Dec 1, 2025
-------------------

FIXED
~~~~~

- **CRITICAL**: Fixed OAuth2 actor creation not triggering lifecycle hooks - ``config._hooks`` was never set, causing ``actor_created`` and other lifecycle hooks to be silently ignored during OAuth-based actor creation
- Added comprehensive regression tests for OAuth2 lifecycle hook integration

CHANGED
~~~~~~~

- ActingWebApp now automatically attaches HookRegistry to Config object's ``_hooks`` attribute in ``get_config()``

v3.5: Nov 30, 2025
------------------

**ActingWeb Specification version 1.2**

This release implements ActingWeb Specification version 1.2 with SPA-friendly API behavior.

FIXED
~~~~~

- **SECURITY**: Fixed SPA PKCE code challenge not being sent to OAuth providers - PKCE parameters are now properly forwarded to authorization URLs
- **SECURITY**: Fixed trust-based permissions bypass - handlers were using ``getattr()`` on dict instead of ``.get()`` for peer ID lookup, causing permission evaluator to be bypassed
- Fixed FastAPI cookie setting using ``key`` parameter instead of ``name`` (FastAPI/Starlette API difference)
- Fixed SPA refresh token cookie not being stored by browser (changed ``path="/"`` and ``samesite="Lax"``)
- Fixed refresh token reuse false positives on rapid page refresh with 2-second grace period
- Fixed ``oauth_state.decode_state()`` to handle JSON null values for optional trust_type field
- Removed sensitive token values from debug log messages (security improvement)
- Fixed pytest marker registration for integration tests (added ``integration`` marker)

CHANGED
~~~~~~~

- SPA OAuth2 authorize endpoint only includes ``trust_type`` in state when provided (distinguishes user login from MCP client auth)

BREAKING CHANGES
~~~~~~~~~~~~~~~~

**Empty Collection Response Behavior (Spec v1.2)**

The following endpoints now return ``200 OK`` with empty arrays/objects instead of ``404 Not Found``
when collections are empty. This is a **breaking change** for clients that rely on ``404`` to detect
empty collections:

- ``GET /trust`` - Returns ``200 OK`` with ``[]`` when no trust relationships exist (was ``404``)
- ``GET /trust?relationship=<type>`` - Returns ``200 OK`` with ``[]`` when no matches (was ``404``)
- ``GET /properties`` - Returns ``200 OK`` with ``{}`` when no properties exist (was ``404``)
- ``GET /subscriptions`` - Returns ``200 OK`` with ``{"id": ..., "data": []}`` when no subscriptions (was ``404``)

**Migration Guide:**

Before (v1.1):

.. code-block:: python

    response = requests.get(f"{actor_url}/trust", auth=auth)
    if response.status_code == 404:
        trusts = []  # No trusts
    else:
        trusts = response.json()

After (v1.2):

.. code-block:: python

    response = requests.get(f"{actor_url}/trust", auth=auth)
    trusts = response.json()  # Always returns array (may be empty)

**Note:** Individual resource lookups still return ``404 Not Found`` when the specific resource
does not exist (e.g., ``GET /properties/nonexistent``, ``GET /trust/friend/nonexistent-peer``).

DOCS
~~~~

- **Spec v1.2**: Added "Response Conventions" section documenting SPA-friendly empty collection behavior
- **Spec v1.2**: Updated ``/properties``, ``/trust``, and list properties sections with new 200 OK behavior
- Added ``listproperties`` option tag to ActingWeb specification for list property support
- Added comprehensive List Properties section to ``docs/actingweb-spec.rst`` documenting ordered collections
- Documented list property CRUD operations (GET/POST/PUT/DELETE) for items and full lists
- Documented list property metadata endpoint (GET/PUT ``/properties/{name}/metadata``)
- Updated GET ``/properties?metadata=true`` documentation to reference listproperties option tag

ADDED
~~~~~

- SPA mode support in OAuth2 callback handler (``spa_mode=true`` in state parameter returns JSON instead of redirect)
- JSON API responses in email verification handler (based on ``Accept: application/json`` header)
- ``GET /{actor_id}/meta/trusttypes`` endpoint for trust type enumeration
- ``GET/PUT /{actor_id}/properties/{name}/metadata`` endpoint for list property metadata
- Factory JSON API: ``GET /?format=json`` or ``Accept: application/json`` returns OAuth configuration for SPAs
- New test suites for SPA API endpoints (``tests/test_spa_api_endpoints.py``, ``tests/integration/test_spa_api.py``)

CHANGED
~~~~~~~

**Trust Type Configuration Clarification**

Trust types are now correctly scoped to MCP client authorization flows only:

- Trust types are **no longer** exposed in user login endpoints (``GET /?format=json``, ``/oauth/spa/*``)
- Library no longer hardcodes default trust types (e.g., ``mcp_client``)
- Applications must configure trust types for MCP OAuth2 flows via ``AccessControlConfig.configure_oauth2_trust_types()``
- ``/oauth/authorize`` (MCP authorization) shows trust types from registry; ``/oauth/spa/authorize`` (user login) does not

This change clarifies the distinction between:

1. **User Login** (ActingWeb as OAuth client to Google/GitHub): No trust relationship created, no trust_type needed
2. **MCP Authorization** (ActingWeb as OAuth server for MCP clients): Trust relationship created with specified trust_type

**Security Enhancement**

- Added explicit validation in OAuth2 callback to prevent actor spoofing (validates OAuth email matches actor creator)
- MCP OAuth2 flows derive actor_id from authenticated email, not user input

FIXED
~~~~~

- Fixed unit test configuration to use correct DynamoDB port (8001) matching docker-compose.test.yml
- Fixed Trust class attribute initialization to prevent AttributeError on early returns

v3.4.3: Nov 23, 2025
-------------------

FIXED
~~~~~

- Fixed MCP authentication to include error="invalid_token" in WWW-Authenticate header per RFC 6750 to force OAuth2 clients to invalidate cached tokens
- Fixed Flask and FastAPI integrations to properly propagate HTTP 401 status codes and WWW-Authenticate headers from MCP handler
- Reduced excessive debug logging in MCP trust relationship lookup
- Added conditional update check to prevent unnecessary trust relationship updates when client info hasn't changed

v3.4.2: Nov 22, 2025
-------------------

ADDED
~~~~~

- Github action to push new package to pypi on merging PRs to master branch

FIXED
~~~~~

- Fixed wrong URL in OAUTH2 discovery URL that prevented detection of dynamic client registration

CHANGED
~~~~~~~

- Reduced unnecessary error logging for access and authentication
- Ruff linting and formatting and pyright type fixes

v3.4.1: Nov 8, 2025
-------------------

FIXED
~~~~~

**MCP Tool Annotations**

- Fixed tool annotations not being serialized in ``tools/list`` responses in MCP handler
- Tool annotations (``readOnlyHint``, ``destructiveHint``, ``idempotentHint``, ``openWorldHint``) are now properly included when decorators define them
- This fix enables ChatGPT and other MCP clients to properly evaluate tool safety before execution
- Aligns FastAPI/HTTP integration path with SDK server behavior

**OAuth2 Trust Type Selection**

- Fixed OAuth2 authorization form ignoring user-selected trust type during Google/GitHub authentication
- OAuth provider buttons now submit form to ``/oauth/authorize`` POST with selected trust_type before redirecting to provider
- Trust type is properly embedded in encrypted OAuth state and applied during callback
- Fixes regression introduced when OAuth provider integration was added (previously worked with email form submission)

v3.4: Oct 26, 2025
-------------------

ADDED
~~~~~

**OAuth2 Security Enhancements**

- Added email verification system for OAuth2 actors when provider cannot verify email ownership
- Added cross-actor authorization prevention in MCP OAuth2 flows (blocks attackers from authorizing access to other users' actors)
- Added session fixation prevention in web OAuth2 login flows
- Added comprehensive security documentation in ``docs/authentication-system.rst``
- Added security tests in ``tests/integration/test_oauth2_security.py``
- Added lifecycle hooks: ``email_verification_required`` and ``email_verified``
- Added email verification endpoint: ``/<actor_id>/www/verify_email``
- Added verified emails dropdown for GitHub OAuth2 (fetches verified emails via GitHub API)
- Added provider ID support (stable identifiers like ``google:sub`` or ``github:user_id``) as alternative to email addresses
- Added 32-byte cryptographic verification tokens with 24-hour expiry
- Added security logging for all authorization violations

**Trust Relationship Enhancements**

- Added ``last_accessed`` and ``last_connected_via`` fields to trust relationships for tracking connection activity
- Handler now updates trust relationship timestamps on each connection with client metadata refresh
- Trust relationship sorting by most recent connection in web UI (``/www/trust``)

FIXED
~~~~~

**Security Fixes**

- **CRITICAL**: Fixed OAuth2 callback to validate actor ownership before completing authorization (prevents cross-actor authorization attacks in MCP flows)
- Fixed potential account hijacking vulnerability when OAuth2 providers don't return verified email addresses
- Fixed session fixation vulnerability where attackers could trick users into logging into attacker's actor

**OAuth2 and Integration Fixes**

- Fixed OAuth2 CORS preflight (OPTIONS) requests not being routed correctly in FastAPI integration, causing 404 errors on ``/oauth/register`` and ``/oauth/token`` endpoints

CHANGED
~~~~~~~

**Code Quality & Type Safety**

- **Type Checking**: Achieved zero pyright errors and warnings across entire codebase (down from 430+ issues)
- **Linting**: Achieved zero ruff errors (fixed all 15 remaining linting issues)
- **Configuration**: Added pyright to dev dependencies and created ``pyrightconfig.json`` for consistent type checking
- **VSCode Integration**: Updated ``.vscode/settings.json`` for optimal pylance and ruff integration
- **Test Improvements**: Fixed pytest fixture names causing test failures, all 474 tests now passing
- **Type Annotations**: Added comprehensive type ignore comments for test files (228+ annotations)
- **Import Management**: Fixed unused imports, variables, and function warnings throughout codebase
- **Module Declarations**: Fixed lazy-loaded module ``__all__`` declarations with proper pyright ignores (34 modules)

- **Dependencies**: Updated Poetry to 2.2.1 and major package upgrades including ``cryptography`` 45.0.6 → 46.0.3, ``fastapi`` 0.116.1 → 0.120.0, ``mcp`` 1.12.4 → 1.19.0, ``pydantic`` 2.11.7 → 2.12.3, ``pytest-cov`` 6.2.1 → 7.0.0, ``ruff`` 0.12.8 → 0.14.2, and 30+ other dependency updates


v3.3: Oct 4, 2025
-----------------

BREAKING CHANGES
~~~~~~~~~~~~~~~~

**Legacy OAuth System Removed**

- Removed legacy ``OAuth`` class and related third-party service authentication
- Removed ``/<actor_id>/oauth`` endpoints that used legacy OAuth
- Removed legacy OAuth methods from ``Auth`` class (``oauth_get``, ``oauth_post``, etc.)
- Legacy OAuth auth type no longer supported in ``select_auth_type()``

**Migration Path**: Use the new unified third-party service integration system instead:

- Replace ``oauth.OAuth()`` with ``actor.services.get("service_name")``
- Replace manual OAuth configuration with ``app.add_dropbox()``, ``app.add_gmail()``, etc.
- Use clean service API: ``service.get()``, ``service.post()``, etc.

FIXED
~~~~~

- MCP tools/list response now applies client-specific formatting for better compatibility
- Trust relationship descriptions now show friendly client names instead of raw identifiers when available
- OAuth2 client trust relationships maintain proper client metadata across updates
- Trust manager now keeps peer identifier in sync for OAuth2/MCP clients
- Fixed FastAPI extra inadvertently importing Flask, forcing Flask as a dependency
- Fixed trust handler to return empty list instead of 404 for graceful handling
- Reduced logging noise by moving non-essential INFO logs to DEBUG
- Made ``actor.get_config()`` use the dynamic global ``actingweb.__version__``
- Fixed error in ``DbPropertyList`` when properties table was missing in DynamoDB
- Fixed ``trustee_root`` JSON to return stored value instead of input parameter
- Fixed missing ``trustee_root`` in actor creation via REST API
- Fixed handling of ``POST`` to ``/<actor_id>/www/properties`` (including ``_method=DELETE``)
- Fixed base path handling for ``/<actor_id>/www`` (supports non-root base paths consistently)
- Fixed ``www/`` hook not triggered
- Devtest proxy: added Basic-auth fallback (``trustee:<peer passphrase>``) when Bearer trust requests to peer ``/properties`` endpoints receive 302/401/403, avoiding OAuth2 redirects during testing
- Fixed MCP OAuth2 trust relationship creation where MCP clients completed authentication but no trust relationships were created
- Fixed hook permission operation mapping where "get" operations were incorrectly passed as "read"
- Fixed OAuth2 callback ``established_via`` to properly distinguish between MCP and regular OAuth2 flows
- Fixed singleton initialization dependency order causing Permission Evaluator to fail when Trust Permission Store was not yet initialized
- Fixed OAuth2 trust-type filtering logic that was incorrectly placed inside exception handlers, causing 0 available trust types during OAuth2 flows
- Fixed severe OAuth2 performance issue where lazy singleton loading during requests caused 4+ minute hangs during OAuth2 callbacks
- Fixed ``established_via`` field being lost between database save and retrieval in trust relationship management
- Added explicit singleton initialization at application startup to prevent performance degradation during OAuth2 flows
- Replaced all urlfetch HTTP calls with requests library for improved reliability, better timeout handling, and elimination of 30+ second timeout issues

CHANGED
~~~~~~~

- If ``unique_creator=False``, ensure deterministic retrieval of the first actor available when doing OAuth2 auth and log in from root
- Refactored OAuth2 server implementation to use Attributes system instead of underscore-prefixed properties for storing sensitive data (tokens, authorization codes, Google OAuth2 tokens)
- Removed unused default resources in the MCP server (now only existing resources and hooks are presented)
- Removed notes and usage as static resource in the library, leave this to the implementing application
- Cleaned up the actor creation interfaces, ActorInterface.create() is now the only factory to be used.
- Standardized global Attribute buckets for cross-actor data.
- Enhanced ``/trust/{relationship}/{peerid}`` API endpoints to support permission management alongside traditional trust relationship operations
- Modified ``/meta/actingweb/supported`` to dynamically include feature tags based on available system capabilities
- Properties, methods, and actions handlers now integrate with unified permission system while maintaining backward compatibility
- Hook execution system now includes transparent permission checking with authentication context passing
- **Dependencies**: Replaced ``urlfetch ^2.0.1`` with ``requests ^2.31.0`` for more reliable HTTP operations

ADDED
~~~~~

**Integration Test Suite**

- Added comprehensive REST API integration test suite with 117 tests covering all mandatory ActingWeb protocol endpoints
- Added ``tests/integration/`` directory with test harness, fixtures, and test files
- Added Docker Compose configuration for local DynamoDB testing (``docker-compose.test.yml``)
- Added GitHub Actions CI/CD workflow (``.github/workflows/integration-tests.yml``) for automated testing on PRs
- Added ``make test-integration`` target for running integration tests locally
- Added comprehensive testing documentation (``docs/TESTING.md``)
- Test coverage: actor lifecycle, properties (nested/complex), meta, trust relationships, subscriptions with diffs

**MCP Client Management Enhancements**

- Support for ``allowed_clients`` parameter in ``@mcp_tool`` decorator to restrict tool access by client type
- Support for ``client_descriptions`` parameter in ``@mcp_tool`` decorator for client-specific tool descriptions
- Client-specific tool filtering for MCP endpoints based on client type detection (ChatGPT, Claude, Cursor, etc.)
- Enhanced OAuth2 client trust relationship display with friendly client names in web UI
- Automatic enrichment of OAuth2 trust relationships with missing client metadata

**Unified Third-Party Service Integration**

- Added modern service integration system replacing legacy OAuth class
- Added fluent API methods: ``app.add_dropbox()``, ``app.add_gmail()``, ``app.add_github()``, ``app.add_box()``
- Added ``ServiceConfig``, ``ServiceClient``, and ``ServiceRegistry`` classes
- Added automatic token management and refresh for third-party services
- Added ``actor.services.get()`` interface for accessing authenticated service clients
- Added service OAuth2 callback endpoints: ``/{actor_id}/services/{service_name}/callback``
- Added service revocation endpoints: ``DELETE /{actor_id}/services/{service_name}``
- Added comprehensive documentation in ``docs/service-integration.rst``
- Integrated service system with both Flask and FastAPI frameworks

**Bot Handler Improvements**

- Fixed broken bot handler that tried to use removed legacy OAuth system
- Simplified bot authentication to use direct bot token validation from config
- Removed dependency on Auth class for bot endpoints - bots now use simpler token-based validation
- Bot token now passed to hooks for service calls if needed

**Simplified Authentication Interface**

- Added ``require_authenticated_actor()`` method to BaseHandler for one-line auth + authorization
- Added ``authenticate_actor()`` method returning ``AuthResult`` for more granular control
- New interface reduces boilerplate from 6-8 lines to 2-3 lines per handler method
- Maintains full compatibility with existing ``init_actingweb()`` usage
- Automatic HTTP response handling for common authentication and authorization failures

**Unified Access Control System**

- Complete unified access control system with trust types, permissions, and pattern matching
- Trust Type Registry with 6 built-in trust types (associate, viewer, friend, partner, admin, mcp_client) and support for custom types
- Permission Evaluator with glob pattern matching, precedence rules, and fallback to legacy authorization
- Per-relationship permission storage system allowing individual trust relationships to override trust type defaults
- Permission Integration module providing transparent permission checking for all ActingWeb operations
- Enhanced Trust API with permission management endpoints:

  - ``GET /trust/{relationship}/{peerid}?permissions=true`` - Include permission overrides in trust response
  - ``PUT /trust/{relationship}/{peerid}`` - Update permissions alongside trust relationship properties
  - ``GET /trust/{relationship}/{peerid}/permissions`` - Dedicated permission management endpoint
  - ``PUT /trust/{relationship}/{peerid}/permissions`` - Create/update permission overrides
  - ``DELETE /trust/{relationship}/{peerid}/permissions`` - Remove permission overrides

- ``trustpermissions`` feature tag automatically included in ``/meta/actingweb/supported`` when permission system is available
- Transparent hook permission checking - existing hooks automatically get permission filtering without code changes
- Enhanced MCP OAuth2 trust relationship creation with automatic trust type detection
- Zero-migration design - existing applications work immediately while gaining new capabilities
- Comprehensive permission structure supporting properties, methods, actions, tools, resources, and prompts
- Pattern-based permissions with support for glob wildcards (``*``, ``?``) and URI schemes
- Backward compatibility with legacy authorization system as fallback

**Other Additions**

- Added execution of property_hooks in the handler of www/*
- Added support for list of hidden properties as variable to www/properties* templates
- Added support for dynamic generation of resources in MCP based on hooks
- Support for CORS in oauth2 flows
- PKCE support in oauth2 flows
- Support for OPTIONS method on OAUTH2 discovery endpoints
- New explicit interface for managing list properties with `actor.property_lists.listname` syntax
- Distributed list storage bypassing DynamoDB 400KB item limits by storing individual list items as separate properties
- Added `property_lists` attribute to Actor class for list-specific operations
- Lazy-loading iterator for efficient list traversal without loading entire lists into memory
- Added singleton warmup module (``actingweb.singleton_warmup``) for explicit initialization of performance-critical singletons at application startup
- Comprehensive documentation for singleton initialization requirements in both CLAUDE.md and unified-access-control.rst
- Intelligent caching system for MCP endpoint authentication providing 50x performance improvement (50ms → 1ms) for repeated requests with 90%+ cache hit rates
- MCP authentication caching includes token validation, actor loading, and trust relationship lookup with automatic TTL-based cleanup and performance monitoring

**OAuth2 Client Management**

- High-level ``OAuth2ClientManager`` interface for creating, listing, validating, deleting clients, and regenerating client secrets
- Client secret regeneration with verification, audit timestamp (``secret_regenerated_at``), and formatted display values
- Generate access tokens via client-credentials flow directly from ``OAuth2ClientManager.generate_access_token()``

**OAuth2 Authorization Server**

- Added support for ``client_credentials`` grant type with token issuance and discovery updated (``grant_types_supported``)
- Added ``trust_type`` and ``actor_id`` to client registration/discovery responses; improved secret validation diagnostics
- Added client deletion capability to MCP client registry

**MCP Integration**

- Captures and caches MCP ``clientInfo`` during initialize; persists to trust relationship after OAuth2 callback
- Populates trust context on authenticated MCP sessions for permission evaluation
- Added Google OAuth2 token validation via Google TokenInfo API
- Enhanced MCP client information capture and persistent storage across session establishment
- Improved MCP authentication with proper HTTP 401 handling and WWW-Authenticate headers for FastAPI integration
- Added global client info caching during session establishment with automatic cleanup
- Each MCP client now gets unique trust relationship per user email, preventing clients from overwriting each other's identities
- OAuth2 client registration now automatically creates trust relationships, ensuring proper permission evaluation
- All OAuth2 clients must pass permission evaluation before accessing MCP endpoints

**Runtime Context System**

- New ``actingweb.runtime_context`` module providing structured request context for hook functions
- ``RuntimeContext`` class with type-safe context classes: ``MCPContext``, ``OAuth2Context``, ``WebContext``
- ``get_client_info_from_context()`` helper function for unified client detection across all context types
- Support for custom context types via ``set_custom_context()`` and ``get_custom_context()`` methods
- Request-scoped context lifecycle with automatic cleanup support
- Comprehensive documentation and examples for using runtime context in hook functions

**Web UI Enhancements**

- Consistent template URL variables across pages: ``actor_root``, ``actor_www``, and ``url``
- Trust page displays registered OAuth2 clients (name, trust type, created time, status)
- Trust creation form supports selecting trust type; consistent ``form_action`` and redirects
- Property pages: create/delete list properties, edit list metadata (description/explanation), and improved redirects after operations

**Auth Utilities**

- Added ``check_and_verify_auth()`` helper to verify authentication for custom (non-ActingWeb) routes with redirect-aware responses

v3.2.1: Aug 9, 2025
-------------------

**OAuth2 Authentication System and Enhanced Integrations**

ADDED
~~~~~

- **OAuth2 Implementation**:
  - New oauth2.py module with comprehensive OAuth2 authentication using oauthlib WebApplicationClient
  - Support for Google and GitHub OAuth2 providers with automatic provider detection
  - OAuth2CallbackHandler for secure callback processing with state parameter validation
  - Email validation system to prevent identity confusion attacks
  - Login hint parameter support for Google OAuth2 to improve user experience
  - State parameter encryption with CSRF protection and email validation

- **MCP OAuth2 Authorization Server**:
  - Complete RFC 7591/RFC 8414 compliant OAuth2 authorization server for MCP (Model Context Protocol) clients
  - Dynamic Client Registration (DCR) endpoint for MCP client registration
  - OAuth2 authorization and token endpoints with proper scope handling
  - Separate token management system for ActingWeb tokens vs Google tokens
  - Per-actor MCP client credential storage using ActingWeb attribute bucket pattern
  - State parameter encryption with MCP context preservation for OAuth2 flows
  - Global index buckets for efficient MCP client lookup across actors
  - Integration with existing Google OAuth2 for user authentication proxying

- **Enhanced Authentication Flow**:
  - Modified factory endpoint behavior: GET shows email form, POST triggers OAuth2 with email hint
  - Email validation step to ensure authenticated email matches form input
  - User-friendly error templates for authentication failures
  - Security enhancement preventing form email != OAuth2 email mismatch attacks
  - Dual OAuth2 callback handling supporting both ActingWeb and MCP flows

- **FastAPI Integration Enhancements**:
  - Improved FastAPI integration with better async/await handling
  - Enhanced template and static file support for FastAPI applications
  - Better separation of GET/POST handling in factory routes
  - Improved error handling and response formatting for FastAPI

- **Integration Improvements**:
  - Enhanced both Flask and FastAPI integrations with OAuth2 callback handling
  - Improved factory route handling with separate GET/POST methods
  - Better template variable population for authentication forms
  - Enhanced error handling across both integrations

CHANGED
~~~~~~~

- **Authentication System**:
  - Factory routes now handle GET and POST separately for better UX
  - Enhanced OAuth callback processing with comprehensive validation
  - Improved state parameter handling with encryption and validation
  - Better error messaging and user guidance for authentication failures

- **Integration Layer**:
  - Updated both Flask and FastAPI integrations to support new OAuth2 flow
  - Enhanced template rendering with better context and error handling
  - Improved factory handler logic with cleaner separation of concerns
  - Better support for custom authentication flows in integrations

- **Dependency Management**:
  - Updated all dependencies to latest stable versions
  - Major version updates: Flask ^2.0.0 → ^3.1.1, Werkzeug ^2.0.0 → ^3.1.3
  - FastAPI ^0.100.0 → ^0.116.1, uvicorn ^0.23.1 → ^0.35.0
  - Core dependencies: boto3 ^1.26.0 → ^1.40.6, urlfetch ^1.0.2 → ^2.0.1, cryptography ^41.0.0 → ^45.0.6
  - Development tools: pytest ^7.0.0 → ^8.4.1, black ^22.0.0 → ^25.1.0, ruff ^0.1.0 → ^0.12.8
  - Documentation: sphinx ^5.0.0 → ^8.2.3, sphinx-rtd-theme ^1.0.0 → ^3.0.2
  - Restructured optional dependencies into independent extras: flask, fastapi, mcp, and all

FIXED
~~~~~

- **Type Safety**:
  - Fixed all pylance/mypy type annotation errors in OAuth2 implementation
  - Enhanced type safety for OAuth2 classes and methods
  - Better null safety checks in authentication flows
  - Improved Union type handling for request bodies

- **Authentication Issues**:
  - Fixed OAuth callback handling edge cases
  - Resolved state parameter validation issues
  - Fixed email validation logic for OAuth2 providers
  - Enhanced error handling in authentication flows

- **Handler Integration Issues**:
  - Fixed critical auth.py bug where handler objects were incorrectly treated as response objects
  - Resolved AttributeError: 'SubscriptionRootHandler' object has no attribute 'write'
  - Resolved AttributeError: 'SubscriptionRootHandler' object has no attribute 'headers'
  - Updated auth.init_actingweb() to properly access appreq.response.write() and appreq.response.headers
  - Added defensive checks for response object availability in authentication flows

- **DynamoDB Storage Issues**:
  - Fixed DynamoDB ValidationException for authorization codes exceeding 2KB index key size limit
  - Fixed DynamoDB ValidationException for access tokens exceeding size limits
  - Implemented individual property storage pattern for large data structures
  - Separated Google token data storage from index keys to prevent size limit violations
  - Added reference key pattern for efficient lookup of separated token data

SECURITY
~~~~~~~~

- **OAuth2 Security Enhancements**:
  - Implemented comprehensive email validation to prevent identity attacks
  - Added state parameter encryption for CSRF protection
  - Enhanced callback validation with multiple security checks
  - Improved error handling to prevent information leakage

- **MCP Authorization Server Security**:
  - RFC 7591 compliant Dynamic Client Registration with proper client credential generation
  - Per-actor client isolation using ActingWeb security boundary model
  - State parameter encryption with MCP context preservation prevents CSRF attacks
  - Secure token separation between ActingWeb internal tokens and Google OAuth2 tokens
  - Proper scope validation and authorization code flow implementation
  - Client credential storage encrypted at rest using ActingWeb property system

v3.1: Jul 28, 2025
--------------------

BREAKING CHANGES
~~~~~~~~~~~~~~~~

- Removed legacy OnAWBase interface completely
- Removed `actingweb.on_aw` module and `OnAWBase` class  
- Removed `ActingWebBridge` compatibility layer from interface module
- Handler constructors now accept `hooks: HookRegistry` instead of `on_aw: OnAWBase`
- Applications must now use the modern `ActingWebApp` interface exclusively

ADDED
~~~~~

- FastAPI integration with `app.integrate_fastapi()` method
- FastAPI integration automatically generates OpenAPI/Swagger documentation
- Synchronous ActingWeb handlers run in thread pools to prevent event loop blocking
- Pydantic models for all ActingWeb endpoints with automatic validation
- Support for modern `@app.actor_factory` decorator in FastAPI integration

CHANGED
~~~~~~~

- All handlers now use HookRegistry directly instead of OnAWBase bridge pattern
- Flask integration now uses HookRegistry directly
- Fixed hook method call signatures in properties.py, resources.py, and www.py
- Fixed path handling in property hooks to prevent index out of bounds errors
- Standardized hook parameter order across all handlers
- Fixed missing arguments in execute_property_hooks calls
- Resolved callback hook return type issues with any() function usage

v3.0.1: (Jul 17, 2025)
------------------------

BREAKING CHANGES
~~~~~~~~~~~~~~~~
- Minimum Python version is now 3.11+
- Removed deprecated Google App Engine (GAE) database implementation
- Removed migrate_2_5_0 migration flag and related migration code
- Database backend now only supports DynamoDB
- Removed Google App Engine urlfetch abstraction layer
- Environment types updated to remove APPENGINE, added AWS
- Separated application-level callbacks (@app.app_callback_hook) from actor-level callbacks (@app.callback_hook)

ADDED
~~~~~
- Comprehensive type hints using Python 3.11+ union syntax (str | None)
- Custom exception hierarchy: ActorError, ActorNotFoundError, InvalidActorDataError, PeerCommunicationError, TrustRelationshipError
- Constants module with AuthType, HttpMethod, TrustRelationship, ResponseCode enums
- Modern build system with pyproject.toml and Poetry for dependency management
- Modern developer interface with ActingWebApp class and fluent API
- Decorator-based hook system for property, callback, subscription, and lifecycle events
- ActorInterface, PropertyStore, TrustManager, and SubscriptionManager wrappers
- Flask integration with automatic route generation
- /methods endpoint support with JSON-RPC 2.0 protocol compatibility
- /actions endpoint support for trigger-based functionality
- Method hooks (@app.method_hook) and action hooks (@app.action_hook)
- Development tooling (black, ruff, mypy) and comprehensive test suite with pytest
- Type checking support with py.typed marker
- __version__ attribute to actingweb module

CHANGED
~~~~~~~
- Modernized string formatting with f-strings
- Simplified HTTP client code to use urlfetch library directly
- Removed config.env == "appengine" environment checks
- Updated default actor type from gae-demo to demo
- Enhanced type safety with comprehensive None-checking patterns
- Applied systematic None validation patterns to prevent runtime errors
- Improved IDE support with better type inference and error detection
- Complete documentation overhaul with modern interface examples

FIXED
~~~~~
- Eliminated potential bugs from dual interface inconsistencies
- Removed unnecessary abstraction layers improving request handling speed
- Single code path reduces potential for interface synchronization issues
- Better type checking with direct HookRegistry usage instead of generic OnAWBase
- Zero Pylance diagnostics errors across entire codebase
- Comprehensive None safety checks across all core modules
- Fixed handler method signatures for proper positional argument passing
- Enhanced HTTP request safety with proper urlfetch module validation
- Fixed OAuth configuration access with proper None checks
- Applied systematic None safety patterns across all HTTP methods
- Refactored actor creation to reduce coupling between factory handler and bridge implementation
- Fixed template variables not being populated for web form POST to /

QUALITY
~~~~~~~
- Legacy OnAWBase interface completely removed for better maintainability
- Applications using OnAWBase must migrate to ActingWebApp interface
- 95%+ reduction in complexity for handler logic
- Clean separation of concerns with direct hook execution
- Much simpler debugging without bridge layer abstraction
- All tests continue to pass with new interface (30/30)
- 90% reduction in boilerplate code for new applications
- Proper circular import handling with TYPE_CHECKING
- Enhanced developer experience with self-documenting type hints

MIGRATION GUIDE
~~~~~~~~~~~~~~~
**For existing applications using OnAWBase:**

**Before (Legacy - NO LONGER SUPPORTED)**::

    class MyApp(OnAWBase):
        def get_properties(self, path, data):
            return data

        def post_callbacks(self, name):
            return True

**After (Modern Interface - REQUIRED)**::

    app = ActingWebApp("my-app", "dynamodb", "myapp.com")

    @app.property_hook("*")
    def handle_properties(actor, operation, value, path):
        if operation == "get":
            return value
        return value

    @app.callback_hook("*")
    def handle_callbacks(actor, name, data):
        return {"status": "handled"}

**Handler instantiation changes:**
- **Before:** `Handler(webobj, config, on_aw=my_onaw_instance)`  
- **After:** `Handler(webobj, config, hooks=app.hooks)`

**Key Benefits of Migration:**
- 95% less boilerplate code
- Better type safety and IDE support  
- Easier testing and debugging
- Single source of truth for application logic
- No more dual interface maintenance

v2.6.5: Apr 22, 2021
--------------------
- Fix bug in subscription_diff handling by replacing query with scan as query requires hash key

v2.6.4: Apr 11, 2021
--------------------
- Messed up release versioning, bump up to avoid confusion

v2.6.3: Apr 11, 2021
--------------------
- Fix bug in peertrustee handling by replacing dynamodb count() with scan() as count requires a hash key

v2.6.2: Oct 20, 2020
--------------------
- Security fix on oauth refresh

v2.6.1: Aug 30, 2020
--------------------
- Fix token refresh to also use Basic authorisation

v2.6.0: Aug 23, 2020
--------------------
- Add support for optional Basic authorisation in token request (e.g. Fitbit is requiring this)

v2.5.1: Jan 29, 2019
--------------------
- Move some annoying info messages to debug in auth/oauth
- Fix bug in set_attr for store where struct is not initialised (attribute.py:70)
- Enforce lower case on creator if @ (i.e. email) in value

v2.5.0: Nov 17, 2018
--------------------
- BREAKING: /www/properties template_values now return a dict with { 'key': value} instead of list of { 'name': 'key',
  'value': value}
- Add support for scope GET parameter in callback from OAUTH2 provider (useful for e.g. Google)
- Add support for oauth_extras dict in oauth config to set additional oauth paramters forwarded to OAUTH2 provider
  (Google uses this)
- Add support for dynamic:creator in oauth_extras to preset login hint etc when forwarding to OAuth2 auth endpoints
  (if creator==email, this allows you to send Google hint on which account to use with 'login_hint': 'dynamic:creator'
  in oauth_extras in config
- Add support for actor get_from_creator() to initialise an actor from a creator (only usable together with config
  variable unique_creator)
- Add support for get_properties(), delete_properties(), put_properties(), and post_properties in the on_aw() class.
  These allows on_aw overriding functions to process any old and new properties and return the resulting properties
  to be stored, deleted, or returned
- Move all internal (oauth_token, oauth_token_expiry, oauth_refresh_token, oauth_token_refresh_token_expiry,
  cookie_redirect, and trustee_root) data from properties (where they are exposed on GET /<actor_id>/properties) to internal
  variable store (attributes). Introduce config variable migrate_2_5_0 (default True) that will look for properties
  with oauth variable names if not found in internal store and move them over to internal store (should be turned
  off when all actors have migrated their oauth properties over to store)
- Add new interface InternalStore() (attribute.py) for storing and retrieving internal variables on an actor (i.e.
  attributes). All actors now have .store that can be used either as a dict or dot-notation. actor.store.var = 'this'
  or actor.store['var'] = 'this'. Set the variable to None to delete it. All variables are immediately stored to the
  database. Note that variable values must be json serializable
- Add new interface PropertyStore() (property.py) for storing and retrieving properties. Used just like InternalStore()
  and access through actor.property.my_var or actor.property['my_var']
- InternalStore(actor_id=None, config=None, bucket=None) can be used independently and the optional bucket parameter
  allows you to create an internal store that stores a set of variables in a specific bucket. A bucket is retrieved
  all at once and variables are written to database immediately
- Fix issue where downstream (trusts) server processing errors resulted in 405 instead of 500 error code
- Fix bug in oauth.put_request() where post was used instead of put
- Fix issue where 200 had Forbidden text

v2.4.3: Sep 27, 2018
--------------------
- Don't do relative import with import_module, AWS Lambda gets a hiccup

v2.4.2: Sep 27, 2018
--------------------
- Get rid of future requirement, just a pain

v2.4.1: Sep 26, 2018
--------------------
- Fix bad relative imports
- Use extras_require for future (python2 support)

v2.4.0: Sep 22 2018
--------------------
- Support python3

v2.3.0: Dec 27, 2017
--------------------
- Entire API for handlers and Actor() as well as other objects changed to be PEP8 compliant
- Add support for head_request(() in oauth and oauth_head() in auth
- Change all uses of now() to utcnow()
- db_gae for Google AppEngine is not kept updated, so folder deprecated and just kept for later reference
- Full linting/PEP8 review
- Add support for actor_id (set id) on Actor.create()

v2.2.2: Dec 3, 2017
-------------------
- Fix bug in region for properties and attributes resulting in using us-east-1 for these (and not us-west-1 as default)

v2.2.1: Dec 3, 2017
-------------------
- Add support for environment variable AWS_DB_PREFIX to support multiple actingweb tables in same DynamoDB region

v2.2.0: Nov 25, 2017
--------------------
- Add support for attribute.Attributes() and attribute.Buckets() (to be used for internal properties not exposed)
- Various bug fixes to make the oauth flows work

v2.1.2: Nov 12, 2017
--------------------
- Split out actingweb module as a separate pypi library and repository
- Python2 support, not python3
- Support AWS DynamoDB and Google Datastore in sub-modules
- Refactor out a set of handlers to allow easy integration into any web framework
- actingwebdemo as a full-functioning demo app to show how the library is used

Jul 9, 2017
--------------------
- Fix bug with unique actor setting and actor already exists
- Improve handling of enforce use of email property as creator
- Fix auth bug for callbacks (401 when no auth is expected)
- Add support for "lazy refresh" of oauth token, i.e. refresh if expired or refresh token has <24h to expiry
- Add support for Actors() class in actor.py to get a list of all actors with id and creator (ONLY for admin usage)
- Fix various bugs when subscriptions don't exist
- Improve logging when actor cannot be created

Apr 2, 2017
--------------------
- Changed license to BSD after approval from Cisco Systems
- Fix bug in deletion of trust relationship that would not delete subscription
- Add support for GET param ?refresh=true for web-based sessions to ignore set cookie and do oauth
- Fix bug in oauth.oauth_delete() returning success when >299 is returned from upstream

Mar 11, 2017
--------------------
- Fix bug in aw_actor_callbacks.py on does exist test after db refactoring
- Fix bug in handling of www/init form to set properties
- Add support to enforce that creator (in actor) is unique (Config.unique_creator bool)
- Add support to enforce that a creator field set to "creator" is overwritten if property "email" is set 
  (Config.force_email_prop_as_creator bool, default True). Note that username for basic login then changes from
  creator to the value of email property. 
  This functionality can be useful if actor is created by trustee and email is set later
- Add new DbActor.py function get_by_creator() to allow retrieving an actor based on the creator value


Feb 25, 2016
--------------------
- Major refactoring of all database code
- All db entities are now accessible only from the actingweb/* libraries
- Each entity can be accessed one by one (e.g. trust.py exposes trust class) and as a list (e.g. trust.py exposes trusts class)
- actor_id and any parameters that identify the entity must be set when the class is instantiated
- get() must be called on the object to retrieve it from the database and the object
  is returned as a dictionary
- Subsequent calls to get() will return the dictionary without database access, but
  any changes will be synced to database immediately
- The actingweb/* libraries do not contain any database-specific code, but imports
  a db library that exposes the barebone db operations per object
- The google datastore code can be found in actingweb/db_gae
- Each database entity has its own .py file exposing get(), modify(), create(), delete()
  and some additional search/utility functions where needed
- These db classes do not do anything at init, and get() and create() must include all parameters
- The database handles are kept in the object, so modify() and delete() require a get() or create()
  before they can be called
- Currently, Google Datastore is the only supported db backend, but the db_* code can now fairly
  easily be adapted to new databases

Nov 19, 2016
--------------------
- Create a better README in rst
- Add readthedocs.org support with conf.py and index.rst files
- Add the actingweb spec as an rst file
- Add a getting-started rst file
- Correct diff timestamps to UTC standard with T and Z notation
- Fix json issue where diff sub-structures are escaped
- Add 20 sec timeout on all urlfethc (inter-actor) communication
- Support using creator passphrase as bearer token IF creator username == trustee
  and passphrase has bitstrength > 80
- Added id, peerid, and subscriptionid in subscriptions to align with spec
- Add modiify() for actor to allow change of creator username
- Add support for /trust/trustee operations to align with spec
- Add /devtest path and config.devtest bool to allow test scripts
- Add /devtest testing of all aw_proxy functionality

Nov 17, 2016
--------------------
- Renaming of getPeer() and deletePeer() to get_peer_trustee() and delete_peer_trustee() to avoid confusion
- Support for oauth_put() (and corresponding put_request()) and fix to accept 404 without refreshing token
- aw_proxy support for get_resource(), change_resource((), and delete_resource(()
- Support PUT on /resources

Nov 5, 2016
--------------------
- Add support for getResources in aw_proxy.py
- Renamed peer to peerTrustee in peer.py to better reflect that it is created by actor as trustee

Nov 1, 2016
--------------
- Add support for change_resource(() and delete_resource(() in aw_proxy.py
- Add support for PUT to /resources and on_put_resources() in on_aw_resources.py

Oct 28, 2016
--------------
- Add support for establishment and tear-down of peer actors as trustee, actor.getPeer() and actor.deletePeer()

  - Add new db storage for peers created as trustee
  - Add new config.actor section in config.py to define known possible peers
- Add new actor support function: getTrustRelationshipByType()
- Add new AwProxy() class with helper functions to do RPCish peer operations on trust relationships

  - Either use trust_target or peer_target to send commands to a specific trust or to the trust associated with a peer (i.e. peer created by this app as a trustee)
  - Support for create_resource() (POST on remote actor path like /resources or /properties)
- Fix bug where clean up of actor did not delete remote subscription (actor.delete())

  - Add remoteSubscription deletion in aw-actor-subscription.py
  - Fix auth issue in aw-actor-callbacks.py revealed by ths bug

Oct 26, 2016
--------------
- Add support for trustee by adding trustee_root to actor factory
- Add debug logging in auth process
- Fix bug where actors created within the same second got the same id

Oct 15, 2016
--------------
- Added support for requests to /bot and a bot (permanent) token in config.py to do API requests
  without going through the /<actorid>/ paths. Used to support scenarios where users can communicate with a bot to
  initiate creation of an actor (or to do commands that don't need personal oauth authorization.

Oct 12, 2016
--------------
- Support for actor.get_from_property(property-name, value) to initialse an actor from db by looking up a property value
  (it must be unique)

Oct 9, 2016
--------------
- Added support for GET, PUT, and DELETE for any sub-level of /properties, 
  also below resource, i.e. /properties/<subtarget>/<resource>/something/andmore/...
- Fixed bug where blob='', i.e. deletion, would not be registered

Oct 7, 2016
--------------
- Added support for resource (in addition to target and subtarget) in subscriptions, thus allowing subscriptions to
  e.g. /resources/files/<fileid> (where <fileid> is the resource to subscribe to. /properties/subtarget/resource
  subscriptions are also allowed.

Oct 6, 2016
--------------
- Added support for /resources with on_aw_resources.py in on_aw/ to hook into GET, DELETE, and POST requests to /resources
- Added fixes for box.com specific OAUTH implementation
- Added new function oauth_get(), oauth_post(), and oauth_delete() to Auth() class. These will refresh a token if necessary and
  can be used insted of oauth.get_request(), post_request(), and delete_request(()
- Minor refactoring of inner workings of auth.py and oauth.py wrt return values and error codes

Sep 25, 2016
--------------
- Added use_cache=False to all db operations to avoid cache issue when there are multiple instances of same app in gae

Sep 4, 2016
--------------
- Refactoring of creation of trust:
  - ensure that secret is generated by initiating peer
  - ensure that a peer cannot have more than one relationship
  - ensure that a secret can only be used for one relationship

Aug 28, 2016
--------------
- Major refactoring of auth.py. Only affects how init_actingweb() is used, see function docs

Aug 21, 2016: New features
--------------------------
- Removed the possibility of setting a secret when initiating a new relationship, as well as ability to change secret. This is to avoid the possibility of detecting existing secrets (from other peers) by testing secrets

Aug 15, 2016: Bug fixes
------------------------
- Added new acl["approved"] flag to auth.py indicating whether an authenticated peer has been approved
- Added new parameter to the authorise() function to turn off the requirement that peer has been approved to allow access
- Changed default relationship to the lowest level (associate) and turned off default approval of the default relationship
- Added a new authorisation check to subscriptions to make sure that only peers with access to a path are allowed to subscribe to those paths
- Added a new approval in trust to allow non-approved peers to delete their relationship (in case they want to "withdraw" their relationship request)
- Fixed uncaught json exception in create_remote_subscription()
- Fixed possibility of subpath being None instead of '' in auth.py
- Fixed handling of both bool json type and string bool value for approved parameter for trust relationships


Aug 6, 2016: New features
----------------------------
- Support for deleting remote subscription (i.e. callback and subscription, dependent on direction) when an actor is
  deleted

  - New delete_remote_subscription() in actor.py
  - Added deletion to actor.delete()
  - New handler for DELETE of /callbacks in aw-actor-callbacks.py
  - New on_delete_callbacks() in on_aw_callbacks.py

Aug 6, 2016: Bug fixes
----------------------------
- Fixed bug where /meta/nonexistent resulted in 500

Aug 3, 2016: New features
----------------------------
- Support for doing callbacks when registering diffs

  - New function in actor.py: callback_subscription()
  - Added defer of callbacks to avoid stalling responses when adding diffs
  - Added new function get_trust_relationship() to get one specific relationship based on peerid (instead of searching using get_trust_relationships())
- Improved diff registration

  - Totally rewrote register_diffs() to register diffs for subscriptions that are not exact matches (i.e. broader/higher-level and more specific)
  - Added debug logging to trace how diffs are registered
- Owner-based access only to /callbacks/subscriptions
- Support for handling callbacks for subscriptions

  - New function in on_aw_callbacks.py: on_post_subscriptions() for handling callbacks on subscriptions
  - Changed aw-actor-callbacks.py to handle POSTs to /callbacks/subscriptions and forward those to on_post_subscriptions()

Aug 3, 2016: Bug fixes
----------------------------
- Added no cache to the rest of subscriptionDiffs DB operations to make sure that deferred subscription callbacks don't mess up sequencing
- Changed meta/raml to meta/specification to allow any type of specification language

Aug 1, 2016: New features
----------------------------
- Added support for GET on subscriptions as peer, generic register diffs function, as well as adding diffs when changing /properties. Also added support for creator initiating creation of a subscription by distingushing on POST to /subscriptions (as creator to inititate a subscription with another peer) and to /subscriptions/<peerid> (as peer to create subscription)
- Subscription is also created when initiating a remote subscription (using callback bool to set flag to identify a subscription where callback is expected). Still missing support for sending callbacks (high/low/none), as well as processing callbacks
- Added support for sequence number in subscription, so that missing diffs can be detected. Specific diffs can be retrieved by doing GET as peer on /subscriptions/<peerid>/<subid>/<seqnr> (and the diff will be cleared)

Jul 27, 2016: New features
----------------------------
- Started adding log statements to classes and methods
- Added this file to track changes
- Added support for requesting creation of subscriptions, GETing (with search) all subscriptions as creator (not peer), as well as deletion of subscriptions when an actor is deleted (still remaining GET all relationship as peer, GET on relationship to get diffs, DELETE subscription as peer, as well as mechanism to store diffs)

Jul 27, 2016: Bug fixes
----------------------------
- Changed all ndb.fetch() calls to not include a max item number
- Cleaned up actor delete() to go directly on database to delete all relevant items
- Fixed a bug where the requested peer would not store the requesting actor's mini-app type in db (in trust)
- Added use_cache=False in all trust.py ndb calls to get rid of the cache issues experienced when two different threads communicate to set up a trust
- Added a new check and return message when secret is not included in an "establish trust" request (requestor must always include secret)

July 12, 2016: New features
----------------------------
- config.py cleaned up a bit

July 12, 2016: Bug fixes
----------------------------
- Fix in on_aw_oauth_success where token can optionally supplied (first time oauth was done the token has not been flushed to db)
- Fix in on_aw_oauth_success where login attempt with wrong Spark user did not clear the cookie_redirect variable
- Fixed issue with wrong Content-Type header for GET and DELETE messages without json body
