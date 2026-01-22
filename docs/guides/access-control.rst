=======================================
ActingWeb Unified Access Control System
=======================================

The ActingWeb Unified Access Control system provides a comprehensive framework for managing permissions across ActingWeb protocol interactions, OAuth2 authentication, and MCP (Model Context Protocol) clients. This system unifies all access control decisions through a flexible, extensible architecture.

.. contents::
   :local:
   :depth: 2

Overview
========

The Unified Access Control system addresses the modern needs of ActingWeb applications by providing:

* **Trust Type Management**: Pre-defined and custom relationship templates with base permissions
* **Per-Relationship Customization**: Individual permission overrides for specific trust relationships
* **Multi-Protocol Support**: Unified handling of ActingWeb peers, OAuth2 users, and MCP clients
* **Granular Permissions**: Fine-grained control over properties, methods, actions, tools, resources, and prompts
* **Pattern Matching**: Flexible glob and URI pattern support for scalable permission rules
* **Backward Compatibility**: Existing ActingWeb applications continue to work without modification

Core Concepts
=============

Trust Types
-----------

Trust types are templates that define the base permissions for different kinds of relationships. ActingWeb provides six built-in trust types:

.. list-table:: Built-in Trust Types
   :header-rows: 1
   :widths: 15 30 55

   * - Trust Type
     - Use Case  
     - Key Permissions
   * - ``associate``
     - Basic ActingWeb peer relationship
     - Public properties (read-only)
   * - ``viewer``
     - Read-only access user
     - Public and shared properties (read-only)
   * - ``friend``
     - Standard trusted relationship
     - Most access, limited admin functions
   * - ``partner``
     - Business partner or collaborator
     - Enhanced access, some admin capabilities
   * - ``admin``
     - Full administrative access
     - All permissions granted
   * - ``mcp_client``
     - AI assistant or MCP client
     - Configurable tools, resources, and prompts

Permission Categories
---------------------

The system controls access across six categories:

**Properties**
  Access to actor property data using path patterns like ``public/*``, ``notes/work/*``

**Methods**
  ActingWeb method calls like ``get_profile``, ``list_notes``

**Actions**
  ActingWeb action calls like ``create_note``, ``send_message``

**Tools**
  MCP tool access like ``search``, ``fetch``, ``create_note``

**Resources**
  MCP resource access using URI patterns like ``notes://``, ``usage://``

**Prompts**
  MCP prompt access like ``analyze_notes``, ``summarize_document``

Permission Structure
--------------------

Permissions are defined using flexible structures that support both explicit lists and pattern matching:

.. code-block:: python

   {
       "properties": {
           "patterns": ["public/*", "shared/*"],           # Allowed path patterns
           "operations": ["read", "write"],                # Allowed operations  
           "excluded_patterns": ["private/*"]              # Explicitly excluded
       },
       "methods": {
           "allowed": ["get_*", "list_*"],                # Allowed method patterns
           "denied": ["delete_*", "admin_*"]              # Explicitly denied
       },
       "tools": {
           "allowed": ["search", "fetch"],                # Specific tools allowed
           "denied": ["admin_*"]                          # Denied tool patterns
       }
   }

ACL Rules (HTTP Endpoint Access)
--------------------------------

In addition to high-level permissions (properties, methods, tools, etc.), trust types can specify
**ACL rules** that control access to HTTP endpoints. This is essential for enabling trust types
to interact with ActingWeb REST endpoints like ``/subscriptions``, ``/trust``, and custom paths.

**Why ACL Rules?**

The ActingWeb framework has two separate access control layers:

1. **High-Level Permissions** - Control access to data and operations (properties, methods, tools)
2. **ACL Rules** - Control access to HTTP REST endpoints

By default, only built-in trust types like ``friend``, ``owner``, and ``creator`` have ACL rules
defined. Custom trust types need to explicitly specify ACL rules to access endpoints like
``/subscriptions/<id>`` for creating subscriptions.

**ACL Rule Format:**

Each rule is a tuple of ``(path, methods, access)`` where:

* ``path`` - HTTP path pattern (e.g., ``subscriptions/<id>``, ``properties``)
* ``methods`` - HTTP methods (``GET``, ``POST``, ``PUT``, ``DELETE``, or ``""`` for all methods)
* ``access`` - ``a`` for allow, ``r`` for reject

.. code-block:: python

   acl_rules = [
       ("subscriptions/<id>", "POST", "a"),  # Allow creating subscriptions
       ("properties", "GET", "a"),           # Allow reading properties
       ("properties", "PUT", "a"),           # Allow updating properties
       ("callbacks", "", "a"),               # Allow all methods on callbacks
   ]

**Common ACL Paths:**

* ``subscriptions/<id>`` - Creating/managing subscriptions (POST to create)
* ``properties`` - Property access (GET/PUT)
* ``trust/<type>/<id>`` - Trust relationship management
* ``callbacks`` - Receiving subscription callbacks

Built-in Trust Type Definitions
-------------------------------

For reference, here is how the built-in ``friend`` trust type is defined internally.
You can use the same pattern for custom trust types:

.. code-block:: python

   # The built-in "friend" trust type (for reference)
   # This is how ActingWeb defines it internally
   access_control.add_trust_type(
       name="friend",
       display_name="Friend",
       description="Standard trusted relationship with access to most resources",
       permissions={
           "properties": {
               "patterns": ["*"],
               "operations": ["read", "write"],
               "excluded_patterns": ["private/*", "security/*", "_internal/*"]
           },
           "methods": {
               "allowed": ["*"],
               "denied": ["delete_*", "admin_*", "system_*"]
           },
           "actions": {
               "allowed": ["*"],
               "denied": ["delete_*", "admin_*", "system_*"]
           },
           "tools": {
               "allowed": ["*"],
               "denied": ["admin_*", "system_*"]
           },
           "resources": {
               "patterns": ["*"],
               "operations": ["read", "write"],
               "excluded_patterns": ["private/*", "security/*"]
           }
       },
       oauth_scope="actingweb.friend"
       # Note: friend uses default ACL rules from config.access,
       # which already includes entries like ("friend", "subscriptions/<id>", "", "a")
   )

**Example: Custom Subscriber Trust Type with ACL Rules**

For actor-to-actor subscription scenarios, you need to specify ACL rules:

.. code-block:: python

   # Custom trust type for actors subscribing to each other's data
   access_control.add_trust_type(
       name="subscriber",
       display_name="Subscriber",
       description="Trust type for actors subscribing to each other's properties",
       permissions={
           "properties": {
               "patterns": ["memory_*", "public/*"],
               "operations": ["read"]
           },
           "methods": {
               "allowed": ["get_*", "list_*"],
               "denied": ["delete_*", "admin_*"]
           }
       },
       # ACL rules enable HTTP endpoint access
       acl_rules=[
           ("subscriptions/<id>", "POST", "a"),  # Create subscriptions
           ("properties", "GET", "a"),           # Read properties
           ("callbacks", "", "a"),               # Receive callbacks (all methods)
       ]
   )

Architecture
============

The Unified Access Control system consists of four main components:

Trust Type Registry
-------------------

Manages the registration and storage of trust relationship types. Trust types are stored globally using ActingWeb's attribute bucket pattern.

**Storage Pattern:**
  * Actor ID: ``_actingweb_system``
  * Bucket: ``trust_types``
  * Key: ``{trust_type_name}``

Trust Permission Store
----------------------

Handles per-relationship permission overrides that customize the base permissions defined by trust types.

**Storage Pattern:**
  * Actor ID: ``{actor_id}`` 
  * Bucket: ``trust_permissions``
  * Key: ``{actor_id}:{peer_id}``

Permission Evaluator
--------------------

The core engine that combines trust type base permissions with individual overrides to make authorization decisions.

Enhanced Trust Model
--------------------

The existing trust database model has been extended with new fields while maintaining full backward compatibility:

* ``peer_identifier`` - Generic identifier supporting email, username, UUID, etc.
* ``established_via`` - Precise method of establishment (e.g., ``trust``, ``oauth2_interactive``, ``oauth2_client``)
* ``created_at`` - Original creation timestamp (when relationship was established)
* ``last_accessed`` - Raw last-access timestamp used for analytics/migrations
* ``last_connected_at`` - Normalized "last connected" timestamp exposed to templates/clients
* ``last_connected_via`` - Method used for the most recent connection (``trust``, ``subscription``, ``oauth``, ``mcp``)

System Constants
================

The system uses standardized constants for consistent global data storage:

.. code-block:: python

   # System Actor IDs
   ACTINGWEB_SYSTEM_ACTOR = "_actingweb_system"    # Core ActingWeb functionality
   OAUTH2_SYSTEM_ACTOR = "_actingweb_oauth2"       # OAuth2/MCP authentication
   
   # Bucket Names
   TRUST_TYPES_BUCKET = "trust_types"
   TRUST_PERMISSIONS_BUCKET = "trust_permissions"
   
   # Establishment Methods
   ESTABLISHED_VIA_ACTINGWEB = "actingweb"
   ESTABLISHED_VIA_OAUTH2_INTERACTIVE = "oauth2_interactive"
   ESTABLISHED_VIA_OAUTH2_CLIENT = "oauth2_client"

Pattern Matching
================

The permission system supports sophisticated pattern matching for scalable access control:

Glob Patterns
-------------

* ``*`` - Matches any characters: ``get_*`` matches ``get_profile``, ``get_notes``
* ``?`` - Matches single character: ``get_?`` matches ``get_a`` but not ``get_ab``  
* ``exact`` - Exact string match

Path Patterns
-------------

* ``public/*`` - Matches all paths under ``public/``
* ``notes/work/*`` - Matches all work-related notes
* ``api/v1/users`` - Exact path match

URI Patterns (MCP Resources)
----------------------------

* ``notes://`` - Matches any notes resource: ``notes://work/project1``
* ``usage://statistics`` - Specific usage resource with path

Operations
----------

Different permission categories support different operations:

* **Properties/Resources**: ``read``, ``write``, ``delete``, ``subscribe``
* **Methods/Actions/Tools/Prompts**: Typically just existence/access checks

Security Model
==============

The Unified Access Control system follows security best practices:

Fail Secure
-----------

The system defaults to denying access when:

* No permission rule matches the request
* Permission evaluation encounters an error
* Trust relationship or trust type cannot be found

Precedence Rules
----------------

Permission evaluation follows this precedence order:

1. **Explicit Deny**: Denied patterns in trust types or overrides (highest priority)
2. **Explicit Allow**: Allowed patterns in overrides
3. **Trust Type Allow**: Allowed patterns in base trust type
4. **Default Deny**: No matching rule found (lowest priority)

Audit Trail
-----------

The system maintains audit capabilities through:

* Trust relationship timestamps (``created_at``, ``last_accessed``)
* Permission evaluation logging
* Security event tracking

Permission Override Merging
---------------------------

When individual trust relationships override base trust type permissions, the system uses
**union merge** semantics for ``patterns`` and ``excluded_patterns`` arrays by default.
This provides fail-safe security:

**Default Behavior (merge_base=True):**

* Base ``patterns`` are preserved; overrides can only ADD patterns
* Base ``excluded_patterns`` are preserved; overrides can only ADD exclusions
* Other fields (``operations``, ``allowed``, ``denied``) are replaced by overrides

.. code-block:: python

   # Example: mcp_client trust type has base patterns
   base_permissions = {
       "properties": {
           "patterns": ["public/*", "shared/*", "profile/*"],
           "excluded_patterns": ["private/*", "security/*", "oauth_*"]
       }
   }

   # Individual override adds memory_* access
   override = {
       "properties": {
           "patterns": ["memory_*"],
           "excluded_patterns": ["memory_personal"]
       }
   }

   # Result: patterns and excluded_patterns are UNIONED
   # patterns: ["public/*", "shared/*", "profile/*", "memory_*"]
   # excluded_patterns: ["private/*", "security/*", "oauth_*", "memory_personal"]

**Security Benefits:**

* Profile properties (displayname, email, etc.) remain accessible regardless of overrides
* Security exclusions (private/*, oauth_*) cannot be accidentally removed
* Individual grants can only expand access, not reduce base trust type security

**Full Override Mode (merge_base=False):**

When explicit full control is needed, pass ``merge_base=False`` to ``merge_permissions()``:

.. code-block:: python

   from actingweb.trust_permissions import merge_permissions

   # Override replaces base patterns entirely
   result = merge_permissions(base, override, merge_base=False)

   # patterns: ["memory_*"] (base patterns NOT preserved)
   # excluded_patterns: ["memory_personal"] (base exclusions NOT preserved)

**Design Decision:**

Base trust type patterns can no longer be restricted by individual overrides for HTTP endpoint
access when using the default ``merge_base=True``. This is intentional:

* Ensures consistent profile display across all MCP clients
* Prevents accidental security regressions
* Simplifies permission management for administrators

To restrict access, use ``excluded_patterns`` instead of trying to narrow ``patterns``.

Performance Considerations
==========================

The system is designed for high performance through:

Caching Strategy
----------------

* **Pattern Cache**: Compiled regex patterns are cached for reuse
* **Registry Cache**: Trust types cached after first load
* **Permission Cache**: Individual permissions cached per relationship
* **Singleton Pattern**: Single evaluator instance per process

Database Efficiency
-------------------

* **Attribute Buckets**: Efficient key-value storage using DynamoDB
* **Global Indexes**: Fast token and client lookups for OAuth2/MCP
* **Lazy Loading**: Permissions loaded only when needed
* **Distributed Storage**: Per-actor permission storage for horizontal scaling

Thread Safety
-------------

All components are designed to be thread-safe:

* Immutable data structures for trust types and permissions
* Safe singleton implementation
* Stateless permission evaluation
* DynamoDB consistency guarantees

Permission System Initialization
--------------------------------

**Good News**: The ActingWeb permission system is **automatically initialized** when you use Flask or FastAPI integration - no manual setup required!

**Automatic Initialization:**

.. code-block:: python

   # Permission system automatically initialized here - nothing else needed!
   app = ActingWebApp(...)
   integration = app.integrate_fastapi(fastapi_app)  # Auto-initializes permissions
   
   # Or for Flask:
   integration = app.integrate_flask(flask_app)      # Auto-initializes permissions

**Manual Initialization (Advanced Use Cases):**

If you need to initialize before integration (e.g., testing, custom frameworks), you can still do it manually:

.. code-block:: python

   # Optional - only needed for advanced use cases
   try:
       from actingweb.permission_initialization import initialize_permission_system
       initialize_permission_system(app.get_config())
       logger.info("ActingWeb permission system initialized manually")
   except Exception as e:
       logger.debug(f"Permission system initialization failed: {e}")
       # System will fall back gracefully with lazy loading

**What Gets Initialized:**

1. **Trust Type Registry**: Pre-compiles all trust types and permission patterns
2. **Permission Evaluator**: Pre-loads system patterns and rule engine  
3. **Trust Permission Store**: Initializes custom permission overrides system

**Debugging Initialization Issues:**

With automatic initialization, performance issues should be rare. If you still experience:

* OAuth2 callbacks hanging for minutes
* Extremely slow first requests after startup
* Logs showing "Initializing trust type registry..." during requests

This indicates the automatic initialization failed. Check your logs for initialization errors.

**Expected Initialization Logs:**

.. code-block:: text

   ActingWeb permission system initialized automatically
   Trust type registry initialized with X types
   Permission evaluator initialized successfully  
   Trust permission store initialized

The system includes graceful fallbacks - if automatic initialization fails during integration, individual components will fall back to lazy loading with debug messages.

Backward Compatibility
======================

The Unified Access Control system maintains full backward compatibility:

Database Schema
---------------

* All existing trust model fields remain unchanged
* New fields are optional and nullable
* Existing queries continue to work

API Compatibility
-----------------

* Existing ActingWeb handler patterns continue to work
* No changes required to existing applications
* New permission checks can be added incrementally

Migration Path
--------------

Applications can adopt the new system gradually:

1. **Phase 1**: System runs alongside existing access control
2. **Phase 2**: Add permission checks to sensitive operations
3. **Phase 3**: Register custom trust types for application needs
4. **Phase 4**: Full migration to unified permission evaluation

This approach allows existing applications to continue operating while new applications can take full advantage of the unified access control capabilities.

Trust API Enhancements
======================

The unified access control system extends the standard ActingWeb ``/trust`` API with permission management capabilities, allowing fine-grained control over individual trust relationships.

Enhanced Trust Relationship API
-------------------------------

**GET /trust/{relationship}/{peerid}**

The standard trust relationship endpoint now supports an optional ``permissions`` query parameter to include permission information in the response:

.. code-block:: bash

   GET /myapp/actor123/trust/friend/peer456?permissions=true

Response includes permission overrides if they exist:

.. code-block:: json

   {
     "peerid": "peer456",
     "relationship": "friend",
     "approved": true,
     "verified": true,
     "permissions": {
       "properties": {"allowed": ["notes/*"], "denied": ["private/*"]},
       "methods": {"allowed": ["get_*", "list_*"]},
       "tools": {"allowed": ["search", "create_note"]},
       "created_by": "admin",
       "notes": "Custom permissions for this relationship"
     }
   }

**PUT /trust/{relationship}/{peerid}**

The PUT endpoint now accepts permission updates alongside traditional trust relationship modifications:

.. code-block:: json

   {
     "approved": true,
     "desc": "Updated relationship description",
     "permissions": {
       "properties": {
         "allowed": ["public/*", "notes/*"],
         "denied": ["private/*", "security/*"]
       },
       "methods": {
         "allowed": ["get_*", "list_*", "search_*"],
         "denied": ["delete_*", "admin_*"]
       },
       "tools": {
         "allowed": ["search", "fetch", "create_note"]
       },
       "notes": "Customized permissions for enhanced access"
     }
   }

Permission Management API
-------------------------

The system introduces a new dedicated API for managing per-relationship permission overrides:

**GET /trust/{relationship}/{peerid}/permissions**

Retrieve detailed permission overrides for a specific trust relationship:

.. code-block:: bash

   GET /myapp/actor123/trust/friend/peer456/permissions

Response:

.. code-block:: json

   {
     "actor_id": "actor123",
     "peer_id": "peer456", 
     "trust_type": "friend",
     "properties": {
       "patterns": ["public/*", "notes/*"],
       "operations": ["read", "write"],
       "excluded_patterns": ["private/*"]
     },
     "methods": {
       "allowed": ["get_*", "list_*", "create_*"],
       "denied": ["delete_*", "admin_*"]
     },
     "tools": {
       "allowed": ["search", "fetch", "create_note"],
       "denied": ["admin_*", "system_*"]
     },
     "resources": {
       "patterns": ["notes://*", "public://*"],
       "operations": ["read"]
     },
     "created_by": "admin",
     "updated_at": "2024-01-15T10:30:00Z",
     "notes": "Custom permissions for enhanced access"
   }

**PUT /trust/{relationship}/{peerid}/permissions**

Create or update permission overrides for a trust relationship:

.. code-block:: json

   {
     "properties": {
       "patterns": ["public/*", "shared/*", "notes/*"],
       "operations": ["read", "write"],
       "excluded_patterns": ["private/*", "security/*"]
     },
     "methods": {
       "allowed": ["get_*", "list_*", "create_*", "update_*"],
       "denied": ["delete_*", "admin_*", "system_*"]
     },
     "tools": {
       "allowed": ["search", "fetch", "create_note", "update_note"],
       "denied": ["delete_*", "admin_*"]
     },
     "notes": "Enhanced permissions for trusted partner"
   }

**DELETE /trust/{relationship}/{peerid}/permissions**

Remove permission overrides, reverting to trust type defaults:

.. code-block:: bash

   DELETE /myapp/actor123/trust/friend/peer456/permissions

Permission Structure
--------------------

Permission overrides follow this structure:

**Properties**
  Controls access to actor property storage:

  .. code-block:: json

     {
       "patterns": ["public/*", "notes/*"],
       "operations": ["read", "write", "delete"],
       "excluded_patterns": ["private/*", "security/*"]
     }

**Methods**
  Controls ActingWeb method calls:

  .. code-block:: json

     {
       "allowed": ["get_*", "list_*", "create_*"],
       "denied": ["delete_*", "admin_*", "system_*"]
     }

**Actions**
  Controls ActingWeb action execution:

  .. code-block:: json

     {
       "allowed": ["search", "fetch", "export"],
       "denied": ["delete_*", "admin_*"]
     }

**Tools** (MCP)
  Controls MCP tool access:

  .. code-block:: json

     {
       "allowed": ["search", "fetch", "create_note"],
       "denied": ["admin_*", "system_*", "delete_*"]
     }

**Resources** (MCP)
  Controls MCP resource access:

  .. code-block:: json

     {
       "patterns": ["notes://*", "public://*"],
       "operations": ["read", "subscribe"],
       "excluded_patterns": ["private://*"]
     }

**Prompts** (MCP)
  Controls MCP prompt access:

  .. code-block:: json

     {
       "allowed": ["analyze_*", "create_*", "summarize_*"]
     }

Feature Discovery
=================

ActingWeb applications supporting the unified access control system automatically include the ``trustpermissions`` feature tag in their ``/meta/actingweb/supported`` endpoint response. This allows clients to discover permission management capabilities:

.. code-block:: bash

   GET /myapp/actor123/meta/actingweb/supported
   
   # Response includes:
   www,oauth,callbacks,trust,onewaytrust,subscriptions,actions,resources,methods,sessions,nestedproperties,trustpermissions

The presence of ``trustpermissions`` indicates support for:

* Enhanced trust relationship endpoints with permission query parameters
* Dedicated permission management endpoints (``/permissions`` sub-endpoint)
* Per-relationship permission overrides
* Standardized permission structures

Implementation Guide
====================

For practical implementation details and simple usage patterns, see:

* :doc:`access-control-simple` - Simple developer guide

The Unified Access Control system provides the foundation for:

* **OAuth2 Integration**: Trust type selection during OAuth2 flows
* **MCP Client Unification**: Seamless AI assistant integration  
* **Permission Management**: Per-relationship permission customization through REST API
* **Feature Discovery**: Automatic ``trustpermissions`` tag in ``/meta/actingweb/supported``
* **Template Customization**: UI customization for 3rd party applications
* **Advanced Analytics**: Trust relationship and access pattern analysis
