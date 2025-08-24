========================================
ActingWeb Access Control (Simple Guide)
========================================

ActingWeb's Unified Access Control system works transparently with your existing hooks. You don't need to add permission checks to your code - ActingWeb handles them automatically.

.. contents::
   :local:
   :depth: 2

Quick Start
===========

For most applications, you only need to do two things:

1. **Define any custom relationship types** you need (optional)
2. **Write your hooks as normal** - ActingWeb handles permission checking automatically

That's it! No explicit permission checking code required.

Simple Example
=============

Here's a complete example of adding access control to an ActingWeb application:

.. code-block:: python

   from actingweb.interface import ActingWebApp
   from actingweb.permission_integration import AccessControlConfig

   # Create your ActingWeb app as usual
   app = ActingWebApp(
       aw_type="urn:actingweb:example.com:myapp",
       database="dynamodb",
       fqdn="myapp.example.com"
   ).with_oauth(
       client_id="your-oauth-client-id",
       client_secret="your-oauth-client-secret"
   )

   # Configure access control (optional - only if you need custom trust types)
   access_control = AccessControlConfig(app.config)
   
   # Add a custom trust type for API clients
   access_control.add_trust_type(
       name="api_client",
       display_name="API Client", 
       permissions={
           "properties": ["public/*", "api/*"],      # Can access public and api properties
           "methods": ["get_*", "list_*"],           # Can call getter and list methods
           "tools": []                               # No MCP tools allowed
       }
   )

   # Write your hooks as normal - no permission checking code needed!
   @app.property_hook("email")
   def handle_email_property(actor, operation, value, path):
       if operation == "write":
           # Validate email format
           if "@" not in value:
               return False
           # Store validated email
           actor.properties.set("validated_email", value)
       return value

   @app.mcp_tool_hook("search")  
   def handle_search_tool(actor, params):
       # Implement search functionality
       query = params.get("query", "")
       return {"results": search_notes(actor, query)}

**That's it!** ActingWeb automatically:

- Checks if the requesting peer has permission to access properties, methods, or tools
- Allows or denies access based on the trust relationship
- Only calls your hooks if permission is granted

Built-in Trust Types
===================

ActingWeb provides these trust types out of the box:

.. list-table::
   :header-rows: 1
   :widths: 20 30 50

   * - Trust Type
     - Use Case
     - Default Permissions
   * - ``viewer``
     - Read-only users
     - Can read ``public/*`` and ``shared/*`` properties
   * - ``friend``
     - Trusted users
     - Can access most properties and methods (not admin functions)
   * - ``partner``
     - Business partners
     - Enhanced access, some admin capabilities
   * - ``admin``
     - Administrators
     - Full access to everything
   * - ``mcp_client``
     - AI assistants
     - Basic property access, user must grant specific tools

**For most applications, these built-in types are sufficient.**

Custom Trust Types (Optional)
=============================

Only add custom trust types if the built-in ones don't meet your needs:

.. code-block:: python

   from actingweb.permission_integration import AccessControlConfig

   access_control = AccessControlConfig(config)

Simple Format
------------

Use the simple format for basic permissions:

.. code-block:: python

   access_control.add_trust_type(
       name="mobile_app",
       display_name="Mobile App",
       permissions={
           "properties": ["public/*", "profile/*"],     # Property patterns
           "methods": ["get_*", "update_profile"],      # Method patterns  
           "actions": ["send_notification"],            # Action names
           "tools": ["search", "create_note"],          # MCP tool names
           "resources": ["notes://", "usage://"],       # MCP resource patterns
           "prompts": ["summarize_*"]                   # MCP prompt patterns
       }
   )

Advanced Format
--------------

Use the advanced format for fine-grained control:

.. code-block:: python

   access_control.add_trust_type(
       name="enterprise_client",
       display_name="Enterprise Client",
       permissions={
           "properties": {
               "patterns": ["enterprise/*", "public/*"],
               "operations": ["read", "write"],
               "excluded_patterns": ["enterprise/secrets/*"]
           },
           "methods": {
               "allowed": ["*"],
               "denied": ["admin_*", "delete_*"]
           },
           "tools": {
               "allowed": ["search", "analytics"],
               "denied": ["admin_*"]
           }
       },
       oauth_scope="myapp.enterprise"
   )

Permission Patterns
==================

Use these patterns to control access:

Property Patterns
----------------

.. code-block:: python

   "properties": [
       "public/*",           # All public properties
       "notes/work/*",       # Work-related notes only
       "profile/basic"       # Specific property
   ]

Method Patterns
--------------

.. code-block:: python

   "methods": [
       "get_*",              # All getter methods
       "list_*",             # All list methods  
       "update_profile"      # Specific method
   ]

Excluded Patterns
----------------

Use the advanced format to exclude specific items:

.. code-block:: python

   "properties": {
       "patterns": ["notes/*"],              # Allow all notes
       "excluded_patterns": ["notes/private/*"]  # Except private notes
   }

How It Works
===========

The access control system integrates seamlessly with ActingWeb:

1. **Request comes in** to your ActingWeb application
2. **ActingWeb identifies the peer** from OAuth token, trust relationship, etc.
3. **Permission check happens automatically** before calling your hooks
4. **Your hook is called** only if permission is granted
5. **Access denied response** sent automatically if permission is denied

Trust Relationship Setup
=======================

Trust relationships are established through:

**OAuth2 Flow**
  User authenticates and selects which trust type to grant

**ActingWeb Protocol**
  Traditional peer-to-peer trust establishment

**MCP Registration**
  AI assistants register with specific capabilities

**API Integration**
  Applications can create trust relationships programmatically

Your hooks don't need to worry about any of this - ActingWeb handles it all.

Migration from Existing Apps
===========================

If you have an existing ActingWeb application:

**No Changes Required**
  Your existing app continues to work without modification

**Add Custom Trust Types** (optional)
  Define any application-specific relationship types you need

**Let ActingWeb Handle Security**
  Remove any manual permission checking code from your hooks

Example migration:

.. code-block:: python

   # Before - manual permission checking
   @app.property_hook("sensitive_data")
   def handle_sensitive_data(actor, operation, value, path):
       # Manual permission check
       if not is_user_authorized(actor, get_current_peer()):
           return {"error": "Access denied"}
       
       return process_data(value)

   # After - automatic permission checking
   @app.property_hook("sensitive_data") 
   def handle_sensitive_data(actor, operation, value, path):
       # No permission checking needed - ActingWeb handles it
       return process_data(value)

Common Patterns
==============

API Client Access
----------------

.. code-block:: python

   access_control.add_trust_type(
       name="api_client",
       display_name="API Client",
       permissions={
           "properties": ["api/*", "public/*"],
           "methods": ["get_*", "list_*"],
           "tools": []  # No AI tools for API clients
       }
   )

Mobile App Access
----------------

.. code-block:: python

   access_control.add_trust_type(
       name="mobile_app", 
       display_name="Mobile App",
       permissions={
           "properties": ["profile/*", "notes/*", "settings/*"],
           "methods": ["*"],
           "actions": ["send_notification", "sync_data"],
           "tools": ["search"]  # Basic search only
       }
   )

AI Assistant Access
------------------

.. code-block:: python

   access_control.add_trust_type(
       name="ai_assistant",
       display_name="AI Assistant", 
       permissions={
           "properties": ["public/*", "notes/*"],
           "tools": ["search", "create_note", "summarize"],
           "prompts": ["analyze_*", "summarize_*"],
           "resources": ["notes://", "usage://"]
       }
   )

Troubleshooting
==============

**Hook not being called?**
  Check that the peer has the required trust relationship and permissions

**Access denied errors?**
  Verify the trust type permissions include the required patterns

**OAuth2 users can't access resources?**
  Make sure the OAuth2 flow includes trust type selection

**MCP tools not working?**
  Check that the MCP client trust relationship includes the required tools

**Need debugging?**
  Enable debug logging to see permission evaluation details:

.. code-block:: python

   import logging
   logging.getLogger("actingweb.permission_evaluator").setLevel(logging.DEBUG)

Advanced Topics
==============

Per-User Permission Overrides
-----------------------------

Users can customize permissions for specific relationships through the web UI or API (implementation details in the full technical documentation).

Custom Permission Logic
----------------------

For complex scenarios, you can still add custom permission logic in your hooks:

.. code-block:: python

   @app.property_hook("financial_data")
   def handle_financial_data(actor, operation, value, path):
       # ActingWeb already checked basic permissions
       # Add custom business logic checks
       if operation == "write" and not validate_financial_data(value):
           return {"error": "Invalid financial data"}
       
       return process_financial_data(value)

Integration with Existing Systems
---------------------------------

The access control system integrates with existing ActingWeb features:

- Web UI for permission management
- OAuth2 flows with trust type selection  
- MCP client registration
- ActingWeb protocol peer relationships

This simple approach lets you focus on your application logic while ActingWeb handles all the security complexity behind the scenes.

See Also
========

* :doc:`unified-access-control` - Complete system overview and architecture