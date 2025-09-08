Configuration Reference
=======================

This page summarizes configuration for building applications with the ActingWeb Python library. Use the fluent `ActingWebApp` API in applications; it produces a `Config` object (``actingweb.config.Config``) that drives behavior.

Quick Start
-----------

.. code-block:: python

    from actingweb.interface import ActingWebApp

    app = ActingWebApp(
        aw_type="urn:actingweb:example.com:myapp",
        database="dynamodb",
        fqdn="myapp.example.com",
        proto="https://"
    ).with_oauth(client_id="...", client_secret="...") \
     .with_web_ui(enable=True) \
     .with_devtest(enable=False) \
     .add_actor_type("myself", relationship="friend")

    config = app.get_config()  # actingweb.config.Config

Core Identity
-------------

- ``aw_type``: ActingWeb type URI for your app (required).
- ``fqdn``: Hostname used for URLs (e.g., ``myapp.example.com``).
- ``proto``: URL scheme (``https://`` recommended).
- ``version``: Populated from library version; can be displayed to clients.

Runtime Switches
----------------

- ``ui``: Enable ``/<actor_id>/www`` web UI (``with_web_ui()``).
- ``devtest``: Enable development endpoints; MUST be ``False`` in production.
- ``www_auth``: ``basic`` or ``oauth``; set by ``with_oauth()``.
- ``unique_creator``: Enforce one actor per creator (``with_unique_creator()``).
- ``force_email_prop_as_creator``: Copy ``email`` property to ``creator``.
- ``mcp``: Include MCP capability; toggle via ``with_mcp()``.

OAuth2
------

Configured by ``with_oauth(...)``. Common fields:

- ``client_id``, ``client_secret``: Provider credentials.
- ``redirect_uri``: Defaults to ``{proto}{fqdn}/oauth``.
- ``auth_uri``, ``token_uri``: Authorization and token endpoints.
- ``scope``: Provider-specific scopes.

Actors Registry
---------------

``actors`` maps short names to known actor factories:

.. code-block:: python

    app.add_actor_type("myself", factory=f"{app.proto}{app.fqdn}/", relationship="friend")

Database
--------

- ``database``: ``dynamodb`` (default). See ``docs/actingweb.db_dynamodb`` for module APIs.
- AWS production: configure credentials/IAM and tables appropriately.
- Local dev: DynamoDB Local is supported.

Database Setup (DynamoDB)
-------------------------

Local Development (DynamoDB Local)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    docker run -p 8000:8000 amazon/dynamodb-local
    export AWS_ACCESS_KEY_ID=local
    export AWS_SECRET_ACCESS_KEY=local
    export AWS_DEFAULT_REGION=us-east-1
    export AWS_DB_HOST=http://localhost:8000  # PynamoDB host override for local

Point your app to DynamoDB Local via these environment variables (no code changes needed). The library uses its bundled PynamoDB models to create/access required tables at runtime.

Production (AWS DynamoDB)
~~~~~~~~~~~~~~~~~~~~~~~~~

- Configure IAM with least-privilege on the app’s tables: ``dynamodb:GetItem``, ``PutItem``, ``UpdateItem``, ``DeleteItem``, ``Query``, ``Scan``.
- Ensure tables exist (actor, properties, attributes, subscriptions, trust, and related indexes) before first traffic; the library’s DB modules are under ``actingweb.db_dynamodb``.
- Set region/credentials via standard AWS mechanisms (env vars, instance roles, profiles).

Logging
-------

- ``logLevel``: ``DEBUG``, ``INFO``, or ``WARN``; defaults can be overridden with env var ``LOG_LEVEL``.

Environment Variables
---------------------

Convenience env vars read by the interface layer:

- ``APP_HOST_FQDN``: Default for ``fqdn`` if not provided.
- ``APP_HOST_PROTOCOL``: Default for ``proto`` if not provided.
- ``LOG_LEVEL``: Overrides logging level.
- ``APP_BOT_TOKEN``, ``APP_BOT_EMAIL``, ``APP_BOT_SECRET``, ``APP_BOT_ADMIN_ROOM``: Used by ``with_bot()``.

URLs and Base Paths
-------------------

- ``root``: Computed as ``{proto}{fqdn}/``. Templates receive ``actor_root`` and ``actor_www`` (see :doc:`www-handler-templates`).
- Deployments under a base path are supported by integrations; avoid relative paths in templates.

MCP Capability
--------------

- Toggle with ``ActingWebApp.with_mcp(enable=True|False)``.
- When enabled, ``mcp`` appears in supported options returned by meta discovery.

Notes
-----

- Always use ``ActorInterface`` in applications; the internal ``Actor`` class is for framework use.
- Prefer property lists for large or growing collections; see :doc:`developers` for guidance.
