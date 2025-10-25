WWW Handler and Templates
=========================

The WWW Handler provides a web-based user interface for ActingWeb actors, allowing users to manage properties, trust relationships, and other actor functionality through a browser interface.

Overview
--------

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
- ``/<actor_id>/www/trust/new`` - Add new trust relationship
- ``/<actor_id>/www/init`` - Actor initialization

Web Interface Features
----------------------

Dashboard
---------

The main dashboard (``/<actor_id>/www``) provides:

- Actor information (ID, creator, status)
- Quick actions to access different sections
- Links to property management, trust relationships, and initialization

Properties Management
---------------------

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
-------------------

The trust interface (``/<actor_id>/www/trust``) allows users to:

- View existing trust relationships with permission status indicators
- View and edit relationship-specific permissions 
- Approve pending relationships
- Manage trust connections with other actors

**Add New Trust Relationship** (``/<actor_id>/www/trust/new``):

- Form-based trust relationship creation
- Select trust type from configured registry
- Specify peer actor URL and relationship details  
- Creates reciprocal trust relationships
- Relationship names must be URL-safe (letters, numbers, underscores, hyphens only)

Property Hooks and Web Interface
--------------------------------

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
--------------------

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
----------------

The WWW Handler uses Jinja2 templates that can be customized for your application.

Template Location
-----------------

Templates should be placed in a ``templates/`` directory in your application root:

.. code-block:: text

    your-app/
    ├── application.py
    ├── templates/
    │   ├── aw-actor-www-root.html
    │   ├── aw-actor-www-properties.html
    │   ├── aw-actor-www-property.html
    │   ├── aw-actor-www-property-delete.html
    │   ├── aw-actor-www-trust.html
    │   ├── aw-actor-www-trust-new.html
    │   ├── aw-actor-www-init.html
    │   ├── aw-oauth-authorization-form.html
    │   ├── aw-root-factory.html
    │   ├── aw-root-created.html
    │   └── aw-root-failed.html
    └── static/
        ├── style.css
        └── favicon.png

Available Templates
-------------------

**aw-actor-www-root.html**
    Main dashboard template

    Available variables:
    - ``url``: Base URL for navigation (includes ``/www``) - **backwards compatible**
    - ``actor_root``: Actor base URL (e.g., ``/mcp-server/actor123``) - **NEW**
    - ``actor_www``: Actor www URL (e.g., ``/mcp-server/actor123/www``) - **NEW**
    - ``id``: Actor ID
    - ``creator``: Actor creator
    - ``passphrase``: Actor passphrase

**aw-actor-www-properties.html**
    Properties list template

    Available variables:
    - ``url``: Base URL for navigation (includes ``/www``) - **backwards compatible**
    - ``actor_root``: Actor base URL (e.g., ``/mcp-server/actor123``) - **NEW**
    - ``actor_www``: Actor www URL (e.g., ``/mcp-server/actor123/www``) - **NEW**
    - ``id``: Actor ID
    - ``properties``: Dictionary of property name → value
    - ``read_only_properties``: Set of property names that are read-only
    - ``list_properties``: Set of property names that are list properties

**aw-actor-www-property.html**
    Individual property editing template

    Available variables:
    - ``url``: Actor www URL (e.g., ``/mcp-server/actor123/www``) - **backwards compatible**
    - ``actor_root``: Actor base URL (e.g., ``/mcp-server/actor123``) - **NEW**
    - ``actor_www``: Actor www URL (e.g., ``/mcp-server/actor123/www``) - **NEW**
    - ``id``: Actor ID
    - ``property``: Property name
    - ``value``: Property value (display value for list properties)
    - ``raw_value``: Raw property value
    - ``qual``: Property status ("a" if exists, "n" if not)
    - ``is_read_only``: Boolean indicating if property is read-only
    - ``is_list_property``: Boolean indicating if this is a list property
    - ``list_items``: List of items (for list properties)
    - ``list_description``: Description of list property
    - ``list_explanation``: Explanation of list property

**aw-actor-www-property-delete.html**
    Property deletion confirmation template

    Available variables:
    - ``url``: Actor base URL (without ``/www``)
    - ``id``: Actor ID
    - ``property``: Property name to be deleted
    - ``value``: Property value

**aw-actor-www-trust.html**
    Trust relationships template

    Available variables:
    - ``url``: Base URL for navigation
    - ``id``: Actor ID
    - ``trusts``: List of trust relationship objects
    - ``trust_connections``: Connection metadata for each trust with ``peerid``, ``established_via``, ``created_at``, ``last_connected_at``, and ``last_connected_via``

**aw-actor-www-trust-new.html**
    Add new trust relationship form template

    Available variables:
    - ``url``: Base URL for navigation
    - ``id``: Actor ID
    - ``form_action``: Form submission URL
    - ``form_method``: HTTP method for form (typically "POST")
    - ``trust_types``: List of available trust types from registry
    - ``error``: Error message if trust types are not configured
    - ``default_relationship``: Default relationship name

**aw-actor-www-init.html**
    Actor initialization template

    Available variables:
    - ``url``: Base URL for navigation (includes ``/www``) - **backwards compatible**
    - ``actor_root``: Actor base URL (e.g., ``/mcp-server/actor123``) - **NEW**
    - ``actor_www``: Actor www URL (e.g., ``/mcp-server/actor123/www``) - **NEW**
    - ``id``: Actor ID

**aw-oauth-authorization-form.html**
    OAuth2 authorization form template

    Available variables:
    - ``client_name``: Name of the OAuth2 client
    - ``scope``: Requested OAuth2 scope
    - ``trust_types``: Available trust types for OAuth2 clients
    - ``default_trust_type``: Default trust type selection
    - ``form_action``: Authorization form submission URL
    - ``email_hint``: Pre-filled email for authorization

**aw-root-factory.html**
    Root actor creation form template

    Available variables:
    - ``form_action``: Form submission URL
    - ``form_method``: HTTP method for form
    - ``error``: Error message if creation failed

**aw-root-created.html**
    Actor creation success template

    Available variables:
    - ``id``: Newly created actor ID
    - ``creator``: Creator email
    - ``passphrase``: Generated actor passphrase

**aw-root-failed.html**
    Actor creation failure template

    Available variables:
    - ``error``: Error message explaining the failure
    - ``form_action``: Form submission URL to retry

Template URL Variables
----------------------

**NEW in ActingWeb v3.2**: All templates now receive consistent URL variables for navigation.

**Template Variables Explained:**

- **``actor_root``**: Actor base URL (e.g., ``/mcp-server/actor123``)
  
  - Use for dashboard and non-www pages: ``{{ actor_root }}/dashboard/memory``
  - Use for actor-level endpoints: ``{{ actor_root }}/properties``

- **``actor_www``**: Actor www URL (e.g., ``/mcp-server/actor123/www``)
  
  - Use for www pages: ``{{ actor_www }}/properties``
  - Use for navigation within the www section

- **``url``**: Backwards compatible variable that points to ``actor_www``
  
  - Existing templates continue to work unchanged
  - Recommended to use ``actor_www`` or ``actor_root`` for clarity

**Navigation Examples:**

.. code-block:: html

    <!-- Navigation with new variables -->
    <nav>
        <a href="{{ actor_www }}">🏠 Home</a>
        <a href="{{ actor_root }}/dashboard/memory">🧠 My Memory</a>
        <a href="{{ actor_root }}/dashboard/setup">Connect AI</a>
        <a href="{{ actor_www }}/properties">Properties</a>
        <a href="{{ actor_www }}/trust">Trust</a>
    </nav>

    <!-- Backwards compatible (still works) -->
    <nav>
        <a href="{{ url }}">Dashboard</a>
        <a href="{{ url }}/properties">Properties</a>
        <a href="{{ url }}/trust">Trust</a>
    </nav>

**Critical: Never use relative paths** like ``../www`` as they create incorrect URLs when on sub-pages.

Template Customization
----------------------

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
-------------

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
--------------------------

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
------------------

Use the consistent URL variables for navigation:

.. code-block:: html

    <!-- Recommended: Use specific variables -->
    <nav>
        <a href="{{ actor_www }}">Dashboard</a>
        <a href="{{ actor_www }}/properties">Properties</a>
        <a href="{{ actor_www }}/trust">Trust</a>
        <a href="{{ actor_root }}/dashboard/memory">My Memory</a>
        <a href="{{ actor_root }}/dashboard/setup">Setup</a>
    </nav>

    <!-- Legacy: Still works but less clear -->
    <nav>
        <a href="{{ url }}">Dashboard</a>
        <a href="{{ url }}/properties">Properties</a>
        <a href="{{ url }}/trust">Trust</a>
    </nav>

**New consistent behavior**: All templates now receive both ``actor_root`` and ``actor_www`` variables, eliminating confusion about URL structure.

Security Considerations
-----------------------

Property Protection
-------------------

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
--------------------------

The WWW Handler integrates with ActingWeb's authentication system:

- OAuth2 authentication is automatically enforced
- Users must authenticate before accessing any www endpoints
- Only the actor creator can access the web interface
- Sessions are managed automatically

URL Structure and Base Paths
----------------------------

The WWW Handler supports flexible URL structures for different deployment scenarios:

Basic Structure
---------------

.. code-block:: text

    /<actor_id>/www                    # Dashboard
    /<actor_id>/www/properties         # Properties list
    /<actor_id>/www/properties/name    # Edit property
    /<actor_id>/www/trust              # Trust relationships
    /<actor_id>/www/trust/new          # Add new trust relationship
    /<actor_id>/www/init               # Initialization

With Base Paths (e.g., deployed under /mcp-server)
--------------------------------------------------

.. code-block:: text

    /mcp-server/<actor_id>/www                    # Dashboard
    /mcp-server/<actor_id>/www/properties         # Properties list
    /mcp-server/<actor_id>/www/properties/name    # Edit property
    /mcp-server/<actor_id>/www/trust              # Trust relationships
    /mcp-server/<actor_id>/www/trust/new          # Add new trust relationship

The templates automatically handle base paths by using the ``url`` variable provided by the handler.

Best Practices
--------------

1. **Consistent Styling**: Use a consistent CSS framework across all templates
2. **Responsive Design**: Ensure templates work on mobile devices
3. **Error Handling**: Include error states and messaging in templates
4. **Loading States**: Show loading indicators for long operations
5. **Accessibility**: Include proper ARIA labels and semantic HTML
6. **Property Hook Integration**: Design templates to work seamlessly with property protection
7. **Navigation Consistency**: Use the provided URL variables for navigation

Example: Complete Custom Template
---------------------------------

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
