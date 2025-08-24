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
--------------------

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
-------------------

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

Architecture
============

The Unified Access Control system consists of four main components:

Trust Type Registry
------------------

Manages the registration and storage of trust relationship types. Trust types are stored globally using ActingWeb's attribute bucket pattern.

**Storage Pattern:**
  * Actor ID: ``_actingweb_system``
  * Bucket: ``trust_types``
  * Key: ``{trust_type_name}``

Trust Permission Store
---------------------

Handles per-relationship permission overrides that customize the base permissions defined by trust types.

**Storage Pattern:**
  * Actor ID: ``{actor_id}`` 
  * Bucket: ``trust_permissions``
  * Key: ``{actor_id}:{peer_id}``

Permission Evaluator
-------------------

The core engine that combines trust type base permissions with individual overrides to make authorization decisions.

Enhanced Trust Model
--------------------

The existing trust database model has been extended with new fields while maintaining full backward compatibility:

* ``peer_identifier`` - Generic identifier supporting email, username, UUID, etc.
* ``established_via`` - Method of establishment: ``actingweb``, ``oauth2``, or ``mcp``
* ``created_at`` - Trust relationship creation timestamp
* ``last_accessed`` - Last access timestamp for analytics

System Constants
===============

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
   ESTABLISHED_VIA_OAUTH2 = "oauth2"
   ESTABLISHED_VIA_MCP = "mcp"

Pattern Matching
===============

The permission system supports sophisticated pattern matching for scalable access control:

Glob Patterns
------------

* ``*`` - Matches any characters: ``get_*`` matches ``get_profile``, ``get_notes``
* ``?`` - Matches single character: ``get_?`` matches ``get_a`` but not ``get_ab``  
* ``exact`` - Exact string match

Path Patterns
------------

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
=============

The Unified Access Control system follows security best practices:

Fail Secure
-----------

The system defaults to denying access when:

* No permission rule matches the request
* Permission evaluation encounters an error
* Trust relationship or trust type cannot be found

Precedence Rules
---------------

Permission evaluation follows this precedence order:

1. **Explicit Deny**: Denied patterns in trust types or overrides (highest priority)
2. **Explicit Allow**: Allowed patterns in overrides
3. **Trust Type Allow**: Allowed patterns in base trust type
4. **Default Deny**: No matching rule found (lowest priority)

Audit Trail
----------

The system maintains audit capabilities through:

* Trust relationship timestamps (``created_at``, ``last_accessed``)
* Permission evaluation logging
* Security event tracking

Performance Considerations
=========================

The system is designed for high performance through:

Caching Strategy
---------------

* **Pattern Cache**: Compiled regex patterns are cached for reuse
* **Registry Cache**: Trust types cached after first load
* **Permission Cache**: Individual permissions cached per relationship
* **Singleton Pattern**: Single evaluator instance per process

Database Efficiency
------------------

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

Backward Compatibility
=====================

The Unified Access Control system maintains full backward compatibility:

Database Schema
--------------

* All existing trust model fields remain unchanged
* New fields are optional and nullable
* Existing queries continue to work

API Compatibility
----------------

* Existing ActingWeb handler patterns continue to work
* No changes required to existing applications
* New permission checks can be added incrementally

Migration Path
-------------

Applications can adopt the new system gradually:

1. **Phase 1**: System runs alongside existing access control
2. **Phase 2**: Add permission checks to sensitive operations
3. **Phase 3**: Register custom trust types for application needs
4. **Phase 4**: Full migration to unified permission evaluation

This approach allows existing applications to continue operating while new applications can take full advantage of the unified access control capabilities.

Implementation Guide
===================

For practical implementation details and simple usage patterns, see:

* :doc:`unified-access-control-simple` - Simple developer guide

The Unified Access Control system provides the foundation for:

* **OAuth2 Integration**: Trust type selection during OAuth2 flows
* **MCP Client Unification**: Seamless AI assistant integration
* **Template Customization**: UI customization for 3rd party applications
* **Advanced Analytics**: Trust relationship and access pattern analysis