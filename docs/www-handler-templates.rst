============================
WWW Handler and Templates
============================

The WWW Handler provides a web-based user interface for ActingWeb actors, allowing users to manage properties, trust relationships, and other actor functionality through a browser interface.

Overview
========

The WWW Handler is automatically enabled when you configure your ActingWeb application with ``.with_web_ui()``:

.. code-block:: python

    app = ActingWebApp(
        aw_type="urn:actingweb:example.com:myapp",
        database="dynamodb",
        fqdn="myapp.example.com"
    ).with_web_ui()

This creates several web endpoints:

- ``/<actor_id>/www`` - Actor dashboard
- ``/<actor_id>/www/properties`` - Property management
- ``/<actor_id>/www/properties/<name>`` - Individual property editing
- ``/<actor_id>/www/trust`` - Trust relationship management
- ``/<actor_id>/www/init`` - Actor initialization

Web Interface Features
======================

Dashboard
---------

The main dashboard (``/<actor_id>/www``) provides:

- Actor information (ID, creator, status)
- Quick actions to access different sections
- Links to property management, trust relationships, and initialization

Properties Management
--------------------

**Properties List** (``/<actor_id>/www/properties``):

- Displays all accessible properties in a table format
- Shows property names, values, and available actions
- Automatically filters out hidden properties based on property hooks
- Displays "Read-only" badges for protected properties
- Provides Edit/Delete actions for editable properties
- Shows "View Only" for protected properties

**Individual Property Editing** (``/<actor_id>/www/properties/<name>``):

- **Editable properties**: Shows a form with textarea for direct editing
- **Read-only properties**: Shows value in a styled display box with protection notice
- Automatically determines editability based on property hook responses
- Delete functionality is disabled for protected properties

Trust Relationships
------------------

The trust interface (``/<actor_id>/www/trust``) allows users to:

- View existing trust relationships
- Approve pending relationships
- Manage trust connections with other actors

Property Hooks and Web Interface
================================

Property hooks directly control what users see and can do in the web interface:

Hidden Properties
-----------------

Properties that return ``None`` for GET operations are completely hidden from the web interface:

.. code-block:: python

    @app.property_hook("*")
    def handle_all_properties(actor, operation, value, path):
        property_name = path[0] if path else ""
        
        if property_name in ["email", "auth_token"] and operation == "get":
            return None  # Hidden from web interface
        
        return value

**Result**: These properties won't appear in the properties list at all.

Read-Only Properties
-------------------

Properties that return ``None`` for PUT/POST operations are marked as read-only:

.. code-block:: python

    @app.property_hook("*")
    def handle_all_properties(actor, operation, value, path):
        property_name = path[0] if path else ""
        
        if property_name in ["created_at", "actor_type"] and operation in ["put", "post"]:
            return None  # Read-only in web interface
        
        return value

**Result**: 
- Properties list shows "Read-only" badge and "View Only" button
- Individual property page shows value in read-only display
- Edit form and delete button are disabled

Template System
================

The WWW Handler uses Jinja2 templates that can be customized for your application.

Template Location
----------------

Templates should be placed in a ``templates/`` directory in your application root:

.. code-block:: text

    your-app/
    ├── application.py
    ├── templates/
    │   ├── aw-actor-www-root.html
    │   ├── aw-actor-www-properties.html
    │   ├── aw-actor-www-property.html
    │   ├── aw-actor-www-trust.html
    │   └── aw-actor-www-init.html
    └── static/
        ├── style.css
        └── favicon.png

Available Templates
------------------

**aw-actor-www-root.html**
    Main dashboard template

    Available variables:
    - ``url``: Base URL for navigation (includes ``/www``)
    - ``id``: Actor ID
    - ``creator``: Actor creator
    - ``passphrase``: Actor passphrase

**aw-actor-www-properties.html**
    Properties list template

    Available variables:
    - ``url``: Base URL for navigation
    - ``id``: Actor ID
    - ``properties``: Dictionary of property name → value
    - ``read_only_properties``: Set of property names that are read-only

**aw-actor-www-property.html**
    Individual property editing template

    Available variables:
    - ``url``: Actor base URL (without ``/www``)
    - ``id``: Actor ID
    - ``property``: Property name
    - ``value``: Property value
    - ``qual``: Property status ("a" if exists, "n" if not)
    - ``is_read_only``: Boolean indicating if property is read-only

**aw-actor-www-trust.html**
    Trust relationships template

    Available variables:
    - ``url``: Base URL for navigation
    - ``id``: Actor ID
    - ``trusts``: List of trust relationship objects

**aw-actor-www-init.html**
    Actor initialization template

    Available variables:
    - ``url``: Base URL for navigation
    - ``id``: Actor ID

Template Customization
---------------------

You can customize templates by creating your own versions. Here's an example of customizing the properties template:

.. code-block:: html

    <!-- templates/aw-actor-www-properties.html -->
    <!DOCTYPE html>
    <html>
    <head>
        <title>{{ id }} - Properties</title>
        <link rel="stylesheet" href="/static/style.css">
    </head>
    <body>
        <h1>Properties for Actor {{ id }}</h1>
        
        <table>
            <thead>
                <tr>
                    <th>Name</th>
                    <th>Value</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                {% for name, value in properties.items() %}
                <tr>
                    <td>
                        {{ name }}
                        {% if name in read_only_properties %}
                        <span class="badge read-only">Read-only</span>
                        {% endif %}
                    </td>
                    <td>{{ value }}</td>
                    <td>
                        {% if name not in read_only_properties %}
                        <a href="{{ url }}/properties/{{ name }}">Edit</a>
                        <a href="{{ url }}/properties/{{ name }}?_method=DELETE">Delete</a>
                        {% else %}
                        <span class="disabled">View Only</span>
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </body>
    </html>

Static Assets
=============

Static files (CSS, JavaScript, images) should be placed in a ``static/`` directory:

.. code-block:: text

    static/
    ├── style.css        # Main stylesheet
    ├── favicon.png      # Favicon
    ├── logo.png         # Logo images
    └── app.js          # Custom JavaScript

These files are served at ``/static/`` URLs and can be referenced in templates:

.. code-block:: html

    <link rel="stylesheet" href="/static/style.css">
    <script src="/static/app.js"></script>
    <img src="/static/logo.png" alt="Logo">

Advanced Template Features
==========================

Conditional Content Based on Property Status
--------------------------------------------

Templates can show different content based on property protection:

.. code-block:: html

    {% for name, value in properties.items() %}
    <div class="property">
        <h3>{{ name }}</h3>
        
        {% if name in read_only_properties %}
        <!-- Read-only property display -->
        <div class="read-only-property">
            <div class="value-display">{{ value }}</div>
            <p class="help-text">This property is protected and cannot be modified.</p>
        </div>
        {% else %}
        <!-- Editable property -->
        <div class="editable-property">
            <textarea name="value">{{ value }}</textarea>
            <button onclick="saveProperty('{{ name }}')">Save</button>
        </div>
        {% endif %}
    </div>
    {% endfor %}

Dynamic Navigation
-----------------

Use the provided URL variables for consistent navigation:

.. code-block:: html

    <nav>
        <a href="{{ url }}">Dashboard</a>
        <a href="{{ url }}/properties">Properties</a>
        <a href="{{ url }}/trust">Trust</a>
        <a href="{{ url }}/init">Initialize</a>
    </nav>

Note that ``url`` in most templates includes ``/www``, but in individual property templates, it's the actor base URL without ``/www``.

Security Considerations
======================

Property Protection
------------------

The web interface automatically enforces property hook security:

1. **Hidden properties** (hooks return ``None`` for GET) are never displayed
2. **Read-only properties** (hooks return ``None`` for PUT/POST) cannot be edited
3. **Protected deletions** (hooks return ``None`` for DELETE) cannot be deleted

Template Security
-----------------

- Always use Jinja2's automatic escaping for user content
- Validate property values before displaying
- Use CSRF protection for forms (if implementing custom forms)

.. code-block:: html

    <!-- Safe: automatically escaped -->
    <div>{{ value }}</div>
    
    <!-- Unsafe: don't use |safe unless you trust the content -->
    <div>{{ value|safe }}</div>

Authentication Integration
=========================

The WWW Handler integrates with ActingWeb's authentication system:

- OAuth2 authentication is automatically enforced
- Users must authenticate before accessing any www endpoints
- Only the actor creator can access the web interface
- Sessions are managed automatically

URL Structure and Base Paths
============================

The WWW Handler supports flexible URL structures for different deployment scenarios:

Basic Structure
--------------

.. code-block:: text

    /<actor_id>/www                    # Dashboard
    /<actor_id>/www/properties         # Properties list
    /<actor_id>/www/properties/name    # Edit property
    /<actor_id>/www/trust              # Trust relationships
    /<actor_id>/www/init               # Initialization

With Base Paths (e.g., deployed under /mcp-server)
-------------------------------------------------

.. code-block:: text

    /mcp-server/<actor_id>/www                    # Dashboard
    /mcp-server/<actor_id>/www/properties         # Properties list
    /mcp-server/<actor_id>/www/properties/name    # Edit property

The templates automatically handle base paths by using the ``url`` variable provided by the handler.

Best Practices
==============

1. **Consistent Styling**: Use a consistent CSS framework across all templates
2. **Responsive Design**: Ensure templates work on mobile devices
3. **Error Handling**: Include error states and messaging in templates
4. **Loading States**: Show loading indicators for long operations
5. **Accessibility**: Include proper ARIA labels and semantic HTML
6. **Property Hook Integration**: Design templates to work seamlessly with property protection
7. **Navigation Consistency**: Use the provided URL variables for navigation

Example: Complete Custom Template
=================================

Here's a complete example of a custom properties template with modern styling:

.. code-block:: html

    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Properties - {{ id }}</title>
        <link rel="stylesheet" href="/static/style.css">
    </head>
    <body>
        <header>
            <nav>
                <a href="{{ url }}">Dashboard</a>
                <a href="{{ url }}/properties" class="active">Properties</a>
                <a href="{{ url }}/trust">Trust</a>
            </nav>
            <h1>Actor Properties</h1>
            <p>Manage properties for actor {{ id }}</p>
        </header>

        <main>
            {% if properties %}
            <div class="properties-grid">
                {% for name, value in properties.items() %}
                <div class="property-card">
                    <div class="property-header">
                        <h3>{{ name }}</h3>
                        {% if name in read_only_properties %}
                        <span class="badge badge-readonly">Read-only</span>
                        {% endif %}
                    </div>
                    
                    <div class="property-value">
                        {% if value|length > 100 %}
                        <details>
                            <summary>{{ value[:100] }}...</summary>
                            <pre>{{ value }}</pre>
                        </details>
                        {% else %}
                        <pre>{{ value }}</pre>
                        {% endif %}
                    </div>
                    
                    <div class="property-actions">
                        {% if name not in read_only_properties %}
                        <a href="{{ url }}/properties/{{ name }}" class="btn btn-primary">Edit</a>
                        <a href="{{ url }}/properties/{{ name }}?_method=DELETE" 
                           class="btn btn-danger"
                           onclick="return confirm('Delete {{ name }}?')">Delete</a>
                        {% else %}
                        <span class="btn btn-disabled">Protected</span>
                        {% endif %}
                    </div>
                </div>
                {% endfor %}
            </div>
            {% else %}
            <div class="empty-state">
                <p>No properties found.</p>
                <a href="{{ url }}/init" class="btn btn-primary">Add Properties</a>
            </div>
            {% endif %}
        </main>
    </body>
    </html>

This template demonstrates:

- Responsive grid layout for properties
- Proper use of ``read_only_properties`` set
- Conditional actions based on property protection
- Modern UI patterns with cards and badges
- Proper navigation using provided URL variables