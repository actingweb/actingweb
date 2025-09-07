ActingWeb Developer Interface
=============================

This document describes the modern developer interface for the ActingWeb library. It replaces the complex ``OnAWBase`` callback system with a clean, fluent API and decorator-based hooks.

Actor vs ActorInterface - Important Distinction
-----------------------------------------------

ActingWeb provides two actor classes that serve different purposes:

**Actor (Core/Internal)**
  - Low-level, internal implementation class
  - Used by the ActingWeb framework itself
  - Handles database operations, internal state management
  - **NOT intended for application developers**
  - Located in ``actingweb.actor.Actor``

**ActorInterface (Application/Public)**
  - High-level, developer-friendly interface
  - **This is what applications should use**
  - Provides clean, intuitive API for actor operations
  - Wraps the core Actor class with safety and convenience methods
  - Located in ``actingweb.interface.ActorInterface``

.. important::
   **Always use ActorInterface in your applications.** The core Actor class is an internal implementation detail and may change between versions. ActorInterface provides a stable, documented API with proper error handling and type safety.

Key Features
------------

- **Fluent Configuration API**: Chain configuration methods for easy setup
- **Decorator-Based Hooks**: Simple, focused functions for handling events
- **Automatic Route Generation**: Web framework integration with auto-generated routes
- **Intuitive Actor Interface**: Clean, object-oriented actor management
- **Type Safety**: Better type hints and IDE support
- **Backward Compatibility**: Works with existing ActingWeb applications

Quick Start
-----------

Basic Application
-----------------

.. code-block:: python

    from actingweb.interface import ActingWebApp, ActorInterface

    # Create app with fluent configuration
    app = ActingWebApp(
        aw_type="urn:actingweb:example.com:myapp",
        database="dynamodb",
        fqdn="myapp.example.com"
    ).with_oauth(
        client_id="your-client-id",
        client_secret="your-client-secret"
    ).with_web_ui().with_devtest()

    # Initialize actors after creation
    @app.lifecycle_hook("actor_created")
    def on_actor_created(actor: ActorInterface, **kwargs):
        # Set the creator email as a property
        actor.properties.email = actor.creator

    # Add hooks
    @app.property_hook("email")
    def handle_email(actor, operation, value, path):
        if operation == "get":
            return value if actor.is_owner() else None
        elif operation == "put":
            return value.lower() if "@" in value else None
        return value

    # Run the application
    app.run(port=5000)

Flask Integration
-----------------

.. code-block:: python

    from flask import Flask
    from actingweb.interface import ActingWebApp

    # Create Flask app
    flask_app = Flask(__name__)

    # Create ActingWeb app
    aw_app = ActingWebApp(
        aw_type="urn:actingweb:example.com:myapp",
        database="dynamodb"
    ).with_web_ui()

    # Integrate with Flask (auto-generates all routes)
    aw_app.integrate_flask(flask_app)

    # Run Flask app
    flask_app.run()

Core Components
---------------

ActingWebApp
------------

The main application class that provides fluent configuration:

.. code-block:: python

    app = ActingWebApp(
        aw_type="urn:actingweb:example.com:myapp",
        database="dynamodb",
        fqdn="myapp.example.com"
    )

    # Configuration methods
    app.with_oauth(client_id="...", client_secret="...")
    app.with_web_ui(enable=True)
    app.with_devtest(enable=True)
    app.with_bot(token="...", email="...")
    app.with_unique_creator(enable=True)
    app.add_actor_type("myself", relationship="friend")

Configuration Methods
~~~~~~~~~~~~~~~~~~~~~

.. py:method:: with_oauth(client_id, client_secret, scope="", auth_uri="", token_uri="", **kwargs)

    Configure OAuth authentication.

    :param client_id: OAuth client ID
    :param client_secret: OAuth client secret
    :param scope: OAuth scope (optional)
    :param auth_uri: Authorization URI (optional)
    :param token_uri: Token URI (optional)
    :param kwargs: Additional OAuth parameters
    :return: ActingWebApp instance for chaining

.. py:method:: with_web_ui(enable=True)

    Enable or disable the web UI.

    :param enable: Whether to enable web UI
    :return: ActingWebApp instance for chaining

.. py:method:: with_devtest(enable=True)

    Enable or disable development/testing endpoints.

    :param enable: Whether to enable devtest endpoints
    :return: ActingWebApp instance for chaining

.. py:method:: with_bot(token="", email="", secret="", admin_room="")

    Configure bot integration.

    :param token: Bot token
    :param email: Bot email
    :param secret: Bot secret
    :param admin_room: Admin room ID
    :return: ActingWebApp instance for chaining

ActorInterface
--------------

Clean interface for working with actors:

.. code-block:: python

    # Create actor
    actor = ActorInterface.create(creator="user@example.com", config=config)

    # Access properties
    actor.properties.email = "user@example.com"
    actor.properties["settings"] = {"theme": "dark"}

    # Manage trust relationships
    peer = actor.trust.create_relationship(
        peer_url="https://peer.example.com/actor123",
        relationship="friend"
    )

    # Handle subscriptions
    actor.subscriptions.subscribe_to_peer(
        peer_id="peer123",
        target="properties"
    )

    # Notify subscribers
    actor.subscriptions.notify_subscribers(
        target="properties",
        data={"status": "active"}
    )

Class Methods
~~~~~~~~~~~~~

.. py:classmethod:: create(creator, config, actor_id=None, passphrase=None, delete_existing=False)

    Create a new actor.

    :param creator: Creator identifier (usually email)
    :param config: ActingWeb Config object
    :param actor_id: Optional custom actor ID
    :param passphrase: Optional custom passphrase
    :param delete_existing: Whether to delete existing actor with same creator
    :return: New ActorInterface instance

.. py:classmethod:: get_by_id(actor_id, config)

    Get an existing actor by ID.

    :param actor_id: Actor ID
    :param config: ActingWeb Config object
    :return: ActorInterface instance or None if not found

.. py:classmethod:: get_by_creator(creator, config)

    Get an existing actor by creator.

    :param creator: Creator identifier
    :param config: ActingWeb Config object
    :return: ActorInterface instance or None if not found

Properties
~~~~~~~~~~

.. py:attribute:: id

    Actor ID (read-only)

.. py:attribute:: creator

    Actor creator (read-only)

.. py:attribute:: url

    Actor URL (read-only)

.. py:attribute:: properties

    PropertyStore instance for property management

.. py:attribute:: property_lists

    PropertyListStore instance for list property management

.. py:attribute:: trust

    TrustManager instance for trust relationship management

.. py:attribute:: subscriptions

    SubscriptionManager instance for subscription management

PropertyStore
-------------

Dictionary-like interface for actor properties:

.. code-block:: python

    # Set properties
    actor.properties.email = "user@example.com"
    actor.properties["config"] = {"theme": "dark"}

    # Get properties
    email = actor.properties.email
    config = actor.properties.get("config", {})

    # Check existence
    if "email" in actor.properties:
        print("Email is set")

    # Iterate
    for key, value in actor.properties.items():
        print(f"{key}: {value}")

Methods
~~~~~~~

.. py:method:: get(key, default=None)

    Get property value with default.

    :param key: Property key
    :param default: Default value if property doesn't exist
    :return: Property value or default

.. py:method:: set(key, value)

    Set property value.

    :param key: Property key
    :param value: Property value

.. py:method:: delete(key)

    Delete property.

    :param key: Property key
    :return: True if property existed and was deleted

.. py:method:: update(other)

    Update properties from dictionary.

    :param other: Dictionary of properties to update

.. py:method:: to_dict()

    Convert to dictionary.

    :return: Dictionary representation of all properties

PropertyListStore
-----------------

Specialized interface for managing list properties that can grow beyond DynamoDB's 400KB item limit. List properties are stored as individual items with metadata, providing efficient operations on large lists.

.. code-block:: python

    # Access list properties through actor interface
    notes_list = actor.property_lists.notes
    
    # Add items to list
    notes_list.append("First note")
    notes_list.append({"title": "Meeting", "content": "Team sync at 2pm"})
    
    # Access items by index
    first_note = notes_list[0]
    second_note = notes_list[1]
    
    # Get list length
    count = len(notes_list)
    
    # Iterate through items
    for note in notes_list:
        print(note)
    
    # Convert to regular Python list
    all_notes = notes_list.to_list()
    
    # Set metadata for UI and LLM context
    notes_list.set_description("User's personal notes and reminders")
    notes_list.set_explanation("This list contains user-generated notes, meeting reminders, and task items for personal organization")
    
    # Get metadata
    description = notes_list.get_description()
    explanation = notes_list.get_explanation()

Creating List Properties
~~~~~~~~~~~~~~~~~~~~~~~~

List properties can be created through the web interface, API, or programmatically:

**Web Interface (Form-based)**:

.. code-block:: html

    <form method="POST" action="/actor_id/www/properties">
        <input name="property_name" value="shopping_list">
        <input name="property_type" value="list">
        <input name="description" value="Weekly grocery shopping list">
        <input name="explanation" value="Items to buy during weekly grocery trips, organized by store sections">
        <input type="submit" value="Create List">
    </form>

**API (JSON-based)**:

.. code-block:: python

    import requests
    
    # Create list property with metadata via POST to /properties
    response = requests.post(f"https://domain.com/{actor_id}/properties", json={
        "shopping_list": {
            "_type": "list",
            "description": "Weekly grocery shopping list",
            "explanation": "Items to buy during weekly grocery trips, organized by store sections"
        }
    })

**Programmatically**:

.. code-block:: python

    # Access creates the list automatically
    shopping_list = actor.property_lists.shopping_list
    
    # Set metadata
    shopping_list.set_description("Weekly grocery shopping list")
    shopping_list.set_explanation("Items to buy during weekly grocery trips")
    
    # Add initial items
    shopping_list.append("Milk")
    shopping_list.append("Bread")
    shopping_list.extend(["Eggs", "Cheese", "Apples"])

List Operations
~~~~~~~~~~~~~~~

.. py:method:: append(item)

    Add an item to the end of the list.
    
    :param item: Item to add (any JSON-serializable type)

.. py:method:: extend(items)

    Add multiple items to the end of the list.
    
    :param items: Iterable of items to add

.. py:method:: insert(index, item)

    Insert an item at the specified index.
    
    :param index: Index position for insertion
    :param item: Item to insert

.. py:method:: pop(index=-1)

    Remove and return item at index (default last).
    
    :param index: Index of item to remove (optional, defaults to -1)
    :return: Removed item

.. py:method:: remove(value)

    Remove first occurrence of value.
    
    :param value: Value to remove from list

.. py:method:: clear()

    Remove all items from the list.

.. py:method:: delete()
   :no-index:

    Delete the entire list including metadata.

.. py:method:: to_list()

    Load entire list into memory as a Python list.
    
    :return: Python list containing all items

.. py:method:: slice(start, end)

    Load a range of items efficiently.
    
    :param start: Start index
    :param end: End index
    :return: List of items in the specified range

.. py:method:: index(value, start=0, stop=None)

    Return index of first occurrence of value.
    
    :param value: Value to search for
    :param start: Start search position (optional)
    :param stop: Stop search position (optional)
    :return: Index of value

.. py:method:: count(value)

    Return number of occurrences of value.
    
    :param value: Value to count
    :return: Number of occurrences

Metadata Operations
~~~~~~~~~~~~~~~~~~~

Each list property includes metadata fields for UI display and LLM context:

.. py:method:: set_description(description)

    Set the description field for UI info about the list.
    
    :param description: Human-readable description for UI display

.. py:method:: get_description()

    Get the description field.
    
    :return: Description string

.. py:method:: set_explanation(explanation)

    Set the explanation field for LLM context.
    
    :param explanation: Detailed explanation for LLM understanding

.. py:method:: get_explanation()

    Get the explanation field.
    
    :return: Explanation string

List Properties in Web Interface
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

List properties have specialized web interface support:

- **Properties Page**: Lists show "[List with N items]" summary
- **Individual List Page**: Shows all items with add/edit/delete controls
- **Metadata Editing**: Form fields for updating description and explanation
- **Item Management**: Add, update, delete individual items via web forms

The web interface supports these operations:

.. code-block:: python

    # Add item via POST to /<actor_id>/www/properties/<list_name>/items
    # POST data: action=add&item_value={"new": "item"}
    
    # Update item via POST 
    # POST data: action=update&item_index=0&item_value={"updated": "item"}
    
    # Delete item via POST
    # POST data: action=delete&item_index=0
    
    # Update metadata via POST to /<actor_id>/www/properties/<list_name>/metadata
    # POST data: action=update&description=new_desc&explanation=new_explanation

Key Features and Benefits
~~~~~~~~~~~~~~~~~~~~~~~~~

**Scalability**:
- Bypasses DynamoDB's 400KB item limit by storing items individually
- Efficient operations on large lists without loading everything into memory
- Lazy-loading iterator minimizes database queries

**Type Safety**:
- Automatic JSON serialization/deserialization for complex objects
- Graceful handling of serialization errors
- Consistent data types across operations

**Metadata Support**:
- Description field for UI display and user understanding
- Explanation field for LLM context and automated processing
- Metadata persisted independently of list items

**Web Integration**:
- Specialized web interface for list management
- Form-based item addition, editing, and deletion
- Metadata editing through web forms

**API Compatibility**:
- Standard Python list interface (``[index]``, ``len()``, ``iter()``)
- RESTful API support through properties handlers
- JSON-RPC method support for automated clients

Use Cases
~~~~~~~~~

**User Content Lists**:

.. code-block:: python

    # Blog posts, notes, bookmarks
    blog_posts = actor.property_lists.blog_posts
    blog_posts.set_description("Published blog articles")
    blog_posts.set_explanation("User-authored blog posts with titles, content, tags, and publication dates")
    
    blog_posts.append({
        "title": "Getting Started with ActingWeb",
        "content": "ActingWeb is a powerful framework...",
        "tags": ["tutorial", "web", "python"],
        "published_at": "2024-01-15T10:00:00Z"
    })

**Configuration Collections**:

.. code-block:: python

    # API endpoints, webhook URLs, integration settings
    webhooks = actor.property_lists.webhook_endpoints
    webhooks.set_description("Configured webhook endpoints")
    webhooks.set_explanation("External URLs that receive notifications when actor data changes")
    
    webhooks.append({
        "url": "https://api.example.com/webhook",
        "events": ["property_change", "trust_approved"],
        "active": True
    })

**Activity Logs**:

.. code-block:: python

    # Audit trails, event logs, user actions
    activity_log = actor.property_lists.activity_log
    activity_log.set_description("User activity history")
    activity_log.set_explanation("Chronological log of user actions, API calls, and system events for audit and debugging")
    
    activity_log.append({
        "timestamp": "2024-01-15T14:30:00Z",
        "action": "property_updated",
        "details": {"property": "email", "old_value": "old@example.com", "new_value": "new@example.com"}
    })

**Data Collections**:

.. code-block:: python

    # Sensor readings, measurements, collected data
    sensor_data = actor.property_lists.temperature_readings
    sensor_data.set_description("Temperature sensor measurements")
    sensor_data.set_explanation("Historical temperature readings from IoT sensors with timestamps and location data")
    
    sensor_data.append({
        "timestamp": "2024-01-15T12:00:00Z",
        "temperature": 22.5,
        "sensor_id": "temp_001",
        "location": "living_room"
    })

Property Lists vs Regular Properties
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Use Regular Properties When**:
- Data is simple key-value pairs
- Values are relatively small (under 50KB)
- You need direct REST API access to individual fields
- Data structure is flat and doesn't grow significantly

**Use Property Lists When**:
- You need to store ordered collections of items
- Data might grow beyond DynamoDB limits (400KB)
- You need list operations (append, insert, remove)
- Items are complex objects with multiple fields
- You need efficient iteration over large datasets

**Migration Example**:

.. code-block:: python

    # Old approach (limited by 400KB, inefficient for large data)
    actor.properties.user_notes = json.dumps([
        "Note 1", "Note 2", "Note 3"  # This grows and hits limits
    ])
    
    # New approach (scalable, efficient)
    notes_list = actor.property_lists.user_notes
    notes_list.set_description("User's personal notes")
    for note in ["Note 1", "Note 2", "Note 3"]:
        notes_list.append(note)

REST API for List Properties
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

List properties have specialized REST API endpoints that extend the standard properties API:

**GET Operations**:

.. code-block:: bash

    # Get all items in a list
    GET /<actor_id>/properties/shopping_list
    # Returns: ["Milk", "Bread", "Eggs"]
    
    # Get specific item by index
    GET /<actor_id>/properties/shopping_list?index=0
    # Returns: "Milk"
    
    # Get item by index (out of range returns 404)
    GET /<actor_id>/properties/shopping_list?index=10
    # Returns: 404 Not Found

**POST Operations - Bulk Updates**:

.. code-block:: bash

    # Bulk update specific items using items array
    POST /<actor_id>/properties/shopping_list
    Content-Type: application/json
    
    {
        "shopping_list": {
            "items": [
                {"index": 0, "name": "Organic Milk", "category": "dairy", "price": 4.99},
                {"index": 2, "name": "Free-range Eggs", "category": "dairy", "quantity": 12},
                {"index": 5, "name": "Apples", "category": "produce", "variety": "Honeycrisp"}
            ]
        }
    }

**POST Operations - Item Deletion**:

.. code-block:: bash

    # Delete specific items using empty item data
    POST /<actor_id>/properties/shopping_list
    Content-Type: application/json
    
    {
        "shopping_list": {
            "items": [
                {"index": 1},   # Delete item at index 1 (empty item = delete)
                {"index": 3}    # Delete item at index 3
            ]
        }
    }

**POST Operations - Mixed Updates**:

.. code-block:: bash

    # Combine updates and deletions in one request
    POST /<actor_id>/properties/shopping_list
    Content-Type: application/json
    
    {
        "shopping_list": {
            "items": [
                {"index": 0, "name": "Updated item", "category": "other"},  # Update
                {"index": 1},                                                # Delete
                {"index": 3, "name": "New item", "urgent": true}            # Add/Update
            ]
        }
    }

**DELETE Operations**:

.. code-block:: bash

    # Delete entire list property (including metadata)
    DELETE /<actor_id>/properties/shopping_list
    # Returns: 204 No Content

**Response Formats**:

.. code-block:: python

    # GET responses return JSON arrays or individual items
    ["Milk", "Bread", "Eggs"]  # All items
    "Milk"                     # Single item
    
    # POST bulk update responses
    {
        "shopping_list": "[Bulk update: 2 items updated, 1 items deleted]"
    }
    
    # Error responses for GET operations
    {"error": "List item not found"}           # 404 for invalid index
    {"error": "Property 'x' is not a list"}   # 400 for non-list property
    
    # Error responses for POST bulk updates
    {"error": "Missing 'index' field in item at position 0"}                           # 400
    {"error": "Invalid index type in item at position 1: expected integer, got str"}   # 400
    {"error": "Invalid index value in item at position 2: -1 (must be >= 0)"}         # 400
    {"error": "Invalid item at position 0: must be a dictionary, got str"}             # 400
    {"error": "Invalid 'items' field for property 'list': expected list, got str"}     # 400

**Error Handling and Validation**:

The bulk update API performs comprehensive validation and provides detailed error messages:

.. code-block:: python

    # Required field validation
    {
        "list_name": {
            "items": [
                {"name": "Missing index"}  # ERROR: Missing 'index' field
            ]
        }
    }
    # Returns: 400 "Missing 'index' field in item at position 0"
    
    # Type validation
    {
        "list_name": {
            "items": [
                {"index": "0", "name": "String index"}  # ERROR: Wrong type
            ]
        }
    }
    # Returns: 400 "Invalid index type in item at position 0: expected integer, got str"
    
    # Value validation
    {
        "list_name": {
            "items": [
                {"index": -1, "name": "Negative index"}  # ERROR: Negative value
            ]
        }
    }
    # Returns: 400 "Invalid index value in item at position 0: -1 (must be >= 0)"
    
    # Structure validation
    {
        "list_name": {
            "items": [
                "not_a_dict"  # ERROR: Items must be dictionaries
            ]
        }
    }
    # Returns: 400 "Invalid item at position 0: must be a dictionary, got str"
    
    # Array validation
    {
        "list_name": {
            "items": "not_an_array"  # ERROR: items must be array
        }
    }
    # Returns: 400 "Invalid 'items' field for property 'list_name': expected list, got str"

**Validation Rules**:

1. **items** field must be a list/array
2. Each item in the array must be a dictionary/object
3. Each item must have an **index** field
4. **index** must be an integer (not string, float, etc.)
5. **index** must be non-negative (>= 0)
6. All other fields in the item become the stored data

**Error Behavior**:

- Validation errors return **HTTP 400 Bad Request**
- Error messages include the problematic item's position in the array
- Operations are **atomic** - if any item fails validation, no changes are made
- Delete operations that target non-existent indices are logged as warnings but don't fail the operation

**Hook Integration**:

Property hooks work seamlessly with the new list API operations:

.. code-block:: python

    @app.property_hook("shopping_list")
    def validate_shopping_list(actor, operation, value, path):
        if operation == "get":
            # Filter items based on user permissions
            if len(path) > 1:  # Specific item access
                item_index = int(path[1])
                return value if item_index < 10 else None  # Limit access
            return value  # Allow access to all items
            
        elif operation == "post":
            # Validate bulk updates
            if isinstance(value, list):
                # Validate each item in bulk update
                for item in value:
                    if not isinstance(item, str) or len(item) > 100:
                        return None  # Reject invalid items
            return value
            
        elif operation == "delete":
            # Allow deletion only by owner
            return value if actor.is_owner() else None
            
        return value

**API Usage Examples**:

.. code-block:: python

    import requests
    
    # Get all items
    response = requests.get(f"https://domain.com/{actor_id}/properties/notes")
    all_notes = response.json()
    
    # Get specific item
    response = requests.get(f"https://domain.com/{actor_id}/properties/notes?index=0")
    first_note = response.json()
    
    # Bulk update items
    response = requests.post(f"https://domain.com/{actor_id}/properties", json={
        "notes": {
            "items": [
                {"index": 0, "title": "Updated Note", "content": "New content", "tags": ["work", "important"]},
                {"index": 2, "title": "Another Note", "content": "More content", "priority": "high"},
                {"index": 1}  # Delete item at index 1
            ]
        }
    })
    
    # Delete entire list
    response = requests.delete(f"https://domain.com/{actor_id}/properties/notes")

**Complex Object Examples**:

The items array supports complex nested objects with any structure:

.. code-block:: python

    # Example: Update a complex configuration list
    response = requests.post(f"https://domain.com/{actor_id}/properties", json={
        "server_configs": {
            "items": [
                {
                    "index": 0,
                    "var1": 3,
                    "var2": "some text",
                    "var3": ["item1", "item2", "item3"],
                    "var4": {
                        "nested_key": "nested_value",
                        "another_nested": {
                            "deep_key": "deep_value"
                        }
                    },
                    "var5": "some text"
                },
                {
                    "index": 1,
                    "server_name": "production-db",
                    "config": {
                        "host": "db.example.com",
                        "port": 5432,
                        "ssl": True,
                        "pools": {
                            "min": 5,
                            "max": 20
                        }
                    },
                    "tags": ["production", "database", "critical"],
                    "metadata": {
                        "created_by": "admin",
                        "created_at": "2024-01-15T10:00:00Z",
                        "version": "1.2.3"
                    }
                },
                {"index": 2}  # Delete item at index 2
            ]
        }
    })

TrustManager
------------

Simplified trust relationship management:

.. code-block:: python

    # Create relationship
    relationship = actor.trust.create_relationship(
        peer_url="https://peer.example.com/actor123",
        relationship="friend"
    )

    # List relationships
    for rel in actor.trust.relationships:
        print(f"Trust with {rel.peer_id}: {rel.relationship}")

    # Find specific relationship
    friend = actor.trust.find_relationship(relationship="friend")

    # Approve relationship
    actor.trust.approve_relationship(peer_id="peer123")

    # Check if peer is trusted
    if actor.trust.is_trusted_peer("peer123"):
        print("Peer is trusted")

Properties
~~~~~~~~~~

.. py:attribute:: relationships

    List of all trust relationships

.. py:attribute:: active_relationships

    List of active (approved and verified) relationships

.. py:attribute:: pending_relationships

    List of pending relationships

Methods
~~~~~~~

.. py:method:: create_relationship(peer_url, relationship="friend", secret="", description="")

    Create a new trust relationship with another actor.

    :param peer_url: URL of the peer actor
    :param relationship: Type of relationship (friend, partner, etc.)
    :param secret: Shared secret (auto-generated if not provided)
    :param description: Description of the relationship
    :return: TrustRelationship instance or None if failed

.. py:method:: get_relationship(peer_id)

    Get relationship with specific peer.

    :param peer_id: Peer actor ID
    :return: TrustRelationship instance or None if not found

.. py:method:: approve_relationship(peer_id)

    Approve a trust relationship.

    :param peer_id: Peer actor ID
    :return: True if successful

.. py:method:: delete_relationship(peer_id)

    Delete a trust relationship.

    :param peer_id: Peer actor ID
    :return: True if successful

.. py:method:: is_trusted_peer(peer_id)

    Check if peer is trusted (has active relationship).

    :param peer_id: Peer actor ID
    :return: True if peer is trusted

Trust Relationship Permission Management
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For applications using the unified access control system, you can manage per-relationship permission overrides:

.. code-block:: python

    from actingweb.trust_permissions import get_trust_permission_store, create_permission_override

    # Grant custom permissions to a specific relationship
    def customize_peer_permissions(actor_id: str, peer_id: str):
        permission_store = get_trust_permission_store(config)
        
        # Create permission override
        permissions = create_permission_override(
            actor_id=actor_id,
            peer_id=peer_id,
            trust_type="friend",
            permission_updates={
                "properties": {
                    "patterns": ["public/*", "notes/*"],
                    "operations": ["read", "write"],
                    "excluded_patterns": ["private/*"]
                },
                "methods": {
                    "allowed": ["get_*", "create_*"],
                    "denied": ["delete_*", "admin_*"]
                },
                "notes": "Enhanced permissions for trusted partner"
            }
        )
        
        # Store the override
        permission_store.store_permissions(permissions)

    # Check existing permissions
    def check_peer_permissions(actor_id: str, peer_id: str):
        permission_store = get_trust_permission_store(config)
        permissions = permission_store.get_permissions(actor_id, peer_id)
        
        if permissions:
            print(f"Custom permissions exist for {peer_id}")
            print(f"Properties: {permissions.properties}")
            print(f"Methods: {permissions.methods}")
        else:
            print(f"Using trust type defaults for {peer_id}")

    # Remove custom permissions
    def revert_to_defaults(actor_id: str, peer_id: str):
        permission_store = get_trust_permission_store(config)
        success = permission_store.delete_permissions(actor_id, peer_id)
        if success:
            print(f"Reverted {peer_id} to trust type defaults")

**REST API Access**

The trust API also supports permission management through HTTP endpoints:

* ``GET /{actor_id}/trust/{relationship}/{peer_id}?permissions=true`` - Include permissions in trust response
* ``PUT /{actor_id}/trust/{relationship}/{peer_id}/permissions`` - Set custom permissions
* ``GET /{actor_id}/trust/{relationship}/{peer_id}/permissions`` - Get custom permissions
* ``DELETE /{actor_id}/trust/{relationship}/{peer_id}/permissions`` - Remove custom permissions

SubscriptionManager
-------------------

Easy subscription handling:

.. code-block:: python

    # Subscribe to peer
    subscription_url = actor.subscriptions.subscribe_to_peer(
        peer_id="peer123",
        target="properties",
        granularity="high"
    )

    # List subscriptions
    for sub in actor.subscriptions.all_subscriptions:
        print(f"Subscription to {sub.peer_id}: {sub.target}")

    # Notify subscribers
    actor.subscriptions.notify_subscribers(
        target="properties",
        data={"status": "active"}
    )

    # Unsubscribe
    actor.subscriptions.unsubscribe(
        peer_id="peer123",
        subscription_id="sub123"
    )

Properties
~~~~~~~~~~

.. py:attribute:: all_subscriptions

    List of all subscriptions (both inbound and outbound)

.. py:attribute:: outbound_subscriptions

    List of subscriptions to other actors

.. py:attribute:: inbound_subscriptions

    List of subscriptions from other actors

Methods
~~~~~~~

.. py:method:: subscribe_to_peer(peer_id, target, subtarget="", resource="", granularity="high")

    Subscribe to another actor's data.

    :param peer_id: Peer actor ID
    :param target: Target to subscribe to
    :param subtarget: Subtarget (optional)
    :param resource: Resource (optional)
    :param granularity: Notification granularity (high, low, none)
    :return: Subscription URL if successful, None otherwise

.. py:method:: unsubscribe(peer_id, subscription_id)

    Unsubscribe from a peer's data.

    :param peer_id: Peer actor ID
    :param subscription_id: Subscription ID
    :return: True if successful

.. py:method:: notify_subscribers(target, data, subtarget="", resource="")

    Notify all subscribers of changes to the specified target.

    :param target: Target that changed
    :param data: Change data
    :param subtarget: Subtarget (optional)
    :param resource: Resource (optional)

.. py:method:: has_subscribers_for(target, subtarget="", resource="")

    Check if there are any subscribers for the given target.

    :param target: Target to check
    :param subtarget: Subtarget (optional)
    :param resource: Resource (optional)
    :return: True if there are subscribers

Hook System
-----------

Property Hooks
--------------

Handle property operations:

.. code-block:: python

    @app.property_hook("email")
    def handle_email_property(actor, operation, value, path):
        if operation == "get":
            return value if actor.is_owner() else None
        elif operation == "put":
            return value.lower() if "@" in value else None
        return value

    # Hook specific operations
    @app.property_hook("settings", operations=["put", "post"])
    def handle_settings_property(actor, operation, value, path):
        if isinstance(value, str):
            import json
            try:
                return json.loads(value)
            except:
                return None
        return value

    # Wildcard hook for access control
    @app.property_hook("*")
    def handle_all_properties(actor, operation, value, path):
        if not path:
            return value
            
        property_name = path[0]
        
        # Hidden properties (not visible in web interface or API)
        if property_name in ["email", "auth_token"] and operation == "get":
            return None
            
        # Read-only properties (visible but not editable)
        if property_name in ["created_at", "actor_type"] and operation in ["put", "post"]:
            return None
            
        # Protected from deletion
        if property_name in ["email", "created_at"] and operation == "delete":
            return None
            
        return value

Hook Function Signature
~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: property_hook_function(actor, operation, value, path)

    Property hook function signature.

    :param actor: ActorInterface instance
    :param operation: Operation type ("get", "put", "post", "delete")
    :param value: Property value
    :param path: Property path as list
    :return: Transformed value or None to reject operation

Property Hook Patterns and Web Interface Effects
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Property hooks directly control how properties appear and behave in the web interface:

**Hidden Properties**
    When a property hook returns ``None`` for GET operations, the property is completely hidden:
    
    - Not displayed in properties list
    - Returns 404 when accessed directly via ``/<actor_id>/www/properties/name``
    - Not accessible via API endpoints

**Read-Only Properties**
    When a property hook returns ``None`` for PUT/POST operations, the property becomes read-only:
    
    - Shows "Read-only" badge in properties list
    - Edit/Delete buttons replaced with "View Only" button
    - Individual property page shows value in styled display box
    - Edit form and delete functionality disabled
    - Returns 403 when modification is attempted

**Protected from Deletion**
    When a property hook returns ``None`` for DELETE operations:
    
    - Delete button is disabled or hidden
    - Returns 403 when deletion is attempted
    - Property remains visible and may be editable

**Common Patterns**
    
.. code-block:: python

    # System properties: visible but not editable or deletable
    @app.property_hook("*")
    def protect_system_properties(actor, operation, value, path):
        property_name = path[0] if path else ""
        
        if property_name.startswith("system_") or property_name in ["created_at", "actor_type"]:
            if operation in ["put", "post", "delete"]:
                return None  # Read-only
        
        return value

    # Sensitive properties: completely hidden
    @app.property_hook("*") 
    def hide_sensitive_properties(actor, operation, value, path):
        property_name = path[0] if path else ""
        
        if property_name in ["password", "auth_token", "private_key"]:
            if operation == "get":
                return None  # Hidden
                
        return value

    # User properties: owner can edit, others can view
    @app.property_hook("*")
    def user_property_access(actor, operation, value, path):
        property_name = path[0] if path else ""
        
        if property_name.startswith("user_"):
            if operation in ["put", "post", "delete"] and not actor.is_owner():
                return None  # Read-only for non-owners
                
        return value

Callback Hooks
--------------

Handle callback requests at both application and actor levels:

.. code-block:: python

    # Application-level callbacks (no actor context)
    @app.app_callback_hook("bot")
    def handle_bot_callback(data):
        if data.get("method") == "POST":
            # Process bot webhook (no actor context)
            return True
        return False

    # Actor-level callbacks (with actor context)
    @app.callback_hook("ping")
    def handle_ping_callback(actor, name, data):
        if data.get("method") == "GET":
            return {"status": "pong", "actor_id": actor.id}
        return False

    @app.callback_hook("status")
    def handle_status_callback(actor, name, data):
        return {"status": "active", "actor_id": actor.id}

Application-Level vs Actor-Level Callbacks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Application-level callbacks** (``@app.app_callback_hook``):
- Used for endpoints like ``/bot``, ``/oauth``
- No actor context - these are application-wide endpoints
- Function signature: ``def callback(data) -> bool``

**Actor-level callbacks** (``@app.callback_hook``):
- Used for endpoints like ``/<actor_id>/callbacks/<name>``
- Have actor context - these are specific to individual actors
- Function signature: ``def callback(actor, name, data) -> bool``

Hook Function Signatures
~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: app_callback_hook_function(data)

    Application-level callback hook function signature.

    :param data: Request data including method and body
    :return: True if processed, False otherwise, or dict for response data

.. py:function:: callback_hook_function(actor, name, data)

    Actor-level callback hook function signature.

    :param actor: ActorInterface instance
    :param name: Callback name
    :param data: Request data including method and body
    :return: True if processed, False otherwise, or dict for response data

Method Hooks
------------

Handle RPC-style method calls with JSON-RPC support:

.. code-block:: python

    # Simple method hook
    @app.method_hook("calculate")
    def handle_calculate(actor, method_name, data):
        a = data.get("a", 0)
        b = data.get("b", 0)
        operation = data.get("operation", "add")
        
        if operation == "add":
            result = a + b
        elif operation == "multiply":
            result = a * b
        else:
            return None  # Method not supported
            
        return {"result": result}

    # JSON-RPC method hook
    @app.method_hook("greet")
    def handle_greet(actor, method_name, data):
        name = data.get("name", "World")
        return {"greeting": f"Hello, {name}!"}

Method Hook Function Signature
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: method_hook_function(actor, method_name, data)

    Method hook function signature.

    :param actor: ActorInterface instance
    :param method_name: Method name being called
    :param data: Method parameters (for JSON-RPC, this is the "params" field)
    :return: Method result (will be wrapped in JSON-RPC response if applicable)

Action Hooks
------------

Handle trigger-based actions that execute external events:

.. code-block:: python

    # Action hook for notifications
    @app.action_hook("send_notification")
    def handle_send_notification(actor, action_name, data):
        message = data.get("message", "")
        recipient = data.get("recipient", "")
        
        # Execute external action (e.g., send email, trigger webhook)
        success = send_notification_email(recipient, message)
        
        return {
            "status": "sent" if success else "failed",
            "timestamp": datetime.now().isoformat()
        }

    # Action hook for device control
    @app.action_hook("toggle_light")
    def handle_toggle_light(actor, action_name, data):
        device_id = data.get("device_id")
        state = data.get("state", "on")
        
        # Control physical device
        result = control_iot_device(device_id, state)
        
        return {
            "device_id": device_id,
            "state": state,
            "success": result
        }

Action Hook Function Signature
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: action_hook_function(actor, action_name, data)

    Action hook function signature.

    :param actor: ActorInterface instance
    :param action_name: Action name being executed
    :param data: Action parameters
    :return: Action result (status information, execution results, etc.)

Subscription Hooks
------------------

Handle subscription callbacks:

.. code-block:: python

    @app.subscription_hook
    def handle_subscription_callback(actor, subscription, peer_id, data):
        print(f"Received data from {peer_id}: {data}")
        
        # Process the subscription data
        if subscription.get("target") == "properties":
            # Handle property changes from peer
            pass
            
        return True

Hook Function Signature
~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: subscription_hook_function(actor, subscription, peer_id, data)

    Subscription hook function signature.

    :param actor: ActorInterface instance
    :param subscription: Subscription information dict
    :param peer_id: Peer actor ID
    :param data: Subscription data
    :return: True if processed, False otherwise

Lifecycle Hooks
---------------

Handle actor lifecycle events:

.. code-block:: python

    @app.lifecycle_hook("actor_created")
    def on_actor_created(actor, **kwargs):
        # Initialize new actor
        actor.properties.created_at = str(datetime.now())

    @app.lifecycle_hook("actor_deleted")
    def on_actor_deleted(actor, **kwargs):
        # Cleanup before deletion
        print(f"Actor {actor.id} is being deleted")

    @app.lifecycle_hook("oauth_success")
    def on_oauth_success(actor, **kwargs):
        token = kwargs.get("token")
        if token:
            actor.properties.oauth_token = token

Available Lifecycle Events
~~~~~~~~~~~~~~~~~~~~~~~~~~

- ``actor_created``: Called when a new actor is created
- ``actor_deleted``: Called when an actor is deleted
- ``oauth_success``: Called when OAuth authentication succeeds
- ``trust_approved``: Called when a trust relationship is approved
- ``trust_deleted``: Called when a trust relationship is deleted

Hook Function Signature
~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: lifecycle_hook_function(actor, **kwargs)

    Lifecycle hook function signature.

    :param actor: ActorInterface instance
    :param kwargs: Event-specific parameters
    :return: Event-specific return value

Migration from OnAWBase (v3.1 Breaking Change)
-------------------------------------------------

.. warning::
   **Breaking Change in v3.1**: The legacy ``OnAWBase`` interface has been completely removed.
   Applications using the old interface must migrate to the modern ``ActingWebApp`` interface.
   
   See :doc:`migration-v3.1` for detailed migration instructions.

Before (OnAWBase - NO LONGER SUPPORTED)
---------------------------------------

.. code-block:: python

    # This code NO LONGER WORKS in v3.1+
    class OnAWDemo(on_aw.OnAWBase):
        def get_properties(self, path: list[str], data: dict) -> Optional[dict]:
            if not path:
                for k, v in data.copy().items():
                    if k in PROP_HIDE:
                        del data[k]
            elif len(path) > 0 and path[0] in PROP_HIDE:
                return None
            return data
        
        def put_properties(self, path: list[str], old: dict, new: Union[dict, str]) -> Optional[dict | str]:
            if not path:
                return None
            elif len(path) > 0 and path[0] in PROP_PROTECT:
                return None
            return new

After (Modern Interface - REQUIRED in v3.1+)
--------------------------------------------

.. code-block:: python

    @app.property_hook("email")
    def handle_email_property(actor, operation, value, path):
        if operation == "get":
            return None if not actor.is_owner() else value
        elif operation == "put":
            return value.lower() if "@" in value else None
        return value

Benefits
--------

1. **Reduced Boilerplate**: No more manual route definitions or complex handler setup
2. **Better Organization**: Hooks are focused on specific functionality
3. **Improved Readability**: Code is easier to understand and maintain
4. **Type Safety**: Better IDE support and error detection
5. **Flexibility**: Easy to add new hooks without modifying core classes
6. **Testing**: Hooks can be tested independently

Version 3.1 Breaking Changes
----------------------------

.. warning::
   **ActingWeb v3.1 removes backward compatibility** with the legacy ``OnAWBase`` interface.
   
   This was necessary to:
   
   - Eliminate dual interface maintenance complexity
   - Improve runtime performance by removing bridge layer overhead
   - Provide better type safety and developer experience
   - Reduce potential for interface synchronization bugs

**Migration Required**
   All applications using the legacy ``OnAWBase`` interface must migrate to the modern 
   ``ActingWebApp`` interface. See :doc:`migration-v3.1` for complete migration instructions.

Advanced Usage
--------------

Accessing Core Components
-------------------------

If you need access to the underlying ActingWeb components:

.. code-block:: python

    # Access core actor
    core_actor = actor.core_actor

    # Access core property store
    core_properties = actor.properties.core_store

    # Access configuration
    config = app.get_config()

Custom Web Framework Integration
--------------------------------

You can extend the integration system for other web frameworks:

.. code-block:: python

    from actingweb.interface.integrations import FlaskIntegration
    
    class FastAPIIntegration:
        def __init__(self, aw_app, fastapi_app):
            self.aw_app = aw_app
            self.fastapi_app = fastapi_app
            
        def setup_routes(self):
            # Implement FastAPI route setup
            pass

Error Handling
--------------

The new interface provides better error handling:

.. code-block:: python

    try:
        actor = ActorInterface.create(creator="user@example.com", config=config)
    except RuntimeError as e:
        print(f"Failed to create actor: {e}")
        
    # Hook error handling
    @app.property_hook("email")
    def handle_email_property(actor, operation, value, path):
        try:
            if operation == "put" and "@" not in value:
                return None  # Reject invalid email
            return value.lower() if operation == "put" else value
        except Exception as e:
            # Log error and reject operation
            print(f"Error in email hook: {e}")
            return None

Global Data Storage with Attributes and Buckets
-----------------------------------------------

ActingWeb provides a flexible attribute and bucket system for storing global data that needs to be shared across actors or persisted at the application level. This is particularly useful for storing configuration data, client registrations, indexes, and other shared state.

Attributes API
--------------

The ``Attributes`` class provides a bucket-based storage system:

.. code-block:: python

    from actingweb import attribute
    
    # Create a bucket for a specific actor
    bucket = attribute.Attributes(
        actor_id="actor123", 
        bucket="user_preferences", 
        config=config
    )
    
    # Store data in the bucket
    bucket.set_attr(name="theme", data="dark")
    bucket.set_attr(name="language", data="en")
    bucket.set_attr(name="notifications", data={"email": True, "push": False})
    
    # Retrieve individual attributes
    theme_attr = bucket.get_attr(name="theme")
    if theme_attr and "data" in theme_attr:
        theme = theme_attr["data"]  # "dark"
    
    # Retrieve the entire bucket
    all_preferences = bucket.get_bucket()
    if all_preferences:
        for attr_name, attr_data in all_preferences.items():
            if attr_data and "data" in attr_data:
                print(f"{attr_name}: {attr_data['data']}")

Global Storage Pattern
----------------------

For global data that isn't associated with a specific actor, use a special global actor ID:

.. code-block:: python

    # Store global application configuration
    global_config = attribute.Attributes(
        actor_id="_global_config", 
        bucket="app_settings", 
        config=config
    )
    
    # Store application-wide settings
    global_config.set_attr(name="max_users", data=1000)
    global_config.set_attr(name="maintenance_mode", data=False)
    global_config.set_attr(name="api_keys", data={"service_a": "key123", "service_b": "key456"})
    
    # Create a global index (e.g., for client registrations)
    client_index = attribute.Attributes(
        actor_id="_mcp_global", 
        bucket="client_index", 
        config=config
    )
    
    # Store client_id -> actor_id mappings
    client_index.set_attr(name="client_abc123", data="actor_user456")
    client_index.set_attr(name="client_def789", data="actor_user789")

Attribute Data Structure
------------------------

Each attribute stored in the system has this structure:

.. code-block:: python

    {
        "data": <your_actual_data>,
        "timestamp": <optional_timestamp>
    }

When storing data, only provide the actual data - the attribute system handles the structure:

.. code-block:: python

    # Store simple data
    bucket.set_attr(name="username", data="john_doe")
    
    # Store complex data
    bucket.set_attr(name="user_profile", data={
        "name": "John Doe",
        "email": "john@example.com",
        "preferences": {"theme": "dark", "lang": "en"}
    })
    
    # Retrieve and extract data
    profile_attr = bucket.get_attr(name="user_profile")
    if profile_attr and "data" in profile_attr:
        profile = profile_attr["data"]  # The actual dictionary

Bucket Operations
-----------------

.. py:method:: set_attr(name, data, timestamp=None)

    Store an attribute in the bucket.

    :param name: Attribute name
    :param data: Data to store (any JSON-serializable type)
    :param timestamp: Optional timestamp (auto-generated if not provided)
    :return: True if successful

.. py:method:: get_attr(name)

    Retrieve a single attribute from the bucket.

    :param name: Attribute name
    :return: Attribute dictionary with "data" and "timestamp" keys, or None

.. py:method:: get_bucket()

    Retrieve all attributes in the bucket.

    :return: Dictionary mapping attribute names to attribute dictionaries

.. py:method:: delete_attr(name)

    Delete an attribute from the bucket.

    :param name: Attribute name
    :return: True if successful

.. py:method:: delete_bucket()

    Delete the entire bucket and all its attributes.

    :return: True if successful

Use Cases
---------

**Client Registry (OAuth2/MCP clients)**:

.. code-block:: python

    # Store client data per actor
    client_bucket = attribute.Attributes(
        actor_id=actor_id, 
        bucket="mcp_clients", 
        config=config
    )
    client_bucket.set_attr(name=client_id, data=client_data)
    
    # Global index for client lookup
    global_index = attribute.Attributes(
        actor_id="_mcp_global", 
        bucket="client_index", 
        config=config
    )
    global_index.set_attr(name=client_id, data=actor_id)

**Feature Flags and Configuration**:

.. code-block:: python

    # Application-wide feature flags
    features = attribute.Attributes(
        actor_id="_global_app", 
        bucket="feature_flags", 
        config=config
    )
    features.set_attr(name="new_ui_enabled", data=True)
    features.set_attr(name="beta_features", data=["advanced_search", "ai_chat"])

**User Session Management**:

.. code-block:: python

    # Per-actor session data
    sessions = attribute.Attributes(
        actor_id=actor_id, 
        bucket="sessions", 
        config=config
    )
    sessions.set_attr(name=session_id, data={
        "created_at": "2024-01-01T12:00:00Z",
        "last_activity": "2024-01-01T12:30:00Z",
        "user_agent": "Mozilla/5.0..."
    })

**Cache and Temporary Data**:

.. code-block:: python

    # Temporary cache data
    cache = attribute.Attributes(
        actor_id="_global_cache", 
        bucket="api_responses", 
        config=config
    )
    cache.set_attr(name=cache_key, data={
        "response": api_response_data,
        "expires_at": "2024-01-01T13:00:00Z"
    })

Private Data Storage
--------------------

The Attributes system is the preferred way to store sensitive or private data that should not be exposed through the public ``/properties`` API endpoint. Unlike regular actor properties, data stored in attribute buckets is completely isolated from the public API:

.. code-block:: python

    # WRONG: Storing sensitive data in regular properties (exposed via /properties API)
    actor.properties["_oauth_token"] = "sensitive_token"  # Exposed in API!
    
    # CORRECT: Using Attributes for private storage (not exposed)
    from actingweb import attribute
    
    private_bucket = attribute.Attributes(
        actor_id=actor.id, 
        bucket="oauth_tokens",  # Private bucket, not exposed
        config=config
    )
    private_bucket.set_attr(name="access_token", data="sensitive_token")

**Security Benefits**:

- **API Isolation**: Attribute data is never exposed through ``/<actor_id>/properties`` endpoints
- **Access Control**: Only application code with direct access to the Attributes API can read the data
- **Clean Separation**: Keeps sensitive data completely separate from user-visible properties

**Example: OAuth2 Token Storage**:

.. code-block:: python

    class OAuth2TokenManager:
        def __init__(self, config):
            self.config = config
            self.tokens_bucket = "oauth_tokens"
            self.refresh_bucket = "refresh_tokens"
        
        def store_access_token(self, actor_id: str, token_data: dict):
            """Store access token in private attributes."""
            tokens = attribute.Attributes(
                actor_id=actor_id, 
                bucket=self.tokens_bucket, 
                config=self.config
            )
            tokens.set_attr(name=token_data["token"], data=token_data)
        
        def get_access_token(self, actor_id: str, token: str) -> dict:
            """Retrieve access token from private attributes."""
            tokens = attribute.Attributes(
                actor_id=actor_id, 
                bucket=self.tokens_bucket, 
                config=self.config
            )
            token_attr = tokens.get_attr(name=token)
            return token_attr["data"] if token_attr and "data" in token_attr else None

Best Practices
--------------

1. **Use Descriptive Bucket Names**: Choose bucket names that clearly indicate their purpose.

2. **Consistent Global Actor IDs**: Use a consistent naming pattern for global actor IDs (e.g., ``_global_*``, ``_app_*``).

3. **Handle Missing Data**: Always check if attribute data exists before using it.

4. **Avoid Large Objects**: The attribute system is designed for metadata and configuration, not large binary data.

5. **Use JSON-Serializable Data**: Store only data that can be serialized to JSON.

6. **Private Data Security**: Always use Attributes (not regular properties) for sensitive data like tokens, passwords, and private keys.

Example: Complete Client Registry Implementation
------------------------------------------------

Here's a complete example of using the attribute system for a client registry:

.. code-block:: python

    class ClientRegistry:
        def __init__(self, config):
            self.config = config
        
        def register_client(self, actor_id: str, client_data: dict) -> None:
            """Register a client for a specific actor."""
            # Store client data in actor's bucket
            client_bucket = attribute.Attributes(
                actor_id=actor_id, 
                bucket="clients", 
                config=self.config
            )
            client_bucket.set_attr(name=client_data["client_id"], data=client_data)
            
            # Update global index for fast lookup
            global_index = attribute.Attributes(
                actor_id="_global_registry", 
                bucket="client_index", 
                config=self.config
            )
            global_index.set_attr(name=client_data["client_id"], data=actor_id)
        
        def find_client(self, client_id: str) -> dict:
            """Find a client by ID using the global index."""
            # Look up actor ID from global index
            global_index = attribute.Attributes(
                actor_id="_global_registry", 
                bucket="client_index", 
                config=self.config
            )
            
            actor_id_attr = global_index.get_attr(name=client_id)
            if not actor_id_attr or "data" not in actor_id_attr:
                return None
            
            actor_id = actor_id_attr["data"]
            
            # Get client data from actor's bucket
            client_bucket = attribute.Attributes(
                actor_id=actor_id, 
                bucket="clients", 
                config=self.config
            )
            
            client_attr = client_bucket.get_attr(name=client_id)
            if client_attr and "data" in client_attr:
                return client_attr["data"]
            
            return None
        
        def list_clients_for_actor(self, actor_id: str) -> list:
            """List all clients for a specific actor."""
            client_bucket = attribute.Attributes(
                actor_id=actor_id, 
                bucket="clients", 
                config=self.config
            )
            
            bucket_data = client_bucket.get_bucket()
            if not bucket_data:
                return []
            
            clients = []
            for attr_data in bucket_data.values():
                if attr_data and "data" in attr_data:
                    clients.append(attr_data["data"])
            
            return clients

Testing
-------

The new interface makes testing much easier:

.. code-block:: python

    import unittest
    from actingweb.interface import ActingWebApp, ActorInterface
    
    class TestActingWebApp(unittest.TestCase):
        def setUp(self):
            self.app = ActingWebApp(
                aw_type="urn:test:example.com:test",
                database="dynamodb"
            )
            
        def test_property_hook(self):
            @self.app.property_hook("email")
            def handle_email(actor, operation, value, path):
                return value.lower() if operation == "put" else value
                
            # Test the hook directly
            actor = ActorInterface.create(creator="test@example.com", config=self.app.get_config())
            result = handle_email(actor, "put", "TEST@EXAMPLE.COM", [])
            self.assertEqual(result, "test@example.com")
            
        def test_actor_creation(self):
            actor = ActorInterface.create(creator="test@example.com", config=self.app.get_config())
            self.assertIsNotNone(actor.id)
            self.assertEqual(actor.creator, "test@example.com")
        
        def test_attribute_storage(self):
            from actingweb import attribute
            
            # Test bucket operations
            bucket = attribute.Attributes(
                actor_id="_test_global", 
                bucket="test_data", 
                config=self.app.get_config()
            )
            
            # Store and retrieve data
            bucket.set_attr(name="test_key", data={"value": 42})
            
            result = bucket.get_attr(name="test_key")
            self.assertIsNotNone(result)
            self.assertEqual(result["data"]["value"], 42)